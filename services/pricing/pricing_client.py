from typing import Optional, Dict, Any, List, Tuple
import os
import httpx
import asyncio
import time
import requests
import re
from bs4 import BeautifulSoup
from libs.shared.utils import log_event
from urllib.parse import quote_plus

EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
VINYL_CATEGORY_ID = "176985"

EU_COUNTRIES = "AT,BE,BG,HR,CY,CZ,DK,EE,FI,FR,DE,GR,HU,IE,IT,LV,LT,LU,MT,NL,PL,PT,RO,SK,SI,ES,SE"


def normalize(text: str) -> str:
    """Normaliza strings para comparaciones simples."""
    return (
        text.lower()
        .replace(",", " ")
        .replace("-", " ")
        .replace("_", " ")
        .replace("/", " ")
        .strip()
    )


class PricingClient:
    def __init__(self):
        self.client_id = os.getenv("EBAY_CLIENT_ID")
        self.client_secret = os.getenv("EBAY_CLIENT_SECRET")
        self.zenrows_key = os.getenv("ZENROWS_API_KEY")
        
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "EBAY_CLIENT_ID y EBAY_CLIENT_SECRET deben estar en variables de entorno"
            )
        
        self.http_client: Optional[httpx.AsyncClient] = None
        self.access_token: Optional[str] = None

    async def start(self):
        """Inicializa el cliente HTTP asíncrono con headers de navegador."""
        default_headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        self.http_client = httpx.AsyncClient(timeout=20.0, headers=default_headers, follow_redirects=True)
        # Token se obtiene lazy en la primera petición real para no bloquear el startup
        try:
            await self._get_access_token()
        except Exception as e:
            log_event("pricing-service", "WARNING", f"eBay token no disponible en startup (se reintentará): {e}")

    async def stop(self):
        """Cierra el cliente HTTP."""
        if self.http_client:
            await self.http_client.aclose()

    def is_ready(self) -> bool:
        """Verifica si el cliente HTTP está inicializado (eBay token es opcional)."""
        return self.http_client is not None

    async def _get_access_token(self) -> str:
        """Obtiene un application access token de eBay usando client credentials."""
        auth = (self.client_id, self.client_secret)
        data = {
            "grant_type": "client_credentials",
            "scope": "https://api.ebay.com/oauth/api_scope",
        }

        resp = await self.http_client.post(
            EBAY_OAUTH_URL,
            auth=auth,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        payload = resp.json()
        self.access_token = payload["access_token"]
        return self.access_token

    def _pick_best_ebay_item(
        self,
        item_summaries: List[dict],
        artist: str,
        album: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Dado itemSummaries de eBay, devuelve el mejor item:
          - título razonable (contenga artist y algo del álbum)
          - precio total más bajo (item + shipping)
          - en EUR
          - ubicado en la Unión Europea
        """
        artist_n = normalize(artist)
        album_n = normalize(album)
        
        # Lista de códigos de país UE para validación
        eu_country_codes = EU_COUNTRIES.split(",")

        candidates: List[Dict[str, Any]] = []

        for item in item_summaries:
            # FILTRO DE UBICACIÓN UE (defensa contra API que ignora itemLocationCountry)
            item_location = item.get("itemLocation", {})
            item_country = item_location.get("country")
            
            if not item_country or item_country not in eu_country_codes:
                # Log warning cuando eBay devuelve item fuera de UE
                if item_country:
                    log_event(
                        "pricing-service", 
                        "WARNING", 
                        f"eBay returned non-EU item from {item_country}, filtering out"
                    )
                continue
            
            title = item.get("title", "")
            title_n = normalize(title)

            if not any(w for w in artist_n.split() if w in title_n):
                continue

            if all(word not in title_n for word in album_n.split() if word):
                continue

            if "cd" in title_n or "cassette" in title_n:
                continue

            price = item.get("price", {})
            ship_opts = item.get("shippingOptions", [])

            if not price or not ship_opts:
                continue

            if price.get("currency") != "EUR":
                continue

            try:
                item_price = float(price.get("value", 0.0))
            except (TypeError, ValueError):
                continue

            try:
                ship_cost = float(
                    ship_opts[0].get("shippingCost", {}).get("value", 0.0)
                )
            except (TypeError, ValueError, IndexError):
                continue

            total = item_price + ship_cost

            candidates.append(
                {
                    "provider": "ebay",
                    "title": title,
                    "item_price": item_price,
                    "shipping_cost": ship_cost,
                    "total_price": total,
                    "currency": price.get("currency"),
                    "url": item.get("itemWebUrl"),
                }
            )

        if not candidates:
            return None

        candidates.sort(key=lambda c: c["total_price"])
        return candidates[0]

    async def fetch_best_ebay_offer(
        self,
        artist: str,
        album: str,
        marketplace_id: str = "EBAY_ES",
    ) -> Optional[Dict[str, Any]]:
        """
        Busca en eBay el vinilo de artist + album y devuelve la mejor oferta
        (precio más barato en EUR ubicado en la Unión Europea).
        """
        # Lazy token: obtener si no está disponible, con un retry
        if not self.access_token:
            try:
                await self._get_access_token()
            except Exception as e:
                log_event("pricing-service", "WARNING", f"eBay token fetch failed: {e}")
                return None

        query = f"{artist} {album}"
        params = {
            "q": query,
            "category_ids": VINYL_CATEGORY_ID,
            "filter": f"itemLocationCountry:{{{EU_COUNTRIES}}}",
            "sort": "priceWithShipping",
            "limit": "20",
        }

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "X-EBAY-C-MARKETPLACE-ID": marketplace_id,
            "Content-Type": "application/json",
        }

        resp = await self.http_client.get(
            EBAY_BROWSE_URL, params=params, headers=headers
        )
        resp.raise_for_status()
        data = resp.json()
        
        items = data.get("itemSummaries", [])
        return self._pick_best_ebay_item(items, artist=artist, album=album)

    async def scrape_marilians_price(self, artist: str, album: str) -> Optional[float]:
        """Scrape price from Marilians search results with smart matching."""
        # Clean query: replace / with space to avoid URL issues
        clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
        query = clean_query.replace(" ", "+")
        
        url = f"https://www.marilians.com/busqueda?controller=search&s={query}"
        
        try:
            log_event("pricing-service", "INFO", f"Scraping Marilians for: {artist} - {album}")
            
            if self.zenrows_key:
                # Use ZenRows proxy to avoid 403 blocks
                zenrows_url = "https://api.zenrows.com/v1/"
                params = {
                    "apikey": self.zenrows_key,
                    "url": url,
                    "js_render": "true"
                }
                log_event("pricing-service", "DEBUG", "Using ZenRows proxy for Marilians")
                # Increase timeout for proxy
                response = await self.http_client.get(zenrows_url, params=params, timeout=30.0)
            else:
                # Direct request fallback
                log_event("pricing-service", "WARNING", "No ZENROWS_API_KEY found, using direct connection (likely to be blocked)")
                response = await self.http_client.get(url, timeout=10.0, follow_redirects=True)
            
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Normalize search terms for matching
            artist_norm = normalize(artist)
            album_norm = normalize(album)
            
            # Find all product containers (articles or divs with product class)
            products = soup.find_all(['article', 'div'], class_=re.compile(r'product', re.I))
            
            if not products:
                # Fallback: try to find any container with both title and price
                products = soup.find_all(['div', 'li'], class_=re.compile(r'item|result', re.I))
            
            best_match = None
            best_score = 0
            
            for product in products:
                # Find product title/name
                title_elem = product.find(['h2', 'h3', 'h4', 'a'], class_=re.compile(r'name|title|product', re.I))
                if not title_elem:
                    title_elem = product.find('a', href=True)
                
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                
                # Check for artist in separate h5 element (Marilians structure)
                artist_elem = product.find('h5')
                artist_text = artist_elem.get_text(strip=True) if artist_elem else ""
                
                # Combine title and artist for matching
                combined_text = f"{artist_text} {title}"
                title_norm = normalize(combined_text)
                
                # Calculate match score
                score = 0
                artist_words = [w for w in artist_norm.split() if len(w) > 1]
                album_words = [w for w in album_norm.split() if len(w) > 1]
                
                if not artist_words or not album_words:
                    continue

                # Check artist words
                artist_matches = sum(1 for word in artist_words if word in title_norm)
                if artist_matches == len(artist_words):
                     score += 50
                elif artist_matches > 0:
                     score += 20 * (artist_matches / len(artist_words))
                else:
                    # If no artist match, it's likely a different record or compilation
                    continue

                # Check album words
                album_matches = sum(1 for word in album_words if word in title_norm)
                if album_matches == len(album_words):
                     score += 50
                elif album_matches > 0:
                     score += 20 * (album_matches / len(album_words))
                
                # Minimum threshold for a valid match (e.g. full artist match + partial album match)
                if score < 60:
                    continue

                # Find price in this product
                price_elem = product.find(class_=re.compile(r'price|precio', re.I))
                if not price_elem:
                    continue
                
                price_text = price_elem.get_text(strip=True)
                price_match = re.search(r'(\d+)[.,](\d+)\s*€?', price_text)
                
                if price_match and score > best_score:
                    best_score = score
                    # Ensure dot format for float
                    best_match = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    log_event("pricing-service", "INFO", f"Marilians match: '{title}' (score: {score}, price: €{best_match})")
            
            if best_match and best_score > 0:
                log_event("pricing-service", "INFO", f"Found Marilians price: €{best_match} (match score: {best_score})")
                return best_match
            
            log_event("pricing-service", "INFO", f"No matching product found on Marilians for: {artist} - {album}")
            return None
            
        except Exception as e:
            log_event("pricing-service", "WARNING", f"Marilians scraping failed: {str(e)}")
            return None
    
    async def scrape_bajo_el_volcan_price(self, artist: str, album: str) -> Optional[Dict[str, Any]]:
        """Scrape price from Bajo el Volcán search results with smart matching."""
        # Clean query: replace / with space to avoid URL issues
        clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
        query = clean_query.replace(" ", "+")
        
        base_url = "https://www.bajoelvolcan.es"
        url = f"{base_url}/busqueda/listaLibros.php?tipoBus=full&palabrasBusqueda={query}"
        
        try:
            log_event("pricing-service", "INFO", f"Scraping Bajo el Volcán for: {artist} - {album}")
            
            response = await self.http_client.get(url, timeout=10.0, follow_redirects=True)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Normalize search terms for matching
            artist_norm = normalize(artist)
            album_norm = normalize(album)
            
            # Bajo el Volcán uses <li class="item"> for products
            products = soup.find_all('li', class_='item')
            
            if not products:
                log_event("pricing-service", "INFO", "No products found with strict search. Trying fallback (Artist only)...")
                
                # Fallback: search just by artist
                fallback_query = artist.replace(" ", "+")
                fallback_url = f"{base_url}/busqueda/listaLibros.php?tipoBus=full&palabrasBusqueda={fallback_query}"
                
                response_fallback = await self.http_client.get(fallback_url, timeout=10.0, follow_redirects=True)
                if response_fallback.status_code == 200:
                    soup_fallback = BeautifulSoup(response_fallback.text, 'lxml')
                    products = soup_fallback.find_all('li', class_='item')
                    log_event("pricing-service", "INFO", f"Fallback search found {len(products)} products")

            if not products:
                log_event("pricing-service", "WARNING", "No products found in Bajo el Volcán results (after fallback)")
                return None
            
            best_match = None
            best_score = -999  # Allow negative scores
            
            for product in products:
                # Find product title in <dd class="title">
                title_elem = product.find('dd', class_='title')
                if not title_elem:
                    continue
                
                # Get the link text and href inside the dd
                title_link = title_elem.find('a')
                if not title_link:
                    continue
                
                title = title_link.get_text(strip=True)
                product_path = title_link.get('href')
                product_url = f"{base_url}{product_path}" if product_path.startswith('/') else product_path
                
                title_norm = normalize(title)
                
                # Also check creator (artist) field
                creator_elem = product.find('dd', class_='creator')
                creator = creator_elem.get_text(strip=True) if creator_elem else ""
                creator_norm = normalize(creator)
                
                # Calculate match score
                score = 0
                artist_words = artist_norm.split()
                album_words = album_norm.split()
                
                # Check if artist name appears in title or creator
                # Allow words >= 2 chars (fixes "WE" issue)
                if any(word in title_norm or word in creator_norm for word in artist_words if len(word) >= 2):
                    score += 3  # Higher weight for artist match
                
                # Check if album name appears in title
                # Allow words >= 2 chars
                album_match_count = sum(1 for word in album_words if len(word) >= 2 and word in title_norm)
                score += album_match_count * 2
                
                # PENALTY for special editions
                special_edition_keywords = ['deluxe', 'remaster', 'remastered', 'reissue', 'anniversary', 
                                           'edition', 'limited', 'expanded', 'collectors', 'box', 'set']
                for keyword in special_edition_keywords:
                    if keyword in title_norm:
                        score -= 5
                
                # BONUS for exact match (title contains only artist + album words)
                # MUST have found at least some album words to qualify for this bonus
                if album_match_count > 0:
                    title_words = set(title_norm.split())
                    search_words = set(artist_norm.split() + album_norm.split())
                    extra_words = title_words - search_words
                    # Filter out common words
                    extra_words = {w for w in extra_words if len(w) > 2 and w not in ['the', 'and', 'or', 'de', 'la', 'el']}
                    
                    if len(extra_words) == 0:
                        score += 10
                    elif len(extra_words) <= 2:
                        score += 3
                
                # Find price in this product
                price_elem = product.find('strong')
                if not price_elem:
                    continue
                
                price_text = price_elem.get_text(strip=True)
                price_match = re.search(r'(\d+)[.,](\d+)\s*€?', price_text)
                
                # Availability
                full_text = product.get_text(separator=' ', strip=True).lower()
                availability = "Disponible"
                if "consultar disponibilidad" in full_text:
                    availability = "Consultar disponibilidad"
                
                if price_match and score > best_score:
                    best_score = score
                    price_val = float(f"{price_match.group(1)}.{price_match.group(2)}")
                    best_match = {
                        "price": price_val,
                        "url": product_url,
                        "availability": availability
                    }
                    log_event("pricing-service", "INFO", f"Bajo el Volcán match: '{title}' (score: {score}, price: €{price_val}, status: {availability})")
            
            if best_match and best_score > 0:
                log_event("pricing-service", "INFO", f"Found Bajo el Volcán price: €{best_match['price']} (match score: {best_score})")
                return best_match
            
            log_event("pricing-service", "INFO", f"No matching product found on Bajo el Volcán for: {artist} - {album}")
            return None
            
        except Exception as e:
            log_event("pricing-service", "WARNING", f"Bajo el Volcán scraping failed: {str(e)}")
            return None

    async def scrape_bora_bora_price(self, artist: str, album: str) -> Optional[float]:
        """Scrape price from Bora Bora with two-step process: search + detail page."""
        # Clean query: replace / with space to avoid URL issues
        clean_query = f"{artist} {album}".replace("/", " ").replace("  ", " ")
        query = clean_query.replace(" ", "+")
        
        search_url = f"https://discosborabora.com/?s={query}"
        
        try:
            log_event("pricing-service", "INFO", f"Scraping Bora Bora for: {artist} - {album}")
            
            # Step 1: Search for the product (using default headers from http_client)
            response = await self.http_client.get(search_url, timeout=10.0, follow_redirects=True)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Normalize search terms for matching
            artist_norm = normalize(artist)
            album_norm = normalize(album)
            
            # Find all product links in search results
            # Bora Bora uses article.post-entry for products
            products = soup.find_all('article', class_=re.compile(r'post-entry', re.I))
            
            log_event("pricing-service", "INFO", f"Bora Bora: Found {len(products)} article elements")
            
            if not products:
                # Debug: try to find ANY article elements
                all_articles = soup.find_all('article')
                log_event("pricing-service", "WARNING", f"No products found in Bora Bora search results. Total articles: {len(all_articles)}")
                if all_articles:
                    first_classes = ' '.join(all_articles[0].get('class', []))
                    log_event("pricing-service", "INFO", f"First article classes: {first_classes[:100]}")
                return None
            
            best_match_url = None
            best_score = -999
            
            for product in products:
                # Find product title in h2.post-title
                title_elem = product.find('h2', class_=re.compile(r'post-title|entry-title', re.I))
                if not title_elem:
                    continue
                
                # Get the link inside the h2
                link_elem = title_elem.find('a', href=True)
                if not link_elem:
                    continue
                
                product_url = link_elem.get('href')
                if not product_url or not product_url.startswith('http'):
                    continue
                
                title = link_elem.get_text(strip=True)
                title_norm = normalize(title)
                
                # Calculate match score
                score = 0
                artist_words = artist_norm.split()
                album_words = album_norm.split()
                
                # Check if artist name appears in title
                if any(word in title_norm for word in artist_words if len(word) > 2):
                    score += 3
                
                # Check if album name appears in title
                album_match_count = sum(1 for word in album_words if len(word) > 2 and word in title_norm)
                score += album_match_count * 2
                
                # PENALTY for special editions
                special_edition_keywords = ['deluxe', 'remaster', 'remastered', 'reissue', 'anniversary', 
                                           'edition', 'limited', 'expanded', 'collectors', 'box', 'set']
                for keyword in special_edition_keywords:
                    if keyword in title_norm:
                        score -= 5
                
                # BONUS for exact match
                title_words = set(title_norm.split())
                search_words = set(artist_norm.split() + album_norm.split())
                extra_words = title_words - search_words
                extra_words = {w for w in extra_words if len(w) > 2 and w not in ['the', 'and', 'or', 'de', 'la', 'el']}
                if len(extra_words) == 0:
                    score += 10
                elif len(extra_words) <= 2:
                    score += 3
                
                if score > best_score:
                    best_score = score
                    best_match_url = product_url
                    log_event("pricing-service", "INFO", f"Bora Bora match: '{title}' (score: {score}, url: {product_url})")
            
            if not best_match_url or best_score <= 0:
                log_event("pricing-service", "INFO", f"No matching product found on Bora Bora for: {artist} - {album}")
                return None
            
            # Step 2: Fetch the detail page to get the price
            log_event("pricing-service", "INFO", f"Fetching Bora Bora detail page: {best_match_url}")
            detail_response = await self.http_client.get(best_match_url, timeout=10.0)
            detail_response.raise_for_status()
            
            detail_soup = BeautifulSoup(detail_response.text, 'lxml')
            
            # Find price on detail page - try multiple selectors
            price_elem = detail_soup.find(class_=re.compile(r'price|precio|amount', re.I))
            
            if not price_elem:
                # Try finding price in meta tags
                price_meta = detail_soup.find('meta', property='product:price:amount')
                if price_meta:
                    price_text = price_meta.get('content', '')
                else:
                    # Last resort: search for price pattern in text
                    price_elem = detail_soup.find(string=re.compile(r'\d+[.,]\d+\s*€'))
                    price_text = str(price_elem) if price_elem else ""
            else:
                price_text = price_elem.get_text(strip=True)
            
            price_match = re.search(r'(\d+)[.,](\d+)\s*€?', price_text)
            
            if price_match:
                price = float(f"{price_match.group(1)}.{price_match.group(2)}")
                log_event("pricing-service", "INFO", f"Found Bora Bora price: €{price}")
                return price
            
            log_event("pricing-service", "WARNING", f"Price not found on Bora Bora detail page: {best_match_url}")
            return None
            
        except Exception as e:
            log_event("pricing-service", "WARNING", f"Bora Bora scraping failed: {str(e)}")
            return None

    async def scrape_fnac_price(self, artist: str, album: str) -> Optional[tuple]:
        """
        Scrape price from FNAC using Google Custom Search + ScrapingBot Retail API.
        
        Returns:
            tuple: (price, product_url) or None if not found
        

        Strategy:
        1. Use Google Custom Search to find FNAC product URL (bypasses CAPTCHA)
        2. Use ScrapingBot Retail API to extract price from product page
        """
        # Get API keys from environment
        scrapingbot_key = os.getenv("SCRAPINGBOT_API_KEY")
        google_api_key = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
        google_cx = os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")
        
        if not scrapingbot_key:
            log_event("pricing-service", "WARNING", "SCRAPINGBOT_API_KEY not configured")
            return None
        
        if not google_api_key or not google_cx:
            log_event("pricing-service", "WARNING", "Google Custom Search not configured - FNAC scraper disabled")
            return None
        
        try:
            log_event("pricing-service", "INFO", f"Searching FNAC for: {artist} - {album}")
            
            # Step 1: Use Google Custom Search to find FNAC product URL
            from googleapiclient.discovery import build
            
            search_query = f'site:fnac.es "{artist}" "{album} - vinilo"'
            log_event("pricing-service", "INFO", f"Google search: {search_query}")
            
            try:
                service = build("customsearch", "v1", developerKey=google_api_key)
                result = service.cse().list(
                    q=search_query,
                    cx=google_cx,
                    num=3  # Get top 3 results
                ).execute()
                
                if 'items' not in result or len(result['items']) == 0:
                    log_event("pricing-service", "INFO", f"No FNAC results found for: {artist} - {album}")
                    return None
                
                # Find first valid product URL that matches the album in title
                product_url = None
                artist_lower = normalize(artist)
                album_lower = normalize(album)
                
                for item in result['items']:
                    url = item.get('link', '')
                    title = normalize(item.get('title', ''))
                    snippet = normalize(item.get('snippet', ''))
                    
                    # Log potential matches for debugging
                    log_event("pricing-service", "DEBUG", f"Analyzing result: {title} | {url}")
                    
                    # Must contain album name in title to be valid
                    # (Avoids picking "Tangk" when searching "Brutalism")
                    if album_lower not in title:
                        continue
                        
                    # Must contain "vinilo" or "lp" to ensure it's not a CD
                    # (Google sometimes returns CDs even with "vinilo" in query if fuzzy matched)
                    if "vinilo" not in title and "lp" not in title:
                        log_event("pricing-service", "DEBUG", f"Skipping non-vinyl result: {title}")
                        continue

                    # FNAC product URLs contain /a followed by numbers OR /mp (marketplace)
                    # Example: https://www.fnac.es/a10657375/Idles-Brutalism-Vinilo
                    if ('/a' in url or '/mp' in url) and 'fnac.es' in url:
                        product_url = url
                        break
                
                if not product_url:
                    log_event("pricing-service", "INFO", f"No matching FNAC product URL found in search results")
                    return None
                
                log_event("pricing-service", "INFO", f"Found FNAC URL: {product_url}")
                
            except Exception as e:
                log_event("pricing-service", "WARNING", f"Google search failed: {str(e)}")
                return None
            
            # Step 2: Use ScrapingBot Retail API to extract price
            retail_url = "http://api.scraping-bot.io/scrape/retail"
            auth = ("Vinilogy", scrapingbot_key)
            
            payload = {
                "url": product_url,
                "options": {
                    "useChrome": False,
                    "premiumProxy": True,  # Use premium for reliability
                    "proxyCountry": "ES",
                    "waitForNetworkRequests": False
                }
            }
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            
            response = await self.http_client.post(
                retail_url,
                json=payload,
                headers=headers,
                auth=auth,
                timeout=60.0
            )
            response.raise_for_status()
            
            result = response.json()
            
            if result.get("error"):
                log_event("pricing-service", "WARNING", f"ScrapingBot error: {result['error']}")
                return None
            
            data = result.get("data", {})
            price = data.get("price")
            title = data.get("title", "")
            
            if price is None:
                log_event("pricing-service", "INFO", f"No price found in FNAC product data")
                return None
            
            # Verify product regex match again just in case (already did header match)
            
            # Convert to float
            try:
                price_float = float(price)
                log_event("pricing-service", "INFO", f"Found FNAC price: €{price_float:.2f} for '{title}'")
                return (price_float, product_url)
            except (ValueError, TypeError):
                log_event("pricing-service", "WARNING", f"Invalid price format: {price}")
                return None
            
        except Exception as e:
            log_event("pricing-service", "WARNING", f"FNAC scraping failed: {str(e)}")
            return None

    async def get_local_store_links_with_prices(
        self, 
        artist: str, 
        album: str,
        exclude_fnac: bool = False,
        only_fnac: bool = False
    ) -> dict:
        """
        Obtiene enlaces y precios de tiendas locales mediante scraping en paralelo.
        """
        query = f"{artist} {album}"
        
        # Prepare tasks based on flags
        tasks = []
        task_names = []
        
        # If specific filters are set, only run relevant scrapers
        run_standard = not only_fnac
        run_fnac = not exclude_fnac
        
        if run_standard:
            tasks.append(self.scrape_marilians_price(artist, album))
            task_names.append("marilians")
            
            tasks.append(self.scrape_bajo_el_volcan_price(artist, album))
            task_names.append("bajo_volcan")
            
            tasks.append(self.scrape_bora_bora_price(artist, album))
            task_names.append("bora_bora")
        
        # FNAC task (potentially slow/blocking)
        # if run_fnac:
        #     tasks.append(self.scrape_fnac_price(artist, album))
        #     task_names.append("fnac")
        
        if not tasks:
            return {}
            
        # Run selected tasks in parallel
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        stores = {}
        
        # Helper to get result by name
        def get_result(name):
            if name in task_names:
                idx = task_names.index(name)
                res = results[idx]
                if isinstance(res, Exception):
                    log_event("pricing-service", "WARNING", f"{name} scraping failed: {str(res)}")
                    return None
                return res
            return None
            
        # Standard stores results
        if run_standard:
            marilians_price = get_result("marilians")
            bajo_volcan_price = get_result("bajo_volcan")
            bora_bora_price = get_result("bora_bora")
            
            if marilians_price is not None:
                stores["marilians"] = {
                    "url": f"https://www.marilians.com/busqueda?controller=search&s={query}",
                    "price": marilians_price
                }
            
            if bajo_volcan_price is not None:
                # Now bajo_volcan_price is a tuple/dict? No, it used to be float
                # We updated it to dict.
                stores["bajo_el_volcan"] = {
                    "url": bajo_volcan_price.get("url", ""),
                    "price": bajo_volcan_price.get("price", 0.0),
                    "availability": bajo_volcan_price.get("availability", "Disponible")
                }
            
            if bora_bora_price is not None:
                stores["bora_bora"] = {
                    "url": f"https://discosborabora.com/?s={query}",
                    "price": bora_bora_price
                }
                
            # Always include Revolver (no scraping) if standard run
            stores["revolver"] = {
                "url": f"https://www.revolverrecords.es/?s={query}&post_type=product",
                "price": None
            }
            
        # FNAC results
        # if run_fnac:
        #     fnac_result = get_result("fnac")
        #     # Handle tuple (price, url) from FNAC
        #     fnac_price = None
        #     fnac_url = None
            
        #     if isinstance(fnac_result, tuple):
        #         fnac_price = fnac_result[0]
        #         fnac_url = fnac_result[1]
        #     elif isinstance(fnac_result, float):
        #         fnac_price = fnac_result
        #         # Fallback URL if old return format
        #         fnac_url = f"https://www.fnac.es/SearchResult/ResultList.aspx?Search={query}"
                
        #     if fnac_price is not None and fnac_url is not None:
        #         stores["fnac"] = {
        #             "url": fnac_url,
        #             "price": fnac_price
        #         }
        
        return stores

    def get_local_store_links(self, artist: str, album: str) -> dict:
        """Devuelve enlaces preparados para tiendas locales sin scraping (legacy method)."""
        query = f"{artist} {album}".replace(" ", "+")

        return {
            "marilians": (
                f"https://www.marilians.com/busqueda?"
                f"controller=search&s={query}"
            ),
            "bajo_el_volcan": (
                "https://www.bajoelvolcan.es/busqueda/listaLibros.php?"
                f"tipoBus=full&palabrasBusqueda={query}"
            ),
            "bora_bora": f"https://discosborabora.com/?s={query}",
            "fnac": f"https://www.fnac.es/SearchResult/ResultList.aspx?Search={query}&sft=1&sa=0",
            "revolver": (
                f"https://www.revolverrecords.es/?s={query}&post_type=product"
            ),
        }
