import asyncio
import httpx
import os
import json

DISCOGS_KEY = os.getenv("DISCOGS_CONSUMER_KEY", "") or os.getenv("DISCOGS_KEY", "")
DISCOGS_SECRET = os.getenv("DISCOGS_CONSUMER_SECRET", "") or os.getenv("DISCOGS_SECRET", "")

async def main():
    headers = {"User-Agent": "VinylRecommendationSystem/1.0"}
    url = "https://api.discogs.com/masters/25721"
    params = {"key": DISCOGS_KEY, "secret": DISCOGS_SECRET}
    
    async with httpx.AsyncClient(headers=headers) as client:
        print(f"Fetching {url}...")
        resp = await client.get(url, params=params)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(json.dumps(data, indent=2))
        else:
            print(resp.text)

if __name__ == "__main__":
    asyncio.run(main())
