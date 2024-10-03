import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
from dataclasses import dataclass
from typing import List, Tuple, Optional
import json
from datetime import datetime, timedelta
import random

@dataclass
class Product:
    url: str
    competitors: List[str]
    last_updated: datetime

def get_random_headers():
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
    ]
    
    headers = {
        'User-Agent': random.choice(user_agents),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://www.google.com/',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    }
    return headers

def extract_price(html_content, url):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Check meta tags
    meta_tags = [
        ("meta", {"name": "twitter:data1"}),
        ("meta", {"property": "og:price:amount"}),
        ("meta", {"property": "product:price:amount"}),
    ]
    for tag, attrs in meta_tags:
        meta_price = soup.find(tag, attrs)
        if meta_price:
            return parse_price(meta_price.get("content"))

    # 2. Check Schema.org microdata
    schema_price = soup.find("span", itemprop="price")
    if schema_price:
        return parse_price(schema_price.text)

    # 3. Check JSON-LD
    json_ld = soup.find("script", type="application/ld+json")
    if json_ld:
        try:
            data = json.loads(json_ld.string)
            if isinstance(data, list):
                data = data[0]
            if "offers" in data and "price" in data["offers"]:
                return parse_price(data["offers"]["price"])
        except json.JSONDecodeError:
            pass

    # 4. Fallback to HTML structure
    return find_price_in_html(soup)

def find_price_in_html(soup):
    # First, try to find the price near the H1 tag
    h1 = soup.find('h1')
    if h1:
        # Search for price within the next 5 siblings of H1
        for sibling in h1.find_next_siblings()[:5]:
            price = extract_price_from_element(sibling)
            if price:
                return price

    # If not found near H1, search for common price classes
    price_classes = ['price', 'product-price', 'regular-price', 'sales-price', 'current-price', 'woocommerce-Price-amount']
    for class_name in price_classes:
        price_elem = soup.find(class_=class_name)
        if price_elem:
            price = extract_price_from_element(price_elem)
            if price:
                return price

    return None

def extract_price_from_element(element):
    return parse_price(element.text.strip())

def parse_price(price_str):
    price_str = re.sub(r'[^\d,.]', '', price_str)
    price_str = price_str.replace(',', '.')
    try:
        price = float(price_str)
        return price if price >= 1.01 else None
    except ValueError:
        return None

def fetch_price(url: str) -> Tuple[Optional[float], Optional[str]]:
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        price = extract_price(response.text, url)
        if price is None:
            return None, "Price not found on the page or below 1.01 euro"
        return price, None
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            # Retry with more advanced headers
            try:
                response = requests.get(url, headers=get_random_headers(), timeout=10)
                response.raise_for_status()
                price = extract_price(response.text, url)
                if price is None:
                    return None, "Price not found on the page or below 1.01 euro"
                return price, None
            except requests.exceptions.RequestException as e:
                return None, f"Error fetching URL (with bypass): {str(e)}"
        return None, f"Error fetching URL: {str(e)}"
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"

def compare_prices(product: Product, progress_bar):
    results = []
    errors = []
    total_urls = len(product.competitors) + 1
    
    # Fetch product price
    progress_bar.progress(0)
    own_price, own_error = fetch_price(product.url)
    results.append((product.url, own_price))
    errors.append((product.url, own_error))
    progress_bar.progress(1 / total_urls)
    
    # Fetch competitor prices
    for i, comp_url in enumerate(product.competitors):
        comp_price, comp_error = fetch_price(comp_url)
        results.append((comp_url, comp_price))
        errors.append((comp_url, comp_error))
        progress_bar.progress((i + 2) / total_urls)
    
    progress_bar.progress(1.0)
    return results, errors

def analyze_results(product: Product, prices: List[Tuple[str, Optional[float]]], errors: List[Tuple[str, Optional[str]]]):
    own_price, own_error = prices[0][1], errors[0][1]
    competitor_prices = prices[1:]
    
    if own_price is None:
        return f"Unable to fetch price for {product.url}\nError: {own_error}"
    
    analysis = f"**Your product ({product.url})**\n\nYour price: €{own_price:.2f}\n\n"
    cheaper_count = 0
    equal_count = 0
    
    for i, (comp_url, comp_price) in enumerate(competitor_prices):
        if comp_price is None:
            comp_error = errors[i+1][1]
            analysis += f"Competitor {i+1}: Unable to fetch price\nError: {comp_error}\n"
        else:
            price_diff = own_price - comp_price
            percentage_diff = (price_diff / comp_price) * 100
            
            if price_diff > 0:
                analysis += f"Competitor {i+1}: :red[€{comp_price:.2f} (You are {percentage_diff:.2f}% more expensive)]\n"
            elif price_diff < 0:
                analysis += f"Competitor {i+1}: :green[€{comp_price:.2f} (You are {abs(percentage_diff):.2f}% cheaper)]\n"
                cheaper_count += 1
            else:
                analysis += f"Competitor {i+1}: :orange[€{comp_price:.2f} (Same price)]\n"
                equal_count += 1
    
    valid_competitor_count = sum(1 for _, price in competitor_prices if price is not None)
    if valid_competitor_count > 0:
        if cheaper_count == valid_competitor_count:
            analysis += "\n:green[You have the lowest price!]"
        elif cheaper_count + equal_count == valid_competitor_count:
            analysis += "\n:orange[Your price is the same as or lower than all competitors.]"
        elif cheaper_count > 0:
            analysis += f"\n:yellow[You are cheaper than {cheaper_count} out of {valid_competitor_count} competitors.]"
        else:
            analysis += "\n:red[Your price is higher than all competitors.]"
    else:
        analysis += "\nUnable to compare with competitors due to price fetch errors."
    
    return analysis

def main():
    st.set_page_config(page_title="Price Comparison App", layout="wide")
    
    st.markdown("""
    <style>
    .stApp {
        max-width: 1200px;
        margin: 0 auto;
        font-family: 'Helvetica', 'Arial', sans-serif;
    }
    .st-bx {
        background-color: #f8f9fa;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .stTextInput input {
        color: black !important;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("Price Comparison Tool")
    
    if 'products' not in st.session_state:
        st.session_state.products = []

    for i, product in enumerate(st.session_state.products):
        st.subheader(f"Product {i+1}")
        product.url = st.text_input(f"Product {i+1} URL", value=product.url, key=f"product_url_{i}")
        
        for j, comp_url in enumerate(product.competitors):
            product.competitors[j] = st.text_input(f"Competitor {j+1} URL", value=comp_url, key=f"comp_url_{i}_{j}")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button(f"+ Add Competitor", key=f"add_comp_{i}"):
                product.competitors.append("")
                st.rerun()
        
    if st.button("+ Add Product"):
        st.session_state.products.append(Product("", [""], datetime.now()))
        st.rerun()
    
    if st.button("Compare Prices", type="primary"):
        for i, product in enumerate(st.session_state.products):
            if product.url and product.competitors[0]:
                st.subheader(f"Analyzing Product {i+1}")
                progress_bar = st.progress(0)
                prices, errors = compare_prices(product, progress_bar)
                
                analysis = analyze_results(product, prices, errors)
                st.markdown(analysis)
                st.markdown("---")

                # Update last_updated timestamp
                product.last_updated = datetime.now()
            elif product.url:
                st.warning(f"Product {i+1} needs at least one competitor URL to compare.")

    # Clean up old products (older than 1 month)
    one_month_ago = datetime.now() - timedelta(days=30)
    st.session_state.products = [p for p in st.session_state.products if p.last_updated > one_month_ago]

if __name__ == "__main__":
    main()