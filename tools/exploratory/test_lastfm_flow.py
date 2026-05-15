import httpx
import asyncio

async def test_full_flow():
    """Test the complete Last.fm recommendation flow"""
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 0. Create User (Simulate Login)
        print("Step 0: Creating user...")
        resp = await client.post(
            "http://localhost:5000/auth/lastfm",
            json={"lastfm_username": "aficcion"}
        )
        if resp.status_code != 200:
            print(f"❌ Failed to create user: {resp.status_code}")
            return
        
        user_data = resp.json()
        user_id = user_data.get("user_id")
        print(f"✅ User created with ID: {user_id}")

        # 1. Get Last.fm recommendations
        print("Step 1: Fetching Last.fm recommendations...")
        resp = await client.post(
            "http://localhost:5000/api/lastfm/recommendations",
            json={"username": "aficcion", "time_range": "medium_term"}
        )
        
        if resp.status_code != 200:
            print(f"❌ Failed to get Last.fm recommendations: {resp.status_code}")
            print(resp.text)
            return
        
        data = resp.json()
        lastfm_recs = data.get("albums", [])
        print(f"✅ Got {len(lastfm_recs)} Last.fm recommendations")
        
        # 2. Get user's selected artists
        print(f"\nStep 2: Getting selected artists for user {user_id}...")
        resp = await client.get(f"http://localhost:5000/api/users/{user_id}/selected-artists")
        
        if resp.status_code != 200:
            print(f"❌ Failed to get selected artists: {resp.status_code}")
            return
        
        selected_artists = resp.json()
        print(f"✅ User has {len(selected_artists)} selected artists")
        for artist in selected_artists:
            print(f"  - {artist['artist_name']}")
        
        # 3. Get recommendations for each selected artist
        print("\nStep 3: Getting recommendations for selected artists...")
        manual_recs = []
        for artist in selected_artists:
            artist_name = artist['artist_name']
            resp = await client.post(
                "http://localhost:5000/api/recommendations/artist-single",
                json={"artist_name": artist_name, "top_albums": 3, "cache_only": True}
            )
            
            if resp.status_code == 200:
                data = resp.json()
                recs = data.get("recommendations", [])
                manual_recs.extend(recs)
                print(f"  ✅ {artist_name}: {len(recs)} recommendations")
            else:
                print(f"  ⚠️ {artist_name}: {resp.status_code}")
        
        print(f"\n✅ Total manual recommendations: {len(manual_recs)}")
        
        # 4. Merge recommendations
        print("\nStep 4: Merging recommendations...")
        resp = await client.post(
            "http://localhost:5000/api/recommendations/merge",
            json={
                "lastfm_recommendations": lastfm_recs,
                "artist_recommendations": manual_recs
            }
        )
        
        if resp.status_code != 200:
            print(f"❌ Failed to merge: {resp.status_code}")
            print(resp.text)
            return
        
        merged_data = resp.json()
        final_recs = merged_data.get("recommendations", [])
        print(f"✅ Merged into {len(final_recs)} total recommendations")
        
        # 5. Save to database
        print("\nStep 5: Saving recommendations to database...")
        resp = await client.post(
            f"http://localhost:5000/users/{user_id}/recommendations/regenerate",
            json={"new_recs": final_recs}
        )
        
        if resp.status_code != 200:
            print(f"❌ Failed to save: {resp.status_code}")
            print(resp.text)
            return
        
        print(f"✅ Saved {len(final_recs)} recommendations to database")
        
        # 6. Save Last.fm profile
        print("\nStep 6: Saving Last.fm profile...")
        resp = await client.post(
            "http://localhost:5000/api/lastfm/top-artists",
            json={"username": "aficcion", "time_range": "medium_term"}
        )
        
        if resp.status_code != 200:
            print(f"❌ Failed to get top artists: {resp.status_code}")
            return
        
        profile_data = resp.json()
        top_artists = profile_data.get("artists", [])
        print(f"✅ Got {len(top_artists)} top artists")
        
        resp = await client.put(
            f"http://localhost:5000/api/users/{user_id}/profile/lastfm",
            json={
                "lastfm_username": "aficcion",
                "top_artists": top_artists[:50]
            }
        )
        
        if resp.status_code != 200:
            print(f"❌ Failed to save profile: {resp.status_code}")
            print(resp.text)
            return
        
        print("✅ Last.fm profile saved")
        
        print("\n🎉 Complete! All steps successful.")

if __name__ == "__main__":
    asyncio.run(test_full_flow())
