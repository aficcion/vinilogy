import asyncio
import os
import httpx
# Set dummy env vars to pass __init__ check
os.environ["EBAY_CLIENT_ID"] = "dummy"
os.environ["EBAY_CLIENT_SECRET"] = "dummy"

from services.pricing.pricing_client import PricingClient

async def version_check():
    print("Initializing PricingClient for testing...")
    try:
        client = PricingClient()
        # Manually init http_client to bypass eBay auth in start()
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        client.http_client = httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True)
        
        print("\n--- Testing: Arcade Fire - WE ---")
        result = await client.scrape_bajo_el_volcan_price("Arcade Fire", "WE")
        
        if result:
            print("✅ Match Found:")
            print(f"  Price: {result.get('price')}")
            print(f"  URL: {result.get('url')}")
            print(f"  Availability: {result.get('availability')}")
            
            # Verifications
            if "bajoelvolcan.es/vinilo" in result.get('url', ''):
                print("  ✅ URL looks correct (product page)")
            else:
                print("  ❌ URL does not look like a product page")
                
            if result.get('availability') == "Consultar disponibilidad":
                print("  ✅ Availability correctly detected")
            else:
                print(f"  ⚠️ Availability: {result.get('availability')} (Expected 'Consultar disponibilidad' based on previous run)")
                
        else:
            print("❌ No match found for Arcade Fire - WE")

        print("\n--- Testing: Arctic Monkeys - AM (Control Case) ---")
        result_am = await client.scrape_bajo_el_volcan_price("Arctic Monkeys", "AM")
        if result_am:
             print("✅ Match Found for AM:")
             print(f"  Price: {result_am.get('price')}")
             
        await client.stop()

    except Exception as e:
        print(f"Test Failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(version_check())
