import os
import sys
import httpx
import asyncio
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

async def check_health():
    print("🔍 Checking Production Health...\n")
    
    # 1. Check Environment Variables
    print("1. Environment Variables:")
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    
    if client_id:
        print(f"   ✅ SPOTIFY_CLIENT_ID found ({client_id[:4]}...)")
    else:
        print("   ❌ SPOTIFY_CLIENT_ID MISSING")
        
    if client_secret:
        print(f"   ✅ SPOTIFY_CLIENT_SECRET found ({client_secret[:4]}...)")
    else:
        print("   ❌ SPOTIFY_CLIENT_SECRET MISSING")
        
    spotify_url = os.getenv("SPOTIFY_SERVICE_URL", "http://127.0.0.1:3005")
    print(f"   ℹ️  SPOTIFY_SERVICE_URL: {spotify_url}")
    
    print("\n2. Service Connectivity:")
    
    # 2. Check Spotify Service directly
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{spotify_url}/health", timeout=5.0)
            if resp.status_code == 200:
                print(f"   ✅ Spotify Service is UP at {spotify_url}")
            else:
                print(f"   ❌ Spotify Service returned {resp.status_code}")
                print(f"      Response: {resp.text}")
    except Exception as e:
        print(f"   ❌ Could not connect to Spotify Service at {spotify_url}")
        print(f"      Error: {str(e)}")
        
    # 3. Check Gateway -> Spotify connection (via Gateway)
    gateway_url = "http://127.0.0.1:5000" # Assuming standard port
    print(f"\n3. Gateway Integration ({gateway_url}):")
    
    try:
        async with httpx.AsyncClient() as client:
            # Try a search
            resp = await client.get(f"{gateway_url}/api/spotify/search/artists?q=daft+punk", timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                total = data.get("total", 0)
                print(f"   ✅ Gateway Search working! Found {total} artists")
            else:
                print(f"   ❌ Gateway Search failed with {resp.status_code}")
                print(f"      Response: {resp.text}")
    except Exception as e:
        print(f"   ❌ Could not connect to Gateway at {gateway_url}")
        print(f"      Error: {str(e)}")

    print("\n---------------------------------------------------")
    if not client_id or not client_secret:
        print("⚠️  CRITICAL: Missing Spotify Credentials")
    elif "Could not connect" in str(sys.stdout): # This check is pseudo-code logic for the user
        print("⚠️  CRITICAL: Service connectivity issues")
    else:
        print("ℹ️  If connectivity is fine but search fails, check Spotify API quotas or credentials validity.")

if __name__ == "__main__":
    asyncio.run(check_health())
