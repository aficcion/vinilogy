"""
Test ScrapingBot with Chrome enabled
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_with_chrome():
    """Test with Chrome rendering enabled"""
    
    print("=" * 70)
    print("Testing ScrapingBot with Chrome Rendering")
    print("=" * 70)
    
    test_url = "https://www.fnac.es/SearchResult/ResultList.aspx?Search=Radiohead+OK+Computer+vinilo&sft=1&sa=0"
    
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    
    payload = {
        "url": test_url,
        "options": {
            "useChrome": True,  # Enable Chrome
            "premiumProxy": False,
            "proxyCountry": "ES"
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print(f"\n🔍 URL: {test_url}")
    print(f"🌐 Using Chrome: Yes")
    print(f"🔐 Auth: {USERNAME}:{API_KEY[:10]}...")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:  # Longer timeout for Chrome
            print("\n⏳ Sending request (this may take longer with Chrome)...")
            
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
                else:
                    print(f"✅ Success!")
                    
                    if "rawHtml" in result:
                        html_length = len(result["rawHtml"])
                        print(f"📝 HTML Length: {html_length:,} characters")
                        
                        if html_length > 1000:
                            from bs4 import BeautifulSoup
                            soup = BeautifulSoup(result["rawHtml"], 'lxml')
                            
                            # Look for product links
                            all_links = soup.find_all('a', href=True)
                            product_links = []
                            for link in all_links:
                                href = link.get('href', '')
                                if '/a' in href or '/mp' in href:
                                    if href.startswith('/'):
                                        href = f"https://www.fnac.es{href}"
                                    product_links.append(href)
                            
                            print(f"🔗 Found {len(product_links)} product links")
                            if product_links:
                                print(f"\n📌 First 3 product links:")
                                for i, link in enumerate(product_links[:3], 1):
                                    print(f"   {i}. {link[:80]}...")
                            else:
                                print("⚠️  No product links found")
                                # Show some of the HTML to debug
                                print(f"\n📄 HTML sample:")
                                print(result["rawHtml"][:1000])
                        else:
                            print(f"⚠️  HTML too short")
                            print(result["rawHtml"])
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"📄 Response: {response.text}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_with_chrome())
