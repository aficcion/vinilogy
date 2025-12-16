import asyncio
import httpx
from bs4 import BeautifulSoup
import re

async def debug_bajo_el_volcan():
    artist = "Arcade Fire"
    album = "WE"
    
    clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
    query = clean_query.replace(" ", "+")
    
    url = f"https://www.bajoelvolcan.es/busqueda/listaLibros.php?tipoBus=full&palabrasBusqueda={query}"
    print(f"Fetching URL: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        response = await client.get(url)
        print(f"Status Code: {response.status_code}")
        
        soup = BeautifulSoup(response.text, 'lxml')
        products = soup.find_all('li', class_='item')
        
        print(f"Found {len(products)} products")
        
        for i, product in enumerate(products):
            print(f"\n--- Product {i+1} ---")
            
            # Title
            title_elem = product.find('dd', class_='title')
            title = "N/A"
            link = "N/A"
            if title_elem:
                title_link = title_elem.find('a')
                if title_link:
                    title = title_link.get_text(strip=True)
                    link = title_link.get('href')
            
            # Creator
            creator_elem = product.find('dd', class_='creator')
            creator = creator_elem.get_text(strip=True) if creator_elem else "N/A"
            
            # Price
            price_elem = product.find('strong')
            price = price_elem.get_text(strip=True) if price_elem else "N/A"
            
            # Availability (guessing selectors, will inspect output)
            # Printing entire text of the product item to find "Consultar disponibilidad"
            full_text = product.get_text(separator=' | ', strip=True)
            
            print(f"Title: {title}")
            print(f"Creator (Artist): {creator}")
            print(f"Link: {link}")
            print(f"Price: {price}")
            print(f"Full Text: {full_text}")

if __name__ == "__main__":
    asyncio.run(debug_bajo_el_volcan())
