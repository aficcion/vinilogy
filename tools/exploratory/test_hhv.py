"""
Test HHV (German vinyl store) with ScrapingBot
"""
import asyncio
import httpx
from bs4 import BeautifulSoup
import re

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_hhv():
    """Test HHV Records search"""
    
    print("=" * 70)
    print("Testing HHV Records (Germany)")
    print("=" * 70)
    
    # HHV search URL
    search_url = "https://www.hhv.de/en-ES/catalog/filter/search-S11?af=true&term=OK%20computer%20radiohead"
    
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    
    # Try without premium first
    payload = {
        "url": search_url,
        "options": {
            "useChrome": False,
            "premiumProxy": False,
            "proxyCountry": "DE"  # German proxy
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print(f"\n🔍 URL: {search_url}")
    print(f"🌍 Proxy: DE (Germany)")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            print("\n⏳ Sending request to ScrapingBot...")
            
            response = await client.post(
                endpoint,
                json=payload,
                headers=headers,
                auth=auth
            )
            
            print(f"\n✅ Response Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("error"):
                    print(f"❌ Error: {result['error']}")
                    return
                
                html = result.get("rawHtml", "")
                
                if not html:
                    print("❌ No HTML content")
                    return
                
                # Check for CAPTCHA/blocking
                if "captcha" in html.lower() or "just a moment" in html.lower():
                    print("❌ CAPTCHA/blocking detected")
                    return
                
                print(f"✅ Success! HTML Length: {len(html):,} characters")
                
                # Parse HTML
                soup = BeautifulSoup(html, 'lxml')
                
                # Look for products
                products = soup.find_all(['div', 'article'], class_=lambda x: x and ('product' in str(x).lower() or 'item' in str(x).lower()))
                
                print(f"\n🔍 Found {len(products)} potential product containers")
                
                # Look for prices (€ symbol)
                price_elements = soup.find_all(string=re.compile(r'€|EUR'))
                print(f"💰 Found {len(price_elements)} price elements")
                
                if price_elements:
                    print(f"\n📌 Sample prices:")
                    for i, price in enumerate(price_elements[:5], 1):
                        print(f"   {i}. {price.strip()}")
                
                # Look for product links
                links = soup.find_all('a', href=True)
                product_links = []
                for link in links:
                    href = link.get('href', '')
                    # HHV product URLs typically contain /shop/
                    if '/shop/' in href or '/product/' in href:
                        if href.startswith('/'):
                            href = f"https://www.hhv.de{href}"
                        product_links.append(href)
                
                print(f"\n🔗 Found {len(product_links)} product links")
                
                if product_links:
                    print(f"\n📌 First 3 product links:")
                    for i, link in enumerate(product_links[:3], 1):
                        print(f"   {i}. {link}")
                    
                    print(f"\n🎉 SUCCESS! HHV can be scraped!")
                    print(f"✅ No CAPTCHA, products and prices found")
                else:
                    print("\n⚠️  No obvious product links found")
                    # Show some links to debug
                    all_links = [l.get('href') for l in links[:10]]
                    print(f"Sample links: {all_links}")
                    
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_hhv())
