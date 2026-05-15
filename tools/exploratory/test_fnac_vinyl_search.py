"""
Test FNAC search URL with vinyl filter
"""
import asyncio
import httpx
from bs4 import BeautifulSoup

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_fnac_vinyl_search():
    """Test FNAC search with vinyl filter"""
    
    print("=" * 70)
    print("Testing FNAC Vinyl Search URL")
    print("=" * 70)
    
    # User's suggested URL with vinyl filter
    test_url = "https://www.fnac.es/SearchResult/ResultList.aspx?SDM=list&Search=ok+computer+disco+vinilo+radiohead&SFilt=1!206"
    
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    
    payload = {
        "url": test_url,
        "options": {
            "useChrome": True,
            "premiumProxy": True,
            "proxyCountry": "ES"
        }
    }
    
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    auth = (USERNAME, API_KEY)
    
    print(f"\n🔍 URL: {test_url}")
    print(f"📌 Note: Using SDM=list and SFilt=1!206 (vinyl filter)")
    
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            print("\n⏳ Sending request...")
            
            response = await client.post(
                endpoint,
                json=payload,
                headers=headers,
                auth=auth
            )
            
            print(f"\n✅ Response Status: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if result.get("error"):
                    print(f"❌ Error: {result['error']}")
                    return
                
                html_content = result.get("rawHtml", "")
                
                if not html_content:
                    print("❌ No HTML content")
                    return
                
                # Check for CAPTCHA
                if "captcha" in html_content.lower() or "datadome" in html_content.lower():
                    print("❌ CAPTCHA detected in response")
                    print(f"HTML preview: {html_content[:500]}")
                    return
                
                print(f"✅ Success! HTML Length: {len(html_content):,} characters")
                
                # Parse HTML
                soup = BeautifulSoup(html_content, 'lxml')
                
                # Look for product links
                all_links = soup.find_all('a', href=True)
                product_links = []
                
                for link in all_links:
                    href = link.get('href', '')
                    # FNAC product URLs
                    if '/a' in href or '/mp' in href:
                        if href.startswith('/'):
                            href = f"https://www.fnac.es{href}"
                        elif not href.startswith('http'):
                            continue
                        product_links.append(href)
                
                print(f"\n🔗 Found {len(product_links)} product links")
                
                if product_links:
                    print(f"\n📌 First 5 product links:")
                    for i, link in enumerate(product_links[:5], 1):
                        print(f"   {i}. {link}")
                    
                    print(f"\n🎉 SUCCESS! Can extract product URLs from this search format")
                    print(f"✅ This URL format works with ScrapingBot!")
                else:
                    print("\n⚠️  No product links found")
                    # Show some content to debug
                    print(f"\nHTML sample (first 1000 chars):")
                    print(html_content[:1000])
                    
            else:
                print(f"❌ Error: HTTP {response.status_code}")
                print(f"Response: {response.text[:500]}")
                
    except Exception as e:
        print(f"\n❌ Exception: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_fnac_vinyl_search())
