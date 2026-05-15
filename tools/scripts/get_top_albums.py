import sqlite3
import os

DB_PATH = "vinylbe.db"

def get_top_albums():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = """
    SELECT ar.name, al.title, al.rating, al.votes
    FROM albums al
    JOIN artists ar ON al.artist_id = ar.id
    WHERE al.votes > 100
    ORDER BY al.rating DESC
    LIMIT 20;
    """
    
    cursor.execute(query)
    rows = cursor.fetchall()
    
    print(f"{'Artist':<30} | {'Album':<40} | {'Rating':<10} | {'Votes':<10}")
    print("-" * 100)
    for row in rows:
        artist = row[0]
        album = row[1]
        rating = row[2]
        votes = row[3]
        print(f"{artist:<30} | {album:<40} | {rating:<10} | {votes:<10}")
        
    conn.close()

if __name__ == "__main__":
    get_top_albums()
