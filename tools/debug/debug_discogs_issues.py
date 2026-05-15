import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import sqlite3

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
load_dotenv()

from services.recommender.artist_recommendations import _discogs_get, get_top_albums_from_discogs_search
from services.recommender.db_utils import get_db_connection

def inspect_elegante():
    key = os.getenv("DISCOGS_KEY")
    secret = os.getenv("DISCOGS_SECRET")
    
    print("--- Inspecting 'La Paloma' Search Results ---")
    # Broad search as implemented in the code
    data = _discogs_get("/database/search", {
        "artist": "La Paloma",
        "format": "Vinyl,LP,Album",
        "type": "release",
        "per_page": 100,
        "key": key,
        "secret": secret
    }, key, secret)
    
    results = data.get("results", [])
    found_elegante = False
    
    print(f"Found {len(results)} results. Checking for 'Elegante'...")
    
    for res in results:
        title = res.get("title", "")
        if "Elegante" in title:
            print(f"!!! FOUND ELEGANTE !!!")
            print(f"Title: {title}")
            print(f"Format: {res.get('format')}")
            print(f"ID: {res.get('id')}")
            print(f"Master ID: {res.get('master_id')}")
            print(f"Cover: {res.get('cover_image')}")
            found_elegante = True
            
    if not found_elegante:
        print("❌ 'Elegante' NOT found in top 100 results for 'La Paloma' (Vinyl, LP, Album)")

def check_image_validity(url):
    import requests
    print(f"\n--- Checking Image Validity: {url} ---")
    try:
        headers = {"User-Agent": "Vinylbe/1.0"}
        r = requests.head(url, headers=headers)
        print(f"Status Code: {r.status_code}")
        if r.status_code != 200:
            print("❌ Image is NOT accessible")
        else:
            print("✅ Image is accessible")
    except Exception as e:
        print(f"Error checking image: {e}")

if __name__ == "__main__":
    inspect_elegante()
    
    # Check one of the URLs from DB if available
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT cover_url FROM albums WHERE cover_url IS NOT NULL LIMIT 1")
    row = cur.fetchone()
    if row:
        check_image_validity(row['cover_url'])
