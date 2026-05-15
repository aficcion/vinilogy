# import pytest
from fastapi.testclient import TestClient
from gateway.main import app
from gateway import db

client = TestClient(app)

# Reset DB for testing (optional, or just use a unique user)
# For simplicity, we'll create a new unique user for each run or just rely on unique emails.
import time
unique_id = int(time.time())
email = f"test_user_{unique_id}@example.com"
google_sub = f"sub_{unique_id}"
lastfm_user = f"user_{unique_id}"

def test_auth_flow():
    # 1. Google Login
    resp = client.post("/auth/google", json={
        "email": email,
        "display_name": "Test User",
        "google_sub": google_sub
    })
    assert resp.status_code == 200
    user_id = resp.json()["user_id"]
    assert isinstance(user_id, int)
    
    # 2. Last.fm Login (should create new or return existing)
    resp = client.post("/auth/lastfm", json={
        "lastfm_username": lastfm_user
    })
    assert resp.status_code == 200
    lfm_user_id = resp.json()["user_id"]
    assert isinstance(lfm_user_id, int)
    
    # 3. Link Last.fm (use a different username to avoid conflict with step 2)
    link_user = f"link_{lastfm_user}"
    resp = client.post("/auth/lastfm/link", json={
        "user_id": user_id,
        "lastfm_username": link_user
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "linked"
    
    return user_id

def test_profile_flow():
    user_id = test_auth_flow()
    
    # Upsert Profile
    top_artists = [{"name": "Radiohead", "playcount": 1000}, {"name": "Daft Punk", "playcount": 500}]
    resp = client.put(f"/users/{user_id}/profile/lastfm", json={
        "lastfm_username": lastfm_user,
        "top_artists": top_artists
    })
    assert resp.status_code == 200
    
    # Get Profile
    resp = client.get(f"/users/{user_id}/profile/lastfm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["lastfm_username"] == lastfm_user
    assert len(data["top_artists"]) == 2
    assert data["top_artists"][0]["name"] == "Radiohead"

def test_selected_artists_flow():
    user_id = test_auth_flow()
    
    # Add Artist
    resp = client.post(f"/users/{user_id}/selected-artists", json={
        "artist_name": "Pink Floyd",
        "source": "manual"
    })
    assert resp.status_code == 200
    
    # Get Artists
    resp = client.get(f"/users/{user_id}/selected-artists")
    assert resp.status_code == 200
    artists = resp.json()
    assert len(artists) >= 1
    assert artists[0]["artist_name"] == "Pink Floyd"
    selection_id = artists[0]["id"]
    
    # Remove Artist
    resp = client.delete(f"/users/{user_id}/selected-artists/{selection_id}")
    assert resp.status_code == 200
    
    # Verify Removal
    resp = client.get(f"/users/{user_id}/selected-artists")
    artists = resp.json()
    # Should be empty or at least not contain the removed one
    ids = [a["id"] for a in artists]
    assert selection_id not in ids

def test_recommendations_flow():
    user_id = test_auth_flow()
    
    # Regenerate
    new_recs = [
        {"artist_name": "Artist A", "album_title": "Album A", "source": "manual"},
        {"artist_name": "Artist B", "album_title": "Album B", "source": "lastfm"}
    ]
    resp = client.post(f"/users/{user_id}/recommendations/regenerate", json={
        "new_recs": new_recs
    })
    assert resp.status_code == 200
    
    # Get Recommendations
    resp = client.get(f"/users/{user_id}/recommendations")
    assert resp.status_code == 200
    recs = resp.json()
    assert len(recs) == 2
    rec_a = next(r for r in recs if r["artist_name"] == "Artist A")
    
    # Update Status
    resp = client.patch(f"/users/{user_id}/recommendations/{rec_a['id']}", json={
        "new_status": "favorite"
    })
    assert resp.status_code == 200
    
    # Get Favorites
    resp = client.get(f"/users/{user_id}/recommendations/favorites")
    assert resp.status_code == 200
    favs = resp.json()
    assert len(favs) == 1
    assert favs[0]["artist_name"] == "Artist A"

if __name__ == "__main__":
    # Manual run if pytest not available
    print("Running Auth Flow...")
    test_auth_flow()
    print("Running Profile Flow...")
    test_profile_flow()
    print("Running Selected Artists Flow...")
    test_selected_artists_flow()
    print("Running Recommendations Flow...")
    test_recommendations_flow()
    print("All tests passed!")
