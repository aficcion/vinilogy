#!/usr/bin/env python3
"""
Debug Bora Bora scraping step by step
"""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv
import re
from bs4 import BeautifulSoup
import httpx

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from services.pricing.pricing_client import normalize


async def debug_step_by_step():
    """Debug each step of Bora Bora scraping"""
    
    artist = "Radiohead"
    album = "OK Computer"
    query = f"{artist} {album}".replace(" ", "+")
    search_url = f"https://discosborabora.com/?s={query}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }
    
    print("=" * 80)
    print("BORA BORA SCRAPING DEBUG")
    print("=" * 80)
    
    # Step 1: Fetch search page
    print(f"\n1. Fetching: {search_url}")
    async with httpx.AsyncClient() as client:
        response = await client.get(search_url, headers=headers, timeout=10.0, follow_redirects=True)
        print(f"   Status: {response.status_code}")
        print(f"   URL after redirects: {response.url}")
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Step 2: Find products
        print(f"\n2. Finding products...")
        products = soup.find_all('article', class_=re.compile(r'post-entry', re.I))
        print(f"   Found {len(products)} article.post-entry elements")
        
        if not products:
            print("   ❌ NO PRODUCTS FOUND!")
            # Try alternative selectors
            print("\n   Trying alternative selectors...")
            alt_products = soup.find_all('article')
            print(f"   Found {len(alt_products)} total <article> elements")
            if alt_products:
                for i, p in enumerate(alt_products[:3]):
                    classes = ' '.join(p.get('class', []))
                    print(f"     [{i}] classes: {classes[:80]}")
            return
        
        # Step 3: Process each product
        print(f"\n3. Processing products...")
        artist_norm = normalize(artist)
        album_norm = normalize(album)
        
        for i, product in enumerate(products[:3]):
            print(f"\n   Product {i+1}:")
            
            # Find title
            title_elem = product.find('h2', class_=re.compile(r'post-title|entry-title', re.I))
            if not title_elem:
                print(f"     ❌ No h2.post-title found")
                continue
            
            link_elem = title_elem.find('a', href=True)
            if not link_elem:
                print(f"     ❌ No <a> inside h2")
                continue
            
            product_url = link_elem.get('href')
            title = link_elem.get_text(strip=True)
            title_norm = normalize(title)
            
            print(f"     ✓ Title: {title}")
            print(f"     ✓ URL: {product_url}")
            print(f"     ✓ Normalized: {title_norm}")
            
            # Calculate score
            score = 0
            artist_words = artist_norm.split()
            album_words = album_norm.split()
            
            if any(word in title_norm for word in artist_words if len(word) > 2):
                score += 3
                print(f"     ✓ Artist match: +3")
            
            album_match_count = sum(1 for word in album_words if len(word) > 2 and word in title_norm)
            score += album_match_count * 2
            print(f"     ✓ Album words matched: {album_match_count} (+{album_match_count * 2})")
            
            # Check for special editions
            special_keywords = ['deluxe', 'remaster', 'remastered', 'reissue', 'anniversary']
            penalties = sum(5 for kw in special_keywords if kw in title_norm)
            if penalties:
                print(f"     ⚠️  Special edition penalty: -{penalties}")
                score -= penalties
            
            print(f"     📊 Final score: {score}")
            
            if i == 0:  # Try to fetch detail page for first product
                print(f"\n4. Fetching detail page: {product_url}")
                detail_response = await client.get(product_url, headers=headers, timeout=10.0)
                detail_soup = BeautifulSoup(detail_response.text, 'lxml')
                
                # Find price
                price_elem = detail_soup.find(class_=re.compile(r'price|precio|amount', re.I))
                if price_elem:
                    price_text = price_elem.get_text(strip=True)
                    print(f"   ✓ Price element found: {price_text}")
                    price_match = re.search(r'(\d+)[.,](\d+)\s*€?', price_text)
                    if price_match:
                        price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                        print(f"   ✓ Price extracted: €{price}")
                else:
                    print(f"   ❌ No price element found")
                    # Try meta tag
                    price_meta = detail_soup.find('meta', property='product:price:amount')
                    if price_meta:
                        print(f"   ✓ Found price in meta: {price_meta.get('content')}")


if __name__ == "__main__":
    asyncio.run(debug_step_by_step())
