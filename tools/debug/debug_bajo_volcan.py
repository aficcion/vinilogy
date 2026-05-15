
import asyncio
import httpx
from bs4 import BeautifulSoup
import re

def normalize(text):
    return (
        text.lower()
        .replace(",", " ")
        .replace("-", " ")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
        .strip()
    )

async def debug_scraper():
    artist = "Arctic Monkeys"
    album = "Whatever People Say I Am, That's What I'm Not"
    
    # Test cases
    queries = [
        "Arctic Monkeys People Say I Am", # Skip first word
        "Arctic Monkeys That's What I'm Not", # Second half
        "Arctic Monkeys", # Just artist (might be too broad but lets see if it appears)
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        for q_text in queries:
            print(f"\n--- Testing Query: {q_text} ---")
            clean_q = q_text.replace("/", " ").replace("  ", " ")
            query = clean_q.replace(" ", "+")
            
            url = f"https://www.bajoelvolcan.es/busqueda/listaLibros.php?tipoBus=full&palabrasBusqueda={query}"
            print(f"URL: {url}")
            
            try:
                response = await client.get(url, timeout=10.0)
                soup = BeautifulSoup(response.text, 'html.parser')
                products = soup.find_all('li', class_='item')
                print(f"Found {len(products)} products")
                
                if products:
                    print(f"✅ SUCCESS! Found {len(products)} items.")
                    for p in products:
                        t = p.find('dd', class_='title').get_text(strip=True)
                        print(f" - {t}")
                    
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(debug_scraper())
