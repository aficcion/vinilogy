
from googleapiclient.discovery import build
import os
from dotenv import load_dotenv

load_dotenv()

def test_search():
    api_key = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
    cx = os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")
    
    query = 'site:fnac.es "Arctic Monkeys" "AM" vinilo'
    print(f"Searching: {query}")
    
    service = build("customsearch", "v1", developerKey=api_key)
    result = service.cse().list(q=query, cx=cx, num=5).execute()
    
    if 'items' not in result:
        print("No results")
        return

    for i, item in enumerate(result['items']):
        print(f"\nResult {i+1}:")
        print(f"Title: {item.get('title')}")
        print(f"Link: {item.get('link')}")
        print(f"Snippet: {item.get('snippet')}")

if __name__ == "__main__":
    test_search()
