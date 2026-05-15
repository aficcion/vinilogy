
import asyncio
import httpx
import time
import os
from bs4 import BeautifulSoup

ZENROWS_API_KEY = "20b0e64040274e8119b87879b293765229fe83a3"

async def test_performance():
    artist = "Arctic Monkeys"
    album = "AM"
    clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
    query = clean_query.replace(" ", "+")
    
    # 1. Test Marilians (ZenRows)
    print("\n--- Testing Marilians (via ZenRows) ---")
    marilians_url = f"https://www.marilians.com/busqueda?controller=search&s={query}"
    
    params_marilians = {
        "apikey": ZENROWS_API_KEY,
        "url": marilians_url,
        "js_render": "true",
        # "premium_proxy": "true", # Optional, maybe needed for FNAC
        # "country": "es"
    }
    
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get("https://api.zenrows.com/v1/", params=params_marilians)
            latency = time.time() - start_time
            
            if response.status_code == 200:
                print(f"✅ Success! (Status 200)")
                print(f"⏱️ Latency: {latency:.2f} seconds")
                # Basic validation
                if "Arctic Monkeys" in response.text:
                    print("   Content verified: Found 'Arctic Monkeys'")
            else:
                print(f"❌ Failed: Status {response.status_code}")
                print(f"   Error: {response.text[:200]}")
                
    except Exception as e:
        print(f"❌ Exception: {e}")

    # 2. Test FNAC (via ZenRows)
    print("\n--- Testing FNAC (via ZenRows) ---")
    # Using specific search URL for FNAC
    fnac_url = f"https://www.fnac.es/SearchResult/ResultList.aspx?Search={query}&sft=1&sa=0"
    
    params_fnac = {
        "apikey": ZENROWS_API_KEY,
        "url": fnac_url,
        "js_render": "true",
        # "premium_proxy": "true", # Removed
        # "country": "es"          # Removed
    }
    
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get("https://api.zenrows.com/v1/", params=params_fnac)
            latency = time.time() - start_time
            
            if response.status_code == 200:
                print(f"✅ Success! (Status 200)")
                print(f"⏱️ Latency: {latency:.2f} seconds")
                if "Arctic Monkeys" in response.text:
                    print("   Content verified: Found 'Arctic Monkeys'")
                
                # Check for blocking/captcha
                if "captcha" in response.text.lower() or "challenge" in response.text.lower():
                    print("⚠️ Warning: Possible CAPTCHA detected/Challenge page")
            else:
                print(f"❌ Failed: Status {response.status_code}")
                print(f"   Error: {response.text[:200]}")

    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_performance())
