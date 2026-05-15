"""
Test specific FNAC URL with ScrapingBot Retail API
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_specific_url():
    """Test the specific FNAC URL"""
    
    product_url = "https://www.fnac.es/a101621/Radiohead-OK-Computer-Vinilo-Disco"
    
    print("=" * 70)
    print("Testing Specific FNAC URL with ScrapingBot Retail API")
    print("=" * 70)
    print(f"\n🔍 URL: {product_url}")
    
    endpoint = "http://api.scraping-bot.io/scrape/retail"
    
    payload = {
        "url": product_url,
        "options": {
            "useChrome": False,
            "premiumProxy": True,
            "proxyCountry": "ES",
            "waitForNetworkRequests": False
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print(f"🔐 Auth: {USERNAME}:{API_KEY[:10]}...")
    print(f"⭐ Premium Proxy: Yes")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            print("\n⏳ Sending request to ScrapingBot Retail API...")
            
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
                    print(f"❌ ScrapingBot Error: {result['error']}")
                else:
                    data = result.get("data", {})
                    
                    print(f"\n📦 Product Data:")
                    print(f"   Title: {data.get('title', 'N/A')}")
                    print(f"   Price: {data.get('price', 'N/A')}")
                    print(f"   Currency: {data.get('currency', 'N/A')}")
                    print(f"   In Stock: {data.get('isInStock', 'N/A')}")
                    print(f"   Status Code: {data.get('statusCode', 'N/A')}")
                    
                    if data.get('price'):
                        print(f"\n🎉 SUCCESS! Price: €{data['price']}")
                    else:
                        print(f"\n⚠️  No price found")
                        print(f"Full data: {data}")
            else:
                print(f"❌ HTTP Error: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_specific_url())
