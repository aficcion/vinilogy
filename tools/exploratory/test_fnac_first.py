"""
Test first FNAC URL (standard edition)
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_first_url():
    """Test the first FNAC URL"""
    
    product_url = "https://www.fnac.es/a1259205/Radiohead-OK-Computer-EdVinilo-Disco"
    
    print("=" * 70)
    print("Testing First FNAC URL (Standard Edition)")
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
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            print("\n⏳ Sending request...")
            
            response = await client.post(
                endpoint,
                json=payload,
                headers=headers,
                auth=auth
            )
            
            print(f"✅ Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("error"):
                    print(f"❌ Error: {result['error']}")
                else:
                    data = result.get("data", {})
                    
                    print(f"\n📦 Product:")
                    print(f"   Title: {data.get('title', 'N/A')}")
                    print(f"   Price: €{data.get('price', 'N/A')}")
                    print(f"   In Stock: {data.get('isInStock', 'N/A')}")
                    
                    if data.get('price'):
                        print(f"\n🎉 SUCCESS! This is the correct price for the standard edition")
            else:
                print(f"❌ HTTP {response.status_code}")
                print(response.text[:500])
                
    except Exception as e:
        print(f"❌ Error: {str(e)}")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_first_url())
