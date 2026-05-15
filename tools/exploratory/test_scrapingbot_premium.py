"""
Test ScrapingBot with Premium Proxy (required for FNAC)
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_with_premium_proxy():
    """Test with Premium Proxy enabled (required for FNAC)"""
    
    print("=" * 70)
    print("Testing ScrapingBot with Premium Proxy for FNAC")
    print("=" * 70)
    
    test_url = "https://www.fnac.es/SearchResult/ResultList.aspx?Search=Radiohead+OK+Computer+vinilo&sft=1&sa=0"
    
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    
    payload = {
        "url": test_url,
        "options": {
            "useChrome": True,
            "premiumProxy": True,  # Required for FNAC
            "proxyCountry": "ES"
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print(f"\n🔍 URL: {test_url}")
    print(f"🌐 Chrome: Yes")
    print(f"⭐ Premium Proxy: Yes (required for FNAC)")
    print(f"🔐 Auth: {USERNAME}:{API_KEY[:10]}...")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            print("\n⏳ Sending request (premium proxy may take longer)...")
            
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
                    print(f"✅ Success! Bypassed FNAC protection")
                    
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
                                    
                                print(f"\n🎯 Will use first link for retail API test")
                            else:
                                print("⚠️  No product links found")
                                print(f"\n📄 HTML sample (first 1000 chars):")
                                print(result["rawHtml"][:1000])
                        else:
                            print(f"⚠️  HTML too short")
                            print(result["rawHtml"])
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"📄 Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_with_premium_proxy())
