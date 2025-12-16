import sys
import os
sys.path.append(os.getcwd())
import gateway.db as db

def normalize(s):
    if not s: return ""
    s = s.replace('’', "'").replace('“', '"').replace('”', '"')
    import re
    return re.sub(r'[^a-z0-9]', '', s.lower())

def check():
    user_id = 2
    conn = db.get_connection()
    cur = conn.cursor()
    
    # 1. Get all Discogs items
    cur.execute("SELECT artist, title FROM user_collection_discogs WHERE user_id = ?", (user_id,))
    discogs_items = cur.fetchall()
    
    # Build set of normalized discogs
    added_albums = set()
    for item in discogs_items:
        norm_key = (normalize(item['artist']), normalize(item['title']))
        added_albums.add(norm_key)
        
    # 2. Get all Recs
    cur.execute("SELECT artist_name, album_title FROM recommendation WHERE user_id = ? AND status = 'owned'", (user_id,))
    recs = cur.fetchall()
    
    print(f"Total Discogs: {len(discogs_items)}")
    print(f"Total Recs: {len(recs)}")
    
    mismatches = 0
    for item in recs:
        norm_key = (normalize(item['artist_name']), normalize(item['album_title']))
        if norm_key not in added_albums:
            mismatches += 1
            if mismatches <= 5:
                # Find potentially matching original to compare
                print(f"Mismatch #{mismatches}: Rec='{item['artist_name']} - {item['album_title']}' -> Norm='{norm_key}'")
                # Try to find what it SHOULD have matched in Discogs?
                # Maybe search by partial?
    
    print(f"Total items that failed dedup: {mismatches}")

if __name__ == "__main__":
    check()
