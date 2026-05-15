"""
Test Juno Records scraping with ScrapingBot
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_juno():
    """Test Juno Records search"""
    
    print("=" * 70)
    print("Testing Juno Records")
    print("=" * 70)
    
    # Juno search URL
    search_url = "https://es.juno.co.uk/search/?q%5Ball%5D%5B%5D=ok+computer+radiohead&solrorder=relevancy&hide_forthcoming=0"
    
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    
    # Try without premium first (cheaper)
    payload = {
        "url": search_url,
        "options": {
            "useChrome": False,
            "premiumProxy": False,
            "proxyCountry": "GB"  # UK proxy for Juno
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print(f"\n🔍 URL: {search_url}")
    print(f"🌍 Proxy: GB (United Kingdom)")
    
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
                
                # Check for CAPTCHA
                if "captcha" in html.lower():
                    print("❌ CAPTCHA detected")
                    return
                
                print(f"✅ Success! HTML Length: {len(html):,} characters")
                
                # Parse HTML
                soup = BeautifulSoup(html, 'lxml')
                
                # Look for product information
                # Juno uses specific classes for products
                products = soup.find_all(['div', 'article'], class_=lambda x: x and ('product' in x.lower() or 'item' in x.lower()))
                
                print(f"\n🔍 Found {len(products)} potential product containers")
                
                # Look for prices
                prices = soup.find_all(string=lambda text: text and '£' in text)
                print(f"💰 Found {len(prices)} price elements")
                
                if prices:
                    print(f"\n📌 Sample prices:")
                    for i, price in enumerate(prices[:5], 1):
                        print(f"   {i}. {price.strip()}")
                
                # Look for product links
                links = soup.find_all('a', href=True)
                product_links = [l.get('href') for l in links if '/products/' in l.get('href', '')]
                
                print(f"\n🔗 Found {len(product_links)} product links")
                
                if product_links:
                    print(f"\n📌 First 3 product links:")
                    for i, link in enumerate(product_links[:3], 1):
                        full_link = link if link.startswith('http') else f"https://es.juno.co.uk{link}"
                        print(f"   {i}. {full_link}")
                    
                    print(f"\n🎉 SUCCESS! Juno can be scraped!")
                    print(f"✅ No CAPTCHA, products found")
                else:
                    print("\n⚠️  No product links found, checking HTML structure...")
                    print(f"HTML sample (first 1000 chars):")
                    print(html[:1000])
                    
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_juno())
