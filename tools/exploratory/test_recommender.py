import httpx
import asyncio
import os

RECOMMENDER_URL = "http://localhost:3002"

async def test_artist_recommendation():
    print("Testing artist-single-recommendation...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Test with a known artist
        payload = {
            "artist_name": "The Beatles",
            "top_albums": 3,
            "csv_mode": False,
            "cache_only": False
        }
        
        try:
            resp = await client.post(f"{RECOMMENDER_URL}/artist-single-recommendation", json=payload)
            if resp.status_code == 200:
                data = resp.json()
                print(f"✅ Success! Got {len(data.get('recommendations', []))} recommendations")
                print(data)
            else:
                print(f"❌ Failed: {resp.status_code} - {resp.text}")
        except Exception as e:
            print(f"❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_artist_recommendation())
