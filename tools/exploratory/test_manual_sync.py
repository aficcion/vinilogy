import requests
import json

# URL base
BASE_URL = "http://localhost:5000"

def test_manual_album_sync():
    print("🧪 Testing Manual Album Sync...")
    
    # 1. Create a dummy guest user to simulate the source
    print("\n1. Creating dummy guest user...")
    guest_resp = requests.post(f"{BASE_URL}/auth/guest")
    if guest_resp.status_code != 200:
        print(f"❌ Failed to create guest: {guest_resp.text}")
        return
    
    guest_data = guest_resp.json()
    guest_id = guest_data['user_id']
    print(f"✅ Guest created: ID {guest_id}")

    # 2. Add a manual album to this guest (to verify we can fetch it like frontend does)
    print("\n2. Adding manual album to guest...")
    album_payload = {
        "title": "Test Manual Album",
        "artist_name": "Test Artist",
        "cover_url": "http://example.com/cover.jpg",
        "discogs_id": 12345
    }
    add_resp = requests.post(f"{BASE_URL}/api/users/{guest_id}/albums", json=album_payload)
    if add_resp.status_code != 200:
        print(f"❌ Failed to add album: {add_resp.text}")
        return
    print("✅ Manual album added to guest")

    # 3. Fetch recommendations to confirm it's there (simulating frontend check)
    print("\n3. Fetching guest recommendations...")
    recs_resp = requests.get(f"{BASE_URL}/api/users/{guest_id}/recommendations")
    recs = recs_resp.json()
    manual_recs = [r for r in recs if r.get('source') == 'manual']
    print(f"✅ Found {len(manual_recs)} manual albums for guest")
    
    if not manual_recs:
        print("❌ No manual albums found, aborting")
        return

    # 4. Simulate Last.fm login with this manual album in payload
    print("\n4. Simulating Last.fm login with manual albums payload...")
    
    # We'll use a fake lastfm username
    lastfm_user = f"test_user_{guest_id}"
    
    login_payload = {
        "lastfm_username": lastfm_user,
        "manually_added_albums": manual_recs
    }
    
    login_resp = requests.post(f"{BASE_URL}/auth/lastfm", json=login_payload)
    
    if login_resp.status_code != 200:
        print(f"❌ Login failed: {login_resp.text}")
        return
        
    final_user_id = login_resp.json()['user_id']
    print(f"✅ Login successful. Final User ID: {final_user_id}")

    # 5. Verify the manual album exists for the new/final user
    print("\n5. Verifying manual album transfer...")
    final_recs_resp = requests.get(f"{BASE_URL}/api/users/{final_user_id}/recommendations")
    final_recs = final_recs_resp.json()
    
    transferred = [r for r in final_recs if r.get('album_title') == "Test Manual Album" and r.get('source') == 'manual']
    
    if transferred:
        print("✅ SUCCESS: Manual album was transferred correctly!")
    else:
        print("❌ FAILURE: Manual album was NOT transferred.")
        print("Final recommendations:", json.dumps(final_recs, indent=2))

if __name__ == "__main__":
    test_manual_album_sync()
