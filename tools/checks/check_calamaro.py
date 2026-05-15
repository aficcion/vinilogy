import asyncio
import os
import httpx
from typing import List, Dict, Any

DISCOGS_KEY = "QvLhWzQvLhWzQvLhWzQv"  # Placeholder, will rely on env vars if running properly or I need to ask user
# Actually, I should check if I can read the env file or assume they are set in the environment where I run the command.
# The user's env file is at /Users/carlosbautista/Downloads/Vinylbe/.env
# I will try to read it first to get the keys.

async def check_discogs_scores():
    # Load env vars manually since I can't rely on os.environ being populated from the .env file in this context
    env_vars = {}
    try:
        with open("/Users/carlosbautista/Downloads/Vinylbe/.env", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    key, val = line.strip().split("=", 1)
                    env_vars[key] = val
    except Exception as e:
        print(f"Error reading .env: {e}")
        return

    key = env_vars.get("DISCOGS_KEY")
    secret = env_vars.get("DISCOGS_SECRET")
    
    if not key or not secret:
        print("Discogs credentials not found in .env")
        return

    artist_name = "Andrés Calamaro"
    headers = {"User-Agent": "VinylbeTest/1.0"}
    
    # Same params as in the code
    params = {
        "artist": artist_name,
        "format": "Vinyl,LP,Album",
        "type": "master",
        "per_page": 50,
        "key": key,
        "secret": secret
    }
    
    url = "https://api.discogs.com/database/search"
    
    async with httpx.AsyncClient() as client:
        print(f"Fetching data for {artist_name}...")
        resp = await client.get(url, params=params, headers=headers)
        
        if resp.status_code != 200:
            print(f"Error: {resp.status_code} - {resp.text}")
            return
            
        data = resp.json()
        results = data.get("results", [])
        
        print(f"Found {len(results)} raw results.")
        
        processed = []
        excluded_terms = [
            "en directo", "live", "concert", "concierto", "tour", 
            "aniversario", "anniversary", "vivo", "demasía",
            "deluxe", "edition", "edición", "expanded", "bonus", 
            "special", "especial", "remix", "demos", "rarities",
            "best of", "greatest hits", "anthology", "collection", "colección",
            "discografía básica", "discografia basica"
        ]
        
        for result in results:
            title = result.get("title", "")
            album_name = title
            if " - " in title:
                parts = title.split(" - ", 1)
                if parts[0].lower().strip() == artist_name.lower().strip():
                    album_name = parts[1]
            
            if any(term in album_name.lower() for term in excluded_terms):
                continue
                
            community = result.get("community", {})
            want = community.get("want", 0)
            have = community.get("have", 0)
            score = want + have
            
            processed.append({
                "title": album_name,
                "full_title": title,
                "score": score,
                "want": want,
                "have": have,
                "year": result.get("year")
            })
            
        processed.sort(key=lambda x: x["score"], reverse=True)
        
        print("\nTop 10 Results by Popularity (Want + Have):")
        for i, item in enumerate(processed[:10], 1):
            print(f"{i}. {item['title']} ({item['year']}) - Score: {item['score']} (Want: {item['want']}, Have: {item['have']})")

if __name__ == "__main__":
    asyncio.run(check_discogs_scores())
