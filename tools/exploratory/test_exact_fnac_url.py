"""
Test the exact FNAC product URL provided by user
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_exact_fnac_url():
    """Test the exact FNAC product URL"""
    
    print("=" * 70)
    print("Testing Exact FNAC Product URL")
    print("=" * 70)
    
    # Exact URL from user
    product_url = "https://www.fnac.es/a1367204/Radiohead-Ok-Computer-1997-2017-Vinilo-Disco"
    
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
    
    print(f"\n🔍 URL: {product_url}")
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
                
                if result.get("error"):
                    print(f"❌ Error: {result['error']}")
                    return
                
                data = result.get("data", {})
                
                print(f"\n📦 Product Data:")
                print(f"   Title: {data.get('title', 'N/A')}")
                print(f"   Price: {data.get('price', 'N/A')}")
                print(f"   Currency: {data.get('currency', 'N/A')}")
                print(f"   In Stock: {data.get('isInStock', 'N/A')}")
                print(f"   Brand: {data.get('brand', 'N/A')}")
                print(f"   Status Code: {data.get('statusCode', 'N/A')}")
                
                if data.get('price'):
                    print(f"\n🎉 SUCCESS! Price extracted: €{data['price']}")
                    print(f"✅ This product URL works perfectly with ScrapingBot Retail API!")
                else:
                    print(f"\n⚠️  No price found")
                    if data.get('statusCode') == 404:
                        print(f"   Product might not exist or URL is incorrect")
                    else:
                        print(f"   Full data: {data}")
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_exact_fnac_url())
