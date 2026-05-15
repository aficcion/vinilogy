#!/usr/bin/env python3
"""
Test Bora Bora scraping with OK Computer
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


async def test_bora_bora():
    """Test Bora Bora scraping"""
    
    client = PricingClient()
    await client.start()
    
    print("=" * 80)
    print("TESTING BORA BORA SCRAPING")
    print("=" * 80)
    
    artist = "Radiohead"
    album = "OK Computer"
    
    print(f"\n🎵 Testing: {artist} - {album}")
    print("-" * 80)
    
    try:
        # Test Bora Bora
        print(f"  📍 Bora Bora (two-step scraping)...")
        bora_bora_price = await client.scrape_bora_bora_price(artist, album)
        if bora_bora_price:
            print(f"     ✓ Price found: €{bora_bora_price:.2f}")
            if abs(bora_bora_price - 31.99) < 0.5:  # Allow small variance
                print(f"     ✅ CORRECT! Expected around €31.99")
            else:
                print(f"     ⚠️  Expected €31.99 but got €{bora_bora_price:.2f}")
        else:
            print(f"     ✗ No price found")
        
        # Test combined method with all three stores
        print(f"\n  📍 Testing all stores in parallel...")
        stores = await client.get_local_store_links_with_prices(artist, album)
        stores_with_prices = {k: v for k, v in stores.items() if v.get('price') is not None}
        print(f"     Found {len(stores_with_prices)} stores with prices:")
        for store_name, store_data in stores_with_prices.items():
            print(f"       - {store_name}: €{store_data['price']:.2f}")
        
    except Exception as e:
        print(f"     ❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    await client.stop()
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(test_bora_bora())
