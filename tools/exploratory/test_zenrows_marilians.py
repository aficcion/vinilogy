
import asyncio
import httpx
import urllib.parse
from bs4 import BeautifulSoup

ZENROWS_API_KEY = "20b0e64040274e8119b87879b293765229fe83a3"

async def test_zenrows():
    artist = "Arctic Monkeys"
    album = "AM"
    
    clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
    query = clean_query.replace(" ", "+")
    
    # Target URL (Marilians Search)
    target_url = f"https://www.marilians.com/busqueda?controller=search&s={query}"
    print(f"Target URL: {target_url}")
    
    # ZenRows Proxy URL Construction
    # We use the standard proxy mode or API mode
    # For simple scraping, API mode (GET) is easiest
    
    params = {
        "apikey": ZENROWS_API_KEY,
        "url": target_url,
        "js_render": "true", # Enable JS rendering
        # "premium_proxy": "true", # Removed to fix 400 error
        # "country": "es" # Removed to fix 400 error
    }
    
    zenrows_url = "https://api.zenrows.com/v1/"
    
    print("Sending request to ZenRows...")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.get(zenrows_url, params=params)
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Success!")
                html = response.text
                soup = BeautifulSoup(html, 'html.parser')
                
                # Check for products
                products = soup.find_all(['article', 'div'], class_='product-miniature')
                if not products:
                     products = soup.find_all('article', class_=lambda x: x and 'product' in x)
                     
                print(f"Found {len(products)} products.")
                
                if products:
                    first_title = products[0].find(['h2', 'h3'], class_='product-title').get_text(strip=True)
                    print(f"First product title: {first_title}")
                    
                    price = products[0].find('span', class_='price').get_text(strip=True)
                    print(f"First product price: {price}")
                    
            else:
                print(f"Error: {response.text}")
                
        except Exception as e:
            print(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_zenrows())
