import requests
import json

RECOMMENDER_URL = "http://localhost:3002"

def verify_endpoint():
    print(f"Calling {RECOMMENDER_URL}/collection-recommendations...")
    # Use 'aficcion' as found in restore_users.py
    payload = {"username": "aficcion", "limit": 3}
    
    try:
        resp = requests.post(f"{RECOMMENDER_URL}/collection-recommendations", json=payload)
        resp.raise_for_status()
        data = resp.json()
        
        print("\n✅ Success! Response:")
        print(json.dumps(data, indent=2))
        
        recs = data.get("recommendations", [])
        if not recs:
            print("\n⚠️ No recommendations found. Check if the user has a collection or if services are connected properly.")
        else:
            print(f"\nFound {len(recs)} recommendations.")
            for rec in recs:
                source = rec.get("source")
                print(f"- {rec['album_name']} by {rec['artist_name']} ({source})")
                if source == "collection_upgrade":
                    print(f"  Current Formats: {rec.get('current_formats')}")
                elif source == "discography_completion":
                    print(f"  Votes: {rec.get('votes')}")
                    
    except Exception as e:
        print(f"\n❌ Failed: {e}")
        if hasattr(e, 'response') and e.response:
             print(f"Response: {e.response.text}")

if __name__ == "__main__":
    verify_endpoint()
