#!/usr/bin/env python3
"""
Test script to verify web scraping functionality for Marilians and Bajo el Volcán
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


async def test_scraping():
    """Test scraping for both stores"""
    
    # Test albums
    test_cases = [
        ("Radiohead", "Pablo Honey"),
        ("The Beatles", "Abbey Road"),
        ("Pink Floyd", "The Dark Side of the Moon"),
    ]
    
    client = PricingClient()
    await client.start()
    
    print("=" * 80)
    print("TESTING WEB SCRAPING FOR VINYL PRICES")
    print("=" * 80)
    
    for artist, album in test_cases:
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
    asyncio.run(test_scraping())
