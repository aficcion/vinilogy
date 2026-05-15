#!/usr/bin/env python3
"""
Test improved scraping with OK Computer example
"""
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from services.pricing.pricing_client import PricingClient


async def test_ok_computer():
    """Test with OK Computer to verify correct matching"""
    
    client = PricingClient()
    await client.start()
    
    print("=" * 80)
    print("TESTING IMPROVED SCRAPER WITH OK COMPUTER")
    print("=" * 80)
    
    artist = "Radiohead"
    album = "OK Computer"
    
    print(f"\n🎵 Testing: {artist} - {album}")
    print("-" * 80)
    
    try:
        # Test Marilians
        print(f"  📍 Marilians...")
        marilians_price = await client.scrape_marilians_price(artist, album)
        if marilians_price:
            print(f"     ✓ Price found: €{marilians_price:.2f}")
        else:
            print(f"     ✗ No price found")
        
        # Test Bajo el Volcán
        print(f"  📍 Bajo el Volcán...")
        bajo_volcan_price = await client.scrape_bajo_el_volcan_price(artist, album)
        if bajo_volcan_price:
            print(f"     ✓ Price found: €{bajo_volcan_price:.2f}")
            if bajo_volcan_price == 29.80:
                print(f"     ✅ CORRECT! Matched the third result (29.80€)")
            else:
                print(f"     ⚠️  Expected 29.80€ but got €{bajo_volcan_price:.2f}")
        else:
            print(f"     ✗ No price found")
        
        # Test combined method
        print(f"  📍 Combined method...")
        stores = await client.get_local_store_links_with_prices(artist, album)
        stores_with_prices = {k: v for k, v in stores.items() if v.get('price') is not None}
        print(f"     Found {len(stores_with_prices)} stores with prices:")
        for store_name, store_data in stores_with_prices.items():
            print(f"       - {store_name}: €{store_data['price']:.2f}")
        
    except Exception as e:
        print(f"     ❌ Error: {str(e)}")
    
    await client.stop()
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_ok_computer())
