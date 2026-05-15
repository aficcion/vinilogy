
import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from services.pricing.pricing_client import PricingClient
from dotenv import load_dotenv

load_dotenv()

async def test_lazy_logic():
    print("Testing Lazy Loading Logic in PricingClient...")
    
    # Initialize client
    client = PricingClient()
    await client.start()
    
    artist = "Radiohead"
    album = "In Rainbows"
    
    print(f"\n--- Test 1: Exclude FNAC (Standard Load) ---")
    print("Expected: Marilians, Bajo el Volcán, Bora Bora, Revolver. NO FNAC.")
    results_no_fnac = await client.get_local_store_links_with_prices(
        artist, album, exclude_fnac=True
    )
    print("Results keys:", list(results_no_fnac.keys()))
    if "fnac" in results_no_fnac:
        print("❌ FAILED: FNAC present when excluded")
    else:
        print("✅ PASSED: FNAC correctly excluded")
        
    print(f"\n--- Test 2: Only FNAC (Lazy Load) ---")
    print("Expected: ONLY FNAC (or empty if failed). NO other stores.")
    results_only_fnac = await client.get_local_store_links_with_prices(
        artist, album, only_fnac=True
    )
    print("Results keys:", list(results_only_fnac.keys()))
    
    # Check if other stores are present
    forbidden = ["marilians", "bajo_el_volcan", "bora_bora", "revolver"]
    found_forbidden = [k for k in results_only_fnac.keys() if k in forbidden]
    
    if found_forbidden:
         print(f"❌ FAILED: Found non-FNAC stores: {found_forbidden}")
    else:
        print("✅ PASSED: Only FNAC (or nothing) returned")
        
    if "fnac" in results_only_fnac:
        print(f"FNAC Price found: {results_only_fnac['fnac']['price']} EUR")
        print(f"FNAC URL: {results_only_fnac['fnac']['url']}")
    else:
        print("⚠️ FNAC not found (could be 502 or timeout, but logic passed if no other stores)")

if __name__ == "__main__":
    asyncio.run(test_lazy_logic())
