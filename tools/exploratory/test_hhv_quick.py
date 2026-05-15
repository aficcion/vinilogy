"""
Test HHV - check what response we get
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_hhv_response():
    """Check HHV response"""
    
    search_url = "https://www.hhv.de/en-ES/catalog/filter/search-S11?af=true&term=OK%20computer%20radiohead"
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    
    payload = {
        "url": search_url,
        "options": {
            "useChrome": False,
            "premiumProxy": False,
            "proxyCountry": "DE"
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print("Testing HHV response format...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            endpoint,
            json=payload,
            headers=headers,
            auth=auth
        )
        
        print(f"Status: {response.status_code}")
        print(f"Content-Type: {response.headers.get('content-type')}")
        print(f"Response length: {len(response.text)}")
        print(f"\nFirst 1000 chars of response:")
        print(response.text[:1000])

if __name__ == "__main__":
    asyncio.run(test_hhv_response())
