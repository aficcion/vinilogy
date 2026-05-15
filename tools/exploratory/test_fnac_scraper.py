"""
Test script for FNAC scraper using ScrapingBot Retail API.
"""
import asyncio
import sys
import os

# Set environment variable directly for testing
os.environ['SCRAPINGBOT_API_KEY'] = '4bdzoKp01ykZUwBpFU4OVQIJ8'

# Load other environment variables
from dotenv import load_dotenv
load_dotenv()

# Add parent directory to path to import services
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.pricing.pricing_client import PricingClient


async def test_fnac_retail_api():
    """Test FNAC scraper with ScrapingBot Retail API."""
    
    client = PricingClient()
    await client.start()
    
    print("=" * 70)
    print("Testing FNAC Scraper with ScrapingBot Retail API")
    print("=" * 70)
    
    # Test with a popular album
    artist = "Radiohead"
    album = "OK Computer"
    
    print(f"\n🎵 Testing: {artist} - {album}")
    print("-" * 70)
    
    try:
        price = await client.scrape_fnac_price(artist, album)
        
        if price:
            print(f"✅ Found price: €{price:.2f}")
        else:
            print("⚠️  No price found")
            print("   This could mean:")
            print("   - Album not available on FNAC")
            print("   - No product links found in search results")
            print("   - ScrapingBot API issue")
            
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)
    print("Check svc_pricing.log for detailed logs")
    print("=" * 70)
    
    await client.stop()


if __name__ == "__main__":
    asyncio.run(test_fnac_retail_api())
