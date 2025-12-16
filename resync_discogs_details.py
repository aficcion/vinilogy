#!/usr/bin/env python3
import sys
import os
import requests
import re
from typing import List, Dict, Any

# Ensure we can import from gateway
sys.path.append(os.getcwd())
import gateway.db as db

def resync(user_id: int):
    """
    Fetch all items from Discogs API and sync them to DB with new fields.
    """
    
    # Needs a Discogs Cache or Token.
    # For user 'aficcion', we need their username. 
    discogs_username = "aficcion" # Hardcoded for this user
    
    # Ideally use token from env
    token = os.getenv("DISCOGS_KEY", "aWZbvONUDQtNKhHEQDAVxSHePAEeLSfFhJILcmvt")
    headers = {"Authorization": f"Discogs token={token}", "User-Agent": "Vinylbe/1.0"}
    
    print(f"Fetching collection for user: {discogs_username}")
    
    url = f"https://api.discogs.com/users/{discogs_username}/collection/folders/0/releases"
    items = []
    page = 1
    
    while True:
        print(f"Fetching page {page}...")
        resp = requests.get(url, params={"page": page, "per_page": 50}, headers=headers)
        if resp.status_code != 200:
            print(f"Error fetching page {page}: {resp.status_code} {resp.text}")
            break
            
        data = resp.json()
        releases = data.get("releases", [])
        if not releases:
            break
            
        for rel in releases:
            basic = rel.get("basic_information", {})
            
            # 1. Format String (Existing logic)
            fmt_str = "OTHERS"
            formats = basic.get("formats", [])
            fmt_descriptions = []
            
            if formats:
                f_name = formats[0].get("name", "").upper()
                fmt_descriptions = formats[0].get("descriptions", [])
                
                if "Candy" in basic.get("title", ""):
                    print(f"DEBUG: Title={basic.get('title')} f_name='{f_name}' descriptions={fmt_descriptions}")

                if "VINYL" in f_name or "LP" in f_name or "7\"" in f_name:
                    fmt_str = "VINYL"
                elif "CD" in f_name:
                    fmt_str = "CD_FORMAT"
                elif "CASSETTE" in f_name:
                    fmt_str = "TAPE_FORMAT"
                
                # Debug OTHERS
                # Global counter needed or just print a few
                if fmt_str == "OTHERS" and len(items) < 20: 
                    print(f"DEBUG OTHERS: Title='{basic.get('title')}' f_name='{f_name}' descs={fmt_descriptions}")

            # 2. Release Type (New Logic - User Requests 2025-12-08)
            release_type = "Other"
            
            # Helper to check case-insensitive presence in descriptions
            desc_upper = [d.upper() for d in fmt_descriptions]
            
            if 'COMPILATION' in desc_upper:
                release_type = "Compilation"
            elif any(d in desc_upper for d in ['ALBUM', 'LP', 'MINI-ALBUM']):
                release_type = "Album"
            elif 'EP' in desc_upper:
                release_type = "EP"
            elif any(d in desc_upper for d in ['SINGLE', 'MAXI-SINGLE', '7"', '12"', '10"']):
                release_type = "Single"

            # 3. Label & Year
            labels = basic.get("labels", [])
            label = labels[0].get("name") if labels else None
            year = basic.get("year", 0)

            items.append({
                "release_id": rel.get("id"),
                "master_id": basic.get("master_id"),
                "title": basic.get("title"),
                "artist": re.sub(r' \(\d+\)$', '', basic.get("artists", [{}])[0].get("name", "")),
                "internal_category": fmt_str,
                "cover_url": basic.get("thumb") or basic.get("cover_image"),
                "release_type": release_type,
                "year": year,
                "label": label
            })
            
        pagination = data.get("pagination", {})
        if page >= pagination.get("pages", 1):
            break
        page += 1
        
    print(f"Syncing {len(items)} items to database...")
    db.sync_discogs_collection_items(user_id, items)
    print("Done!")

if __name__ == "__main__":
    resync(2) # user_id 2 (aficcion)
