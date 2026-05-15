#!/usr/bin/env python3
"""
Test if httpx.AsyncClient with default headers works
"""
import asyncio
import httpx
from bs4 import BeautifulSoup
import re

async def test_with_default_headers():
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }
    
    # Test with headers in AsyncClient initialization
    async with httpx.AsyncClient(timeout=20.0, headers=default_headers, follow_redirects=True) as client:
        print("Testing with headers in AsyncClient init...")
        response = await client.get("https://discosborabora.com/?s=Radiohead+OK+Computer", timeout=10.0)
        soup = BeautifulSoup(response.text, 'lxml')
        products = soup.find_all('article', class_=re.compile(r'post-entry', re.I))
        print(f"Found {len(products)} products")
        
        if products:
            print("✅ SUCCESS! Headers working correctly")
        else:
            print("❌ FAIL! No products found")
            all_articles = soup.find_all('article')
            print(f"Total articles: {len(all_articles)}")

if __name__ == "__main__":
    asyncio.run(test_with_default_headers())
