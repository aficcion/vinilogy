import os
import requests
import time
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load env variables from .env file
load_dotenv()

# Get credentials
DISCOGS_KEY = os.environ.get("DISCOGS_KEY")
DISCOGS_SECRET = os.environ.get("DISCOGS_SECRET")

def _discogs_get(endpoint: str, params: Dict[str, Any], key: str, secret: str, sleep_after_ok: float = 1.0) -> Dict[str, Any]:
    url = f"https://api.discogs.com{endpoint}"
    headers = {
        "User-Agent": "VinylbeApp/1.0",
        "Authorization": f"Discogs key={key}, secret={secret}"
    }
    print(f"GET {url} {params}")
    resp = requests.get(url, params=params, headers=headers)
    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text}")
        return {}
    time.sleep(sleep_after_ok)
    return resp.json()

def get_top_albums_debug(artist_name: str):
    print(f"\n--- Searching for: {artist_name} ---")
    
    # REPLICATED LOGIC FROM artist_recommendations.py
    data = _discogs_get("/database/search", {
        "artist": artist_name,
        "format": "Vinyl,LP,Album",
        "type": "release",
        "per_page": 50
    }, DISCOGS_KEY, DISCOGS_SECRET)
    
    results = data.get("results", [])
    print(f"Raw Results Count: {len(results)}")
    
    filtered_albums = []
    seen_titles = set()
    exclude_keywords = ["live", "compilation", "anthology", "best of", "greatest hits", "deluxe", "promo", "single", "ep", "directo"]

    for res in results:
        title_full = res.get("title", "")
        print(f"Checking: {title_full}")
        
        album_title = title_full
        # Original logic: blindly split if ' - ' exists
        if " - " in title_full:
             parts = title_full.split(" - ", 1)
             album_title = parts[1]
        
        # KEYWORD FILTER
        is_excluded = False
        lower_title = album_title.lower()
        if any(ex in lower_title for ex in exclude_keywords):
            print(f"  -> EXCLUDED (Keyword): {album_title}")
            is_excluded = True
        
        # FORMAT FILTER (Implicit in search, but maybe verify 'format' list in response?)
        formats = res.get("format", [])
        
        if not is_excluded:
             if album_title.lower() in seen_titles:
                 print(f"  -> SKIPPED (Duplicate): {album_title}")
                 continue
             
             print(f"  -> ACCEPTED: {album_title}")
             seen_titles.add(album_title.lower())
             filtered_albums.append(res)
             
    print(f"Total Accepted: {len(filtered_albums)}")
    return filtered_albums

if __name__ == "__main__":
    if DISCOGS_KEY == "MustSetKey":
        print("Please set DISCOGS_KEY and DISCOGS_SECRET env vars")
    else:
        # Test problematic artists
        get_top_albums_debug("Black Rebel Motorcycle Club")
        get_top_albums_debug("The Black Keys")
