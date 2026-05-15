#!/usr/bin/env python3
"""
Debug Bora Bora HTML structure
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

async def debug_bora_bora():
    query = "Radiohead+OK+Computer"
    url = f"https://discosborabora.com/?s={query}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, timeout=10.0, follow_redirects=True)
        soup = BeautifulSoup(response.text, 'lxml')
        
        print("=" * 80)
        print("BORA BORA HTML STRUCTURE")
        print("=" * 80)
        
        # Find all potential product containers
        print("\n1. Looking for product containers...")
        products = soup.find_all(['article', 'div'], class_=True)
        product_classes = set()
        for prod in products[:20]:
            classes = ' '.join(prod.get('class', []))
            if 'product' in classes.lower() or 'item' in classes.lower():
                product_classes.add(classes)
        
        print(f"   Found product-related classes:")
        for cls in list(product_classes)[:10]:
            print(f"     - {cls}")
        
        # Look for anything with "OK COMPUTER" in text
        print("\n2. Looking for 'OK COMPUTER' or 'Radiohead' text...")
        ok_computer_elements = soup.find_all(string=lambda text: text and ('OK COMPUTER' in text.upper() or 'RADIOHEAD' in text.upper()))
        for i, elem in enumerate(ok_computer_elements[:5]):
            parent = elem.parent
            print(f"   [{i}] Found in: <{parent.name}> class='{parent.get('class', [])}'")
            print(f"       Text: {elem.strip()[:100]}")
            # Find link
            link = parent.find('a', href=True) if parent.name != 'a' else parent
            if not link and parent.parent:
                link = parent.parent.find('a', href=True)
            if link:
                print(f"       Link: {link.get('href', 'N/A')}")
            print()
        
        # Save HTML for inspection
        with open('/tmp/bora_bora_debug.html', 'w') as f:
            f.write(response.text)
        print("\n3. Full HTML saved to: /tmp/bora_bora_debug.html")

if __name__ == "__main__":
    asyncio.run(debug_bora_bora())
