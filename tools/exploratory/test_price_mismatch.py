
import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

async def test_specific_url():
    url = "https://www.fnac.es/a920787/Arctic-Monkeys-AM-Vinilo-Descarga-MP3-Disco"
    api_key = os.getenv("SCRAPINGBOT_API_KEY")
    
    if not api_key:
        print("Error: SCRAPINGBOT_API_KEY not found")
        return

    print(f"Testing URL: {url}")
    
    retail_url = "http://api.scraping-bot.io/scrape/retail"
    auth = ("Vinilogy", api_key)
    
    payload = {
        "url": url,
        "options": {
            "useChrome": True,
            "premiumProxy": True,
            "proxyCountry": "ES",
            "waitForNetworkRequests": True
        }
    }
    
    headers = {"Content-Type": "application/json"}
    
    async with httpx.AsyncClient() as client:
        print("Sending request to ScrapingBot...")
        response = await client.post(
            retail_url,
            json=payload,
            headers=headers,
            auth=auth,
            timeout=60.0
        )
        
        data = response.json()
        print("\n--- API Response ---")
        if data.get("data"):
            d = data["data"]
            print(f"Title: {d.get('title')}")
            print(f"Price: {d.get('price')}")
            print(f"Currency: {d.get('currency')}")
            print(f"Shipping: {d.get('shippingPrice')}")
            print(f"Seller: {d.get('site')}")
            print(f"Full Data: {d}")
        else:
            print(f"Error/No Data: {data}")

if __name__ == "__main__":
    asyncio.run(test_specific_url())
