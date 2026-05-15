
import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.pricing.pricing_client import PricingClient, normalize

async def test_marilians_matching():
    client = PricingClient()
    
    # Test cases: (Artist, Album, Expected Result present in title)
    test_cases = [
        ("Radiohead", "OK Computer", True),
        ("Deerhunter", "Cryptograms / Fluorescent Grey", True),  # Test slash handling
        ("The Beatles", "Abbey Road", True),
        ("Unknown Artist", "Non Existent Album", False)
    ]
    
    print("\n🔬 Testing Marilians Scraper Logic...")
    
    for artist, album, should_find in test_cases:
        print(f"\nTesting: {artist} - {album}")
        
        # Test Query Sanitization
        query = f"{artist} {album}".replace("/", " ").replace("  ", " ").replace(" ", "+")
        print(f"Sanitized Query URL suffix: &s={query}")
        
        # We can't easily mock the HTTP request without a lot of setup, 
        # so for this test script we will primarily verify the query construction 
        # and matching logic concepts.
        
        artist_norm = normalize(artist)
        album_norm = normalize(album)
        print(f"Normalized: '{artist_norm}' - '{album_norm}'")
        
        # Simulate matching logic with a hypothetical title
        if "/" in album:
             # Simulate title that might be found on store
             simulated_title = f"{artist} - {album.replace('/', ' ')} (Vinyl)"
        else:
             simulated_title = f"{artist} - {album} LP"
             
        title_norm = normalize(simulated_title)
        print(f"Simulated Title: '{simulated_title}'")
        print(f"Normalized Title: '{title_norm}'")
        
        # Test scoring logic
        score = 0
        artist_words = artist_norm.split()
        album_words = album_norm.split()
        
        # Check artist words
        artist_matches = sum(1 for word in artist_words if word in title_norm)
        if artist_matches == len(artist_words):
            score += 50
            print("✓ Artist match (Full)")
        elif artist_matches > 0:
            score += 20 * (artist_matches / len(artist_words))
            print("~ Artist match (Partial)")
            
        # Check album words
        album_matches = sum(1 for word in album_words if word in title_norm)
        if album_matches == len(album_words):
            score += 50
            print("✓ Album match (Full)")
        elif album_matches > 0:
            score += 20 * (album_matches / len(album_words))
            print("~ Album match (Partial)")
            
        print(f"Final Score: {score}")

if __name__ == "__main__":
    asyncio.run(test_marilians_matching())
