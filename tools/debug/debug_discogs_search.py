import asyncio
import os
import httpx
import json

async def debug_discogs():
    # Load env vars
    env_vars = {}
    try:
        with open("/Users/carlosbautista/Downloads/Vinylbe/.env", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, val = line.strip().split("=", 1)
                    env_vars[key] = val
    except Exception:
        pass

    key = env_vars.get("DISCOGS_KEY")
    secret = env_vars.get("DISCOGS_SECRET")
    
    if not key:
        print("No API key found")
        return

    artist_name = "Andrés Calamaro"
    headers = {"User-Agent": "VinylbeDebug/1.0"}
    url = "https://api.discogs.com/database/search"
    
    # Test 1: Current strict params
    print(f"--- TEST 1: Strict (Current) ---")
    params1 = {
        "artist": artist_name,
        "format": "Vinyl,LP,Album",
        "type": "master",
        "per_page": 100,
        "key": key,
        "secret": secret
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params1, headers=headers)
        data = resp.json()
        results = data.get("results", [])
        print(f"Results found: {len(results)}")
        for r in results[:5]:
            print(f" - {r.get('title')} ({r.get('year')}) [Format: {r.get('format')}]")

    # Test 2: Relaxed Format (Just Vinyl, Album)
    print(f"\n--- TEST 2: Relaxed Format (Vinyl, Album) ---")
    params2 = {
        "artist": artist_name,
        "format": "Vinyl,Album",
        "type": "master",
        "per_page": 100,
        "key": key,
        "secret": secret
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params2, headers=headers)
        data = resp.json()
        results = data.get("results", [])
        print(f"Results found: {len(results)}")
        for r in results[:5]:
            print(f" - {r.get('title')} ({r.get('year')}) [Format: {r.get('format')}]")

    # Test 3: Just Vinyl (No Album tag enforcement)
    print(f"\n--- TEST 3: Just Vinyl ---")
    params3 = {
        "artist": artist_name,
        "format": "Vinyl",
        "type": "master",
        "per_page": 100,
        "key": key,
        "secret": secret
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params3, headers=headers)
        data = resp.json()
        results = data.get("results", [])
        print(f"Results found: {len(results)}")
        for r in results[:5]:
            print(f" - {r.get('title')} ({r.get('year')}) [Format: {r.get('format')}]")

    # Test 4: Query based (q=Artist) instead of artist param
    print(f"\n--- TEST 4: Query string (q=Artist) + Vinyl + Master ---")
    params4 = {
        "q": artist_name,
        "format": "Vinyl",
        "type": "master",
        "per_page": 100,
        "key": key,
        "secret": secret
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, params=params4, headers=headers)
        data = resp.json()
        results = data.get("results", [])
        print(f"Results found: {len(results)}")
        for r in results[:5]:
            print(f" - {r.get('title')} ({r.get('year')}) [Format: {r.get('format')}]")

if __name__ == "__main__":
    asyncio.run(debug_discogs())
