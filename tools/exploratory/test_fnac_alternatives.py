"""
Try different ScrapingBot options to bypass FNAC CAPTCHA
Testing various combinations
"""
import asyncio
import httpx

USERNAME = "Vinilogy"
API_KEY = "4bdzoKp01ykZUwBpFU4OVQIJ8"

async def test_different_approaches():
    """Test different ScrapingBot configurations"""
    
    search_url = "https://www.fnac.es/SearchResult/ResultList.aspx?SDM=list&Search=radiohead+ok+computer&SFilt=1!206"
    
    # Different configurations to try
    configs = [
        {
            "name": "Premium + Chrome + Wait for Network",
            "options": {
                "useChrome": True,
                "premiumProxy": True,
                "proxyCountry": "ES",
                "waitForNetworkRequests": True  # Wait for async content
            }
        },
        {
            "name": "Premium + No Chrome",
            "options": {
                "useChrome": False,
                "premiumProxy": True,
                "proxyCountry": "ES"
            }
        },
        {
            "name": "Premium + Chrome + Different Country (FR)",
            "options": {
                "useChrome": True,
                "premiumProxy": True,
                "proxyCountry": "FR",  # Try French proxy
            }
        }
    ]
    
    endpoint = "http://api.scraping-bot.io/scrape/raw-html"
    auth = (USERNAME, API_KEY)
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    print("=" * 70)
    print("Testing Different ScrapingBot Configurations for FNAC")
    print("=" * 70)
    
    for config in configs:
        print(f"\n{'='*70}")
        print(f"Testing: {config['name']}")
        print(f"{'='*70}")
        
        payload = {
            "url": search_url,
            "options": config["options"]
        }
        
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                print("⏳ Sending request...")
                
                response = await client.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    auth=auth
                )
                
                print(f"Status: {response.status_code}")
                
                if response.status_code == 200:
                    result = response.json()
                    
                    if result.get("error"):
                        print(f"❌ Error: {result['error']}")
                    else:
                        html = result.get("rawHtml", "")
                        
                        # Check for CAPTCHA
                        if "captcha" in html.lower() or "datadome" in html.lower():
                            print("❌ CAPTCHA detected")
                        else:
                            print(f"✅ Success! HTML length: {len(html):,}")
                            
                            # Quick check for product links
                            if "/a" in html or "/mp" in html:
                                print("✅ Product links found!")
                            else:
                                print("⚠️  No obvious product links")
                else:
                    print(f"❌ HTTP {response.status_code}")
                    
        except Exception as e:
            print(f"❌ Exception: {str(e)}")
        
        await asyncio.sleep(2)  # Wait between requests
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(test_different_approaches())
