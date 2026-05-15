"""
Detailed test for ScrapingBot API - raw HTML endpoint
"""
import asyncio
import os
import httpx

# Set API key
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_scrapingbot_raw_html():
    """Test ScrapingBot raw HTML API directly"""
    
    print("=" * 70)
    print("Testing ScrapingBot Raw HTML API")
    print("=" * 70)
    
    # Test URL
    test_url = "https://www.fnac.es/SearchResult/ResultList.aspx?Search=Radiohead+OK+Computer+vinilo&sft=1&sa=0"
    
    print(f"\n🔍 Test URL: {test_url}")
    print(f"🔑 API Key: {API_KEY[:10]}...")
    
    # ScrapingBot endpoint
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
    
    auth = (API_KEY, API_KEY)
    
    print(f"\n📡 Endpoint: {endpoint}")
    print(f"📦 Payload: {payload}")
    
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
            print(f"📄 Response Headers: {dict(response.headers)}")
            
            if response.status_code == 200:
                result = response.json()
                print(f"\n📊 Response Keys: {list(result.keys())}")
                
                if "error" in result and result["error"]:
                    print(f"❌ Error: {result['error']}")
                else:
                    print(f"✅ No error in response")
                
                if "rawHtml" in result:
                    html_length = len(result["rawHtml"])
                    print(f"📝 HTML Length: {html_length} characters")
                    print(f"📝 HTML Preview (first 500 chars):")
                    print(result["rawHtml"][:500])
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
    asyncio.run(test_scrapingbot_raw_html())
