"""
Test complete FNAC scraper (Google Search + ScrapingBot Retail API)
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from services.pricing.pricing_client import PricingClient


async def test_fnac_complete():
    """Test complete FNAC scraper"""
    
    client = PricingClient()
    await client.start()
    
    print("=" * 70)
    print("Testing Complete FNAC Scraper")
    print("=" * 70)
    
    # Test albums
    test_cases = [
        ("Radiohead", "OK Computer"),
        ("Pink Floyd", "The Dark Side of the Moon"),
        ("Deerhunter", "Microcastle")
    ]
    
    for artist, album in test_cases:
        print(f"\n🎵 Testing: {artist} - {album}")
        print("-" * 70)
        
        try:
            price = await client.scrape_fnac_price(artist, album)
            
            if price:
                print(f"✅ Found price: €{price:.2f}")
            else:
                print(f"⚠️  No price found (album might not be on FNAC)")
                
        except Exception as e:
            print(f"❌ Error: {str(e)}")
    
    print("\n" + "=" * 70)
    print("Check svc_pricing.log for detailed logs")
    print("=" * 70)
    
    await client.stop()


if __name__ == "__main__":
    asyncio.run(test_fnac_complete())
