"""
Measure latency of FNAC scraper
"""
import asyncio
import time
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"
GOOGLE_API_KEY = "AIzaSyCp40l6dKPXu_Kv6jyb4ault7_gFh-vUbs"
GOOGLE_CX = "a13aaab813bbe44cf"

async def measure_latency():
    """Measure complete FNAC scraper latency"""
    
    print("=" * 70)
    print("FNAC Scraper Latency Test")
    print("=" * 70)
    
    artist = "Radiohead"
    album = "OK Computer"
    
    # Step 1: Google Search
    print(f"\n🔍 Searching: {artist} - {album}")
    start_search = time.time()
    
    from googleapiclient.discovery import build
    
    search_query = f'site:fnac.es "{artist}" "{album}" vinilo'
    service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
    result = service.cse().list(q=search_query, cx=GOOGLE_CX, num=3).execute()
    
    search_time = time.time() - start_search
    print(f"⏱️  Google Search: {search_time:.2f}s")
    
    # Get first URL
    product_url = None
    for item in result.get('items', []):
        url = item.get('link', '')
        if '/a' in url and 'fnac.es' in url:
            product_url = url
            break
    
    if not product_url:
        print("❌ No URL found")
        return
    
    print(f"📌 URL: {product_url}")
    
    # Step 2: ScrapingBot Retail API
    print(f"\n💰 Fetching price from FNAC...")
    start_scrape = time.time()
    
    endpoint = "http://api.scraping-bot.io/scrape/retail"
    payload = {
        "url": product_url,
        "options": {
            "useChrome": False,
            "premiumProxy": True,
            "proxyCountry": "ES",
            "waitForNetworkRequests": False
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(endpoint, json=payload, headers=headers, auth=auth)
        result = response.json()
    
    scrape_time = time.time() - start_scrape
    print(f"⏱️  ScrapingBot: {scrape_time:.2f}s")
    
    # Total
    total_time = search_time + scrape_time
    
    data = result.get("data", {})
    price = data.get("price")
    
    print(f"\n" + "=" * 70)
    print(f"📊 RESULTS:")
    print(f"   Google Search:  {search_time:.2f}s")
    print(f"   ScrapingBot:    {scrape_time:.2f}s")
    print(f"   ─────────────────────────")
    print(f"   TOTAL:          {total_time:.2f}s")
    print(f"\n   Price found: €{price}")
    print("=" * 70)
    
    # Context
    print(f"\n💡 For comparison:")
    print(f"   - Direct scrapers (Marilians, etc): ~1-3s")
    print(f"   - eBay API: ~2-4s")
    print(f"   - FNAC (Google + ScrapingBot): ~{total_time:.0f}s")

if __name__ == "__main__":
    asyncio.run(measure_latency())
