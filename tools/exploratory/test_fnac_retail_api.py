"""
Test ScrapingBot Retail API directly with a FNAC product URL
According to docs, FNAC is supported by the retail API
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_retail_api():
    """Test Retail API with a known FNAC product URL"""
    
    print("=" * 70)
    print("Testing ScrapingBot Retail API for FNAC")
    print("=" * 70)
    
    # Example FNAC product URL (you can replace with any FNAC product)
    # This is just a test URL - we'll need to find actual vinyl products
    test_url = "https://www.fnac.es/a8374569/Radiohead-OK-Computer-Vinilo"
    
    endpoint = "http://api.scraping-bot.io/scrape/retail"
    
    payload = {
        "url": test_url,
        "options": {
            "useChrome": False,
            "premiumProxy": True,  # Use premium for FNAC
            "proxyCountry": "ES",
            "waitForNetworkRequests": False
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print(f"\n🔍 Product URL: {test_url}")
    print(f"⭐ Premium Proxy: Yes")
    print(f"🔐 Auth: {USERNAME}:{API_KEY[:10]}...")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            print("\n⏳ Sending request to Retail API...")
            
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
                
                if result.get("error"):
                    print(f"❌ Error: {result['error']}")
                else:
                    print(f"✅ Success!")
                    
                    data = result.get("data", {})
                    print(f"\n📦 Product Data:")
                    print(f"   Title: {data.get('title', 'N/A')}")
                    print(f"   Price: {data.get('price', 'N/A')} {data.get('currency', '')}")
                    print(f"   In Stock: {data.get('isInStock', 'N/A')}")
                    print(f"   Brand: {data.get('brand', 'N/A')}")
                    print(f"   Description: {data.get('description', 'N/A')[:100]}...")
                    
                    if data.get('price'):
                        print(f"\n🎉 Successfully extracted price from FNAC!")
                    else:
                        print(f"\n⚠️  No price found in response")
                        print(f"Full data: {data}")
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"📄 Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("Note: If the product URL doesn't exist, try with a real FNAC product URL")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_retail_api())
