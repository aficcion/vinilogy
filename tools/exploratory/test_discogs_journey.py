import requests
import sqlite3
import json
import time

DB_PATH = "vinylbe.db"
BASE_URL = "http://localhost:5000/api"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def setup_test_data(user_id=888):
    print(f"Setting up test data for user {user_id}...")
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Ensure user exists (hacky)
    cur.execute("INSERT OR IGNORE INTO user (id, display_name) VALUES (?, 'Test User')", (user_id,))
    
    # 2. Insert Test Album (CD) - Daft Punk "Discovery"
    # release_id=12345, master_id=67890
    cur.execute("""
        INSERT OR REPLACE INTO user_collection_discogs 
        (user_id, release_id, master_id, artist, title, internal_category, release_type)
        VALUES (?, 12345, 67890, 'Daft Punk', 'Discovery', 'CD_FORMAT', 'release')
    """, (user_id,))
    
    conn.commit()
    conn.close()

def test_stats(user_id=888):
    print("\nTesting /collection/stats...")
    resp = requests.post(f"{BASE_URL}/collection/stats", json={"user_id": user_id, "username": "testuser"})
    if resp.status_code == 200:
        data = resp.json()
        print("Stats Response:", json.dumps(data, indent=2))
        artists = [a['name'] for a in data.get('top_artists', [])]
        if 'Daft Punk' in artists:
            print("PASS: Daft Punk found in stats")
        else:
            print("FAIL: Daft Punk NOT found in stats")
    else:
        print(f"FAIL: {resp.status_code} - {resp.text}")

def test_preferences(user_id=888):
    print("\nTesting /collection/preferences...")
    payload = {
        "user_id": user_id,
        "username": "testuser",
        "focus_artists": ["Daft Punk"],
        "strategies": ["upgrade"]
    }
    resp = requests.post(f"{BASE_URL}/collection/preferences", json=payload)
    if resp.status_code == 200:
        print("Preferences Response:", resp.json())
        print("PASS: Preferences saved")
    else:
        print(f"FAIL: {resp.status_code} - {resp.text}")

def test_generate(user_id=888):
    print("\nTesting /collection/generate...")
    payload = {
        "user_id": user_id,
        "username": "testuser",
        "focus_artists": ["Daft Punk"],
        "strategies": ["upgrade"]
    }
    # This might take time as it hits Discogs API
    resp = requests.post(f"{BASE_URL}/collection/generate", json=payload, timeout=60)
    if resp.status_code == 200:
        data = resp.json()
        print("Generate Response:", json.dumps(data, indent=2))
        
        recs = data.get('recommendations', [])
        found_upgrade = False
        for r in recs:
            if r['artist_name'] == 'Daft Punk' and r['album_name'] == 'Discovery':
                found_upgrade = True
                print("Found Upgrade Candidate:", r)
        
        if found_upgrade:
            print("PASS: Daft Punk upgrade generated")
        else:
            print("FAIL: Upgrade not generated")
            
    else:
        print(f"FAIL: {resp.status_code} - {resp.text}")

if __name__ == "__main__":
    setup_test_data()
    test_stats()
    test_preferences()
    test_generate() 
    print("\nTests Complete.")
