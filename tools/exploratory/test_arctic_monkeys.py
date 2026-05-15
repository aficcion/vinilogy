"""
Test Arctic Monkeys - Humbug on FNAC
"""
import asyncio
import os
import sys

# Add services directory to path
sys.path.append(os.getcwd())

from services.pricing.pricing_client import PricingClient

async def test_arctic_monkeys():
    print("=" * 70)
    print("Testing Arctic Monkeys - Humbug")
    print("=" * 70)
    
    # Needs env vars
    from dotenv import load_dotenv
    load_dotenv()
    
    client = PricingClient()
    print("\n🔍 Initializing client...")
    await client.start()
    
    try:
        print("\n🔍 Running scrape_fnac_price...")
        result = await client.scrape_fnac_price("Arctic Monkeys", "Humbug")
        
        if result:
            price, url = result
            print(f"\n✅ SUCCESS!")
            print(f"Price: €{price}")
            print(f"URL: {url}")
        else:
            print("\n❌ FAILED: No results found or error occurred")
            
    finally:
        await client.stop()

if __name__ == "__main__":
    asyncio.run(test_arctic_monkeys())
