import sys
import os
import json
from datetime import datetime

# Add gateway to path
sys.path.insert(0, os.path.abspath("."))

from gateway import db
import requests

user_id = 11
artist_names = ["Foals", "Ornamento Y Delito", "Idles", "Praful", "Green Day"]

print(f"Fetching manual artist recommendations for {len(artist_names)} artists...")
try:
    resp = requests.post("http://127.0.0.1:5000/api/recommendations/artists", json={
        "artist_names": artist_names
    })
    resp.raise_for_status()
    data = resp.json()
    manual_recs = data.get("recommendations", [])
    print(f"Got {len(manual_recs)} manual recommendations.")
    print(f"Sample rec: {json.dumps(manual_recs[0] if manual_recs else {}, indent=2)}")
    
    # Format them like app-user.js does
    formatted_recs = []
    for rec in manual_recs:
        if rec.get('source') == 'artist_based':
            formatted_recs.append({
                'album_name': rec.get('album_name'),
                'artist_name': rec.get('artist_name'),
                'image_url': rec.get('image_url'),
                'discogs_master_id': rec.get('discogs_master_id'),
                'rating': rec.get('rating'),
                'votes': rec.get('votes'),
                'year': rec.get('year'),
                'source': 'manual'  # Changed from 'artist_based' to match DB constraint
            })
        else:
            formatted_recs.append(rec)
    
    print(f"Formatted {len(formatted_recs)} recommendations.")
    print(f"Sample formatted: {json.dumps(formatted_recs[0] if formatted_recs else {}, indent=2)}")
    
    # Now try to save
    print(f"\nCalling regenerate_recommendations for user {user_id}...")
    db.regenerate_recommendations(user_id, formatted_recs)
    print("Success!")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
