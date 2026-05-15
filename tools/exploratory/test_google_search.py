"""
Test Google Custom Search API for FNAC
"""
import os
from dotenv import load_dotenv
from googleapiclient.discovery import build

load_dotenv()

def test_google_search():
    """Test Google Custom Search API"""
    
    api_key = os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
    search_engine_id = os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID")
    
    if not api_key or not search_engine_id:
        print("❌ Error: Missing environment variables")
        print("   GOOGLE_CUSTOM_SEARCH_API_KEY:", "✅" if api_key else "❌")
        print("   GOOGLE_CUSTOM_SEARCH_ENGINE_ID:", "✅" if search_engine_id else "❌")
        print("\nPlease configure these in your .env file")
        return
    
    print("=" * 70)
    print("Testing Google Custom Search API")
    print("=" * 70)
    
    # Test search
    artist = "Radiohead"
    album = "OK Computer"
    query = f'site:fnac.es "{artist}" "{album}" vinilo'
    
    print(f"\n🔍 Search query: {query}")
    
    try:
        # Build the service
        service = build("customsearch", "v1", developerKey=api_key)
        
        # Execute search
        result = service.cse().list(
            q=query,
            cx=search_engine_id,
            num=5  # Get top 5 results
        ).execute()
        
        # Check results
        if 'items' in result:
            print(f"\n✅ Found {len(result['items'])} results")
            
            for i, item in enumerate(result['items'], 1):
                print(f"\n📌 Result {i}:")
                print(f"   Title: {item.get('title', 'N/A')}")
                print(f"   URL: {item.get('link', 'N/A')}")
                
                # Check if it's a product URL
                url = item.get('link', '')
                if '/a' in url and 'fnac.es' in url:
                    print(f"   ✅ This looks like a FNAC product URL!")
            
            print(f"\n🎉 SUCCESS! Google Custom Search is working")
            print(f"💡 First result URL: {result['items'][0]['link']}")
            
        else:
            print("\n⚠️  No results found")
            print("   This might mean:")
            print("   - The album is not on FNAC")
            print("   - Search engine not configured correctly")
            
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        print("\nCommon issues:")
        print("- API key not valid → Check your API key")
        print("- Daily limit exceeded → Wait until tomorrow or enable billing")
        print("- Search engine ID wrong → Check your cx value")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    test_google_search()
