"""
Test ScrapingBot with correct credentials
"""
import asyncio
import os
import httpx

# Correct credentials
USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_scrapingbot_with_correct_auth():
    """Test ScrapingBot with username:apiKey authentication"""
    
    print("=" * 70)
    print("Testing ScrapingBot with Correct Credentials")
    print("=" * 70)
    
    test_url = "https://www.fnac.es/SearchResult/ResultList.aspx?Search=Radiohead+OK+Computer+vinilo&sft=1&sa=0"
    
    print(f"\n🔍 Test URL: {test_url}")
    print(f"👤 Username: {USERNAME}")
    print(f"🔑 API Key: {API_KEY[:10]}...")
    
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    
    payload = {
        "url": test_url,
        "options": {
            "useChrome": False,
            "premiumProxy": False,
            "proxyCountry": "ES"
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    # Correct authentication format
    auth = (USERNAME, API_KEY)
    
    print(f"\n📡 Endpoint: {endpoint}")
    print(f"🔐 Auth: {USERNAME}:{API_KEY[:10]}...")
    
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
                print(f"📊 Response Keys: {list(result.keys())}")
                
                if "error" in result and result["error"]:
                    print(f"❌ Error: {result['error']}")
                else:
                    print(f"✅ No error in response")
                
                if "rawHtml" in result:
                    html_length = len(result["rawHtml"])
                    print(f"📝 HTML Length: {html_length} characters")
                    
                    # Check if we got actual content
                    if html_length > 1000:
                        print(f"✅ Successfully fetched FNAC search page!")
                        
                        # Look for product links
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(result["rawHtml"], 'lxml')
                        links = soup.find_all('a', href=True)
                        product_links = [l.get('href') for l in links if '/a' in l.get('href', '') or '/mp' in l.get('href', '')]
                        print(f"🔗 Found {len(product_links)} potential product links")
                        if product_links:
                            print(f"📌 First product link: {product_links[0][:100]}...")
                    else:
                        print(f"⚠️  HTML seems too short, might be an error page")
                        print(f"📝 HTML Preview: {result['rawHtml'][:500]}")
                else:
                    print("❌ No 'rawHtml' key in response")
                    print(f"📊 Full response: {result}")
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"📄 Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_scrapingbot_with_correct_auth())
