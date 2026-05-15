#!/usr/bin/env python3
"""
Compare HTTP responses between working and non-working clients
"""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv
import httpx
from bs4 import BeautifulSoup
import re

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from services.pricing.pricing_client import PricingClient


async def compare_clients():
    """Compare responses from different HTTP clients"""
    
    url = "https://discosborabora.com/?s=Radiohead+OK+Computer"
    
    print("=" * 80)
    print("COMPARING HTTP CLIENTS")
    print("=" * 80)
    
    # Test 1: Fresh client with headers
    print("\n1. Fresh httpx.AsyncClient with headers in init:")
    default_headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }
    
    async with httpx.AsyncClient(timeout=20.0, headers=default_headers, follow_redirects=True) as client:
        response = await client.get(url, timeout=10.0)
        print(f"   Status: {response.status_code}")
        print(f"   Content-Length: {len(response.text)}")
        soup = BeautifulSoup(response.text, 'lxml')
        products = soup.find_all('article', class_=re.compile(r'post-entry', re.I))
        print(f"   Products found: {len(products)}")
        print(f"   Request headers sent:")
        for key, value in response.request.headers.items():
            if key.lower() in ['user-agent', 'accept', 'accept-language']:
                print(f"     {key}: {value}")
    
    # Test 2: PricingClient
    print("\n2. PricingClient http_client:")
    pricing_client = PricingClient()
    await pricing_client.start()
    
    response = await pricing_client.http_client.get(url, timeout=10.0)
    print(f"   Status: {response.status_code}")
    print(f"   Content-Length: {len(response.text)}")
    soup = BeautifulSoup(response.text, 'lxml')
    products = soup.find_all('article', class_=re.compile(r'post-entry', re.I))
    print(f"   Products found: {len(products)}")
    print(f"   Request headers sent:")
    for key, value in response.request.headers.items():
        if key.lower() in ['user-agent', 'accept', 'accept-language', 'host']:
            print(f"     {key}: {value}")
    
    # Save both HTML responses for comparison
    with open('/tmp/bora_fresh_client.html', 'w') as f:
        f.write(response.text)
    
    await pricing_client.stop()
    
    print("\n3. Saved PricingClient response to: /tmp/bora_fresh_client.html")
    
    # Test 3: Check if it's a timing issue
    print("\n4. Testing with delay between requests:")
    await asyncio.sleep(2)
    
    async with httpx.AsyncClient(timeout=20.0, headers=default_headers, follow_redirects=True) as client:
        response = await client.get(url, timeout=10.0)
        soup = BeautifulSoup(response.text, 'lxml')
        products = soup.find_all('article', class_=re.compile(r'post-entry', re.I))
        print(f"   Products found after delay: {len(products)}")


if __name__ == "__main__":
    asyncio.run(compare_clients())
