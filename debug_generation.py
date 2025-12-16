
import os
import sys
import asyncio
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

from services.recommender.artist_recommendations import get_artist_studio_albums, get_top_albums_from_discogs_search
from gateway import db_utils

# Load environment variables
load_dotenv()

async def debug_generation():
    print("--- DEBUGGING RECOMMENDATION GENERATION ---")
    
    # Get a real user ID
    conn = db_utils.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM user LIMIT 1")
    user = cur.fetchone()
    if not user:
        print("No user found in DB!")
        return
    user_id = user['id']
    print(f"User ID: {user_id}")
    
    # 1. Test Fetching User Collection Artists
    cur.execute("SELECT artist, internal_category FROM user_collection_discogs LIMIT 5")
    items = cur.fetchall()
    print(f"Sample Collection Items: {[ (i['artist'], i['internal_category']) for i in items ]}")
    
    artist_name = "The Black Keys" # FORCE TEST
    print(f"\n--- TESTING UPGRADE LOGIC FOR: {artist_name} ---")
    
    try:
        # Replicate UPGRADE call
        print("Calling get_artist_studio_albums(..., use_mb=False)")
        albums = get_artist_studio_albums(
            artist_name, 
            os.getenv("DISCOGS_KEY"), 
            os.getenv("DISCOGS_SECRET"), 
            top_n=5,
            use_mb=False 
        )
        print(f"Found {len(albums)} albums via Discogs-Only Search:")
        for alb in albums:
            print(f" - {alb.title} ({alb.year}) [ID: {alb.discogs_master_id}]")
            
        if not albums:
            print("❌ NO ALBUMS FOUND! Check filtering or API key.")
            
    except Exception as e:
        print(f"❌ ERROR in UPGRADE logic: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n--- TESTING COMPLETION LOGIC FOR: {artist_name} ---")
    try:
        # Replicate COMPLETION call
        print("Calling get_top_albums_from_discogs_search(...)")
        results = get_top_albums_from_discogs_search(
            artist_name,
            os.getenv("DISCOGS_KEY"),
            os.getenv("DISCOGS_SECRET"),
            limit=5
        )
        print(f"Found {len(results)} raw results from Discogs:")
        for res in results:
            print(f" - {res['title']} ({res.get('year')})")
            
    except Exception as e:
        print(f"❌ ERROR in COMPLETION logic: {e}")

if __name__ == "__main__":
    asyncio.run(debug_generation())
