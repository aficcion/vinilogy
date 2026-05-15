import requests
import json

BASE_URL = "http://localhost:5000"

def test_repion_album():
    print("🧪 Testing Repion Album Details...")
    
    # 1. Create a guest user
    print("\n1. Creating guest user...")
    guest_resp = requests.post(f"{BASE_URL}/auth/guest")
    user_id = guest_resp.json()['user_id']
    print(f"✅ User created: {user_id}")

    # 2. Add the specific album
    print("\n2. Adding 'Entre Todas Lo Arreglamos' by 'Repion'...")
    album_payload = {
        "title": "Entre Todas Lo Arreglamos",
        "artist_name": "Repion",
        "cover_url": "http://example.com/cover.jpg",
        "discogs_id": None
    }
    add_resp = requests.post(f"{BASE_URL}/api/users/{user_id}/albums", json=album_payload)
    if add_resp.status_code != 200:
        print(f"❌ Failed to add album: {add_resp.text}")
        return
    print("✅ Album added")

    # 3. Fetch recommendations to see how it looks
    print("\n3. Fetching recommendations...")
    recs_resp = requests.get(f"{BASE_URL}/api/users/{user_id}/recommendations")
    recs = recs_resp.json()
    
    target_rec = next((r for r in recs if r['artist_name'] == 'Repion'), None)
    
    if target_rec:
        print("✅ Found album in recommendations:")
        print(json.dumps(target_rec, indent=2))
        
        # Check for album_name vs album_title
        if 'album_name' not in target_rec and 'album_title' not in target_rec:
            print("❌ MISSING album name/title field!")
        
        if 'artist_name' not in target_rec:
            print("❌ MISSING artist_name field!")
            
    else:
        print("❌ Album not found in recommendations")

    # 4. Test Pricing Endpoint directly
    print("\n4. Testing Pricing Endpoint for 'Unknown Artist' / 'Unknown Album'...")
    pricing_resp = requests.get(f"{BASE_URL}/album-pricing/Unknown%20Artist/Unknown%20Album")
    if pricing_resp.status_code == 200:
        print("✅ Pricing data received:")
        data = pricing_resp.json()
        print(f"Title: {data.get('title')}")
        print(f"Artist: {data.get('artist')}")
        print("Tracklist sample:", data.get('tracklist', [])[:3])
        print("Full Tracklist:", json.dumps(data.get('tracklist'), indent=2))
    else:
        print(f"❌ Pricing fetch failed: {pricing_resp.status_code}")

if __name__ == "__main__":
    test_repion_album()
