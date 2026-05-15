
import asyncio
import httpx
import os
from bs4 import BeautifulSoup
import base64
import re

# Use the key from environment or hardcode for local testing if needed
# (In production it will be in env)
SCRAPINGBOT_KEY = os.getenv("SCRAPINGBOT_API_KEY", "TEST_KEY_IF_NEEDED")

async def test_marilians_via_scrapingbot():
    artist = "Arctic Monkeys"
    album = "AM"
    
    clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
    query = clean_query.replace(" ", "+")
    
    # Marilians Search URL (Corrected to match pricing_client.py)
    target_url = f"https://www.marilians.com/busqueda?controller=search&s={query}"
    print(f"Target URL: {target_url}")
    
    # ScrapingBot Generic/Retail Endpoint
    # We want raw HTML to parse it ourselves with existing logic
    # Try 'retail' first (sometimes it returns HTML in 'html' field if parsing fails)
    # Or try a more generic endpoint if known. 
    # Based on docs, usually /scrape/real-estate or /scrape/retail are specialized.
    # But often just passing 'useChrome': True returns the page source.
    
    api_url = "http://api.scraping-bot.io/scrape/retail"
    auth = ("Vinilogy", SCRAPINGBOT_KEY)
    
    payload = {
        "url": target_url,
        "options": {
            "useChrome": True, # Marilians might need JS or just to be safe
            "premiumProxy": True,
            "proxyCountry": "ES",
            "waitForNetworkRequests": True
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    print("Sending request to ScrapingBot...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                api_url,
                json=payload,
                headers=headers,
                auth=auth
            )
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                # Check what we got
                # Typically valid fields: 'html', 'data', 'status'
                if 'html' in data:
                    print("✅ Received HTML content!")
                    html = data['html']
                    soup = BeautifulSoup(html, 'html.parser')
                    products = soup.find_all('div', class_='product-grid-item')
                    print(f"Found {len(products)} products in HTML.")
                else:
                    print("⚠️ No 'html' field in response.")
                    print(f"Keys: {data.keys()}")
                    print(f"Data: {str(data)[:500]}") # Print start of data
            
            # TEST 2: Try Raw HTML endpoint
            print("\n--- Trying Raw HTML Endpoint ---")
            raw_url = "http://api.scraping-bot.io/scrape/raw-html"
            payload['options']['useChrome'] = True # Ensure chrome is used
            
            response2 = await client.post(
                raw_url,
                json=payload,
                headers=headers,
                auth=auth
            )
            print(f"Raw Endpoint Status: {response2.status_code}")
            if response2.status_code == 200:
                print("✅ Received Raw Response (Status 200)")
                # Check if it's JSON or Raw HTML
                try:
                    data2 = response2.json()
                    if 'body' in data2:
                         html_content = data2['body']
                    elif 'html' in data2:
                         html_content = data2['html']
                    else:
                         html_content = None
                         print(f"Keys in raw response: {data2.keys()}")
                except:
                    # Not JSON, assume raw HTML
                    print("⚠️ Response is not JSON, assuming Raw HTML body")
                    html_content = response2.text

                if html_content:
                     soup = BeautifulSoup(html_content, 'html.parser')
                     products = soup.find_all('article', class_=re.compile(r'product', re.I))
                     if not products:
                         products = soup.find_all('div', class_=re.compile(r'product', re.I))

                     print(f"Found {len(products)} products in Raw Body.")
                     if products:
                        print(f"First product: {products[0].get_text(strip=True)[:100]}")
            else:
                print(f"Raw Error: {response2.status_code} - {response2.text[:500]}...")

            # TEST 3: Try generic /scrape/do endpoint
            print("\n--- Trying Generic /scrape/do Endpoint ---")
            do_url = "http://api.scraping-bot.io/scrape/do"
            # Payload is same
            
            response3 = await client.post(
                do_url,
                json=payload,
                headers=headers,
                auth=auth
            )
            print(f"Do Endpoint Status: {response3.status_code}")
            if response3.status_code == 200:
                data3 = response3.json()
                 # Typically returns 'body'
                if 'body' in data3:
                     print("✅ Received Do Body!")
                     soup = BeautifulSoup(data3['body'], 'html.parser')
                     products = soup.find_all('div', class_='product-grid-item')
                     print(f"Found {len(products)} products in Do Body.")
                     if products:
                        print(f"First product: {products[0].get_text(strip=True)[:100]}")
                else:
                    print(f"Keys in Do response: {data3.keys()}")
            else:
                print(f"Do Error: {response3.status_code} - {response3.text[:500]}...")

                
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    if SCRAPINGBOT_KEY == "TEST_KEY_IF_NEEDED":
        print("Please set SCRAPINGBOT_API_KEY environment variable.")
    else:
        asyncio.run(test_marilians_via_scrapingbot())
