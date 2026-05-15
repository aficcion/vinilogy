import os
import asyncio
import httpx
from dotenv import load_dotenv
from pathlib import Path

# Load env
env_path = Path(".env")
load_dotenv(dotenv_path=env_path)

client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()

print(f"Client ID loaded: {client_id[:5]}..." if client_id else "Client ID NOT loaded")
print(f"Client Secret loaded: {client_secret[:5]}..." if client_secret else "Client Secret NOT loaded")

async def test_ebay():
    url = "https://api.ebay.com/identity/v1/oauth2/token"
    auth = (client_id, client_secret)
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }
    
    print(f"\nTesting connection to: {url}")
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                url,
                auth=auth,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            print(f"Status Code: {resp.status_code}")
            if resp.status_code == 200:
                print("✅ SUCCESS! Token received.")
                print(f"Token: {resp.json()['access_token'][:20]}...")
            else:
                print(f"❌ FAILED. Response: {resp.text}")
        except Exception as e:
            print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_ebay())
