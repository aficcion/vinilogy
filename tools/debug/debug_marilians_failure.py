
import asyncio
import sys
import os
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
import re

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Copy-paste normalize to ensure we test the exact current logic
def normalize(text: str) -> str:
    """Normaliza strings para comparaciones simples."""
    return (
        text.lower()
        .replace(",", " ")
        .replace("-", " ")
        .replace("_", " ")
        .replace("/", " ")
        .strip()
    )

async def debug_marilians():
    artist = "Deerhunter"
    album = "Microcastle / Weird Era Continued"
    
    print(f"--- Debugging: {artist} - {album} ---")
    
    # 1. Query Generation
    clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
    query = clean_query.replace(" ", "+")
    url = f"https://www.marilians.com/busqueda?controller=search&s={query}"
    
    print(f"Generated URL: {url}")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        response = await client.get(url)
        print(f"Response Status: {response.status_code}")
        
        soup = BeautifulSoup(response.text, 'lxml')
        
        products = soup.find_all(['article', 'div'], class_=re.compile(r'product', re.I))
        if not products:
             products = soup.find_all(['div', 'li'], class_=re.compile(r'item|result', re.I))
             
        print(f"Found {len(products)} potential products.")
        
        artist_norm = normalize(artist)
        album_norm = normalize(album)
        print(f"Normalized Target: '{artist_norm}' - '{album_norm}'")
        
        for i, product in enumerate(products):
            print(f"\n--- Product {i+1} ---")
            
            title_elem = product.find(['h2', 'h3', 'h4', 'a'], class_=re.compile(r'name|title|product', re.I))
            if not title_elem:
                title_elem = product.find('a', href=True)
            
            if not title_elem:
                print("No title element found")
                continue
                
            title = title_elem.get_text(strip=True)
            
            # Check for artist in separate h5 element (Marilians structure)
            artist_elem = product.find('h5')
            artist_text = artist_elem.get_text(strip=True) if artist_elem else ""
            
            # Combine title and artist for matching
            combined_text = f"{artist_text} {title}"
            title_norm = normalize(combined_text)
            
            print(f"Title: {title}")
            if artist_text:
                print(f"Artist (from h5): {artist_text}")
            print(f"Combined: {combined_text}")
            print(f"Norm Title: {title_norm}")

            if "microcastle" in title_norm:
                print(f"MATCH FOUND! Raw HTML:\n{product.prettify()}")

            
            # Helper to check matching score
            score = 0
            artist_words = [w for w in artist_norm.split() if len(w) > 1]
            album_words = [w for w in album_norm.split() if len(w) > 1]
            
            print(f"Artist Words: {artist_words}")
            print(f"Album Words: {album_words}")

            # Check artist words
            artist_matches = sum(1 for word in artist_words if word in title_norm)
            if artist_matches == len(artist_words):
                 score += 50
                 print("  Artist: Full Match (+50)")
            elif artist_matches > 0:
                 score += 20 * (artist_matches / len(artist_words))
                 print(f"  Artist: Partial Match ({artist_matches}/{len(artist_words)})")
            else:
                 print("  Artist: No Match")

            # Check album words
            album_matches = sum(1 for word in album_words if word in title_norm)
            if album_matches == len(album_words):
                 score += 50
                 print("  Album: Full Match (+50)")
            elif album_matches > 0:
                 score += 20 * (album_matches / len(album_words))
                 print(f"  Album: Partial Match ({album_matches}/{len(album_words)})")
            else:
                 print("  Album: No Match")
            
            print(f"Total Score: {score}")

if __name__ == "__main__":
    asyncio.run(debug_marilians())
