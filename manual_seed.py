
import os
import sys
import asyncio
from dotenv import load_dotenv

# Add project root
sys.path.append(os.getcwd())

from services.recommender.artist_recommendations import get_artist_studio_albums
from gateway import db_utils

load_dotenv()

def seed_artist():
    artist_name = "The Black Keys"
    print(f"🚀 Seeding '{artist_name}' as if from CSV (Full MB Scan)...")
    
    try:
        # csv_mode=True usually implies stricter checking or logging, but use_mb=True is the key for "Heavy" load.
        # We use use_mb=True to fetch from MusicBrainz and cache deep data.
        albums = get_artist_studio_albums(
            artist_name,
            os.getenv("DISCOGS_KEY"),
            os.getenv("DISCOGS_SECRET"),
            top_n=100,
            csv_mode=True, 
            use_mb=True # FORCE MB Check for quality data
        )
        
        print(f"✅ Success! Fetched and cached {len(albums)} albums.")
        for alb in albums[:10]:
            print(f" - {alb.title} ({alb.year})")
            
        print("Data is now in the 'albums' table in SQLite.")
        
    except Exception as e:
        print(f"❌ Error seeding: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    seed_artist()
