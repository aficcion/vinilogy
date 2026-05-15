import sys
import os
import json
from datetime import datetime

# Add gateway to path
sys.path.insert(0, os.path.abspath("."))

from gateway import db

import requests

user_id = 11
username = "aficcion"

print(f"Fetching Last.fm recommendations for {username}...")
try:
    resp = requests.post("http://127.0.0.1:5000/api/lastfm/recommendations", json={
        "username": username,
        "time_range": "medium_term"
    })
    resp.raise_for_status()
    data = resp.json()
    new_recs = data.get("albums", [])
    print(f"Got {len(new_recs)} recommendations.")
    
    # Simulate what app-user.js does (it might add manual recs too, but let's test this first)
    print(f"Calling regenerate_recommendations for user {user_id}...")
    db.regenerate_recommendations(user_id, new_recs)
    print("Success!")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
