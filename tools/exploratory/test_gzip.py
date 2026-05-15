#!/usr/bin/env python3
"""
Test if gzip decompression is working
"""
import asyncio
import httpx
from bs4 import BeautifulSoup
import re

async def test_gzip():
    url = "https://discosborabora.com/?s=Radiohead+OK+Computer"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
    }
    
    # Don't specify Accept-Encoding, let httpx handle it
    async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
        response = await client.get(url)
        
        print(f"Status: {response.status_code}")
        print(f"Content-Encoding: {response.headers.get('content-encoding', 'none')}")
        print(f"Content-Type: {response.headers.get('content-type', 'none')}")
        print(f"Content-Length header: {response.headers.get('content-length', 'none')}")
        print(f"Actual content length: {len(response.content)}")
        print(f"Text length: {len(response.text)}")
        print(f"\nFirst 200 chars of text:")
        print(response.text[:200])
        
        soup = BeautifulSoup(response.text, 'lxml')
        products = soup.find_all('article', class_=re.compile(r'post-entry', re.I))
        print(f"\nProducts found: {len(products)}")

if __name__ == "__main__":
    asyncio.run(test_gzip())
