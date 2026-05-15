import sqlite3
import os
import sys

# Connect to the actual database
DB_PATH = "vinylbe.db"

if not os.path.exists(DB_PATH):
    print(f"Database not found at {DB_PATH}")
    sys.exit(1)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# User ID 11 had duplicates for 'Idles'
user_id = 11

print(f"Checking recommendations for user {user_id}...")

# This is the query with the fix (GROUP BY r.id)
query = """
    SELECT 
        r.artist_name, 
        r.album_title,
        count(*) as count
    FROM recommendation r
    LEFT JOIN artists ar ON ar.name = r.artist_name COLLATE NOCASE
    LEFT JOIN albums a ON 
        (r.album_mbid IS NOT NULL AND a.mbid = r.album_mbid) 
        OR 
        (a.artist_id = ar.id AND a.title = r.album_title COLLATE NOCASE)
    WHERE r.user_id = ?
    GROUP BY r.id
"""

cursor.execute(query, (user_id,))
rows = cursor.fetchall()

# Check for duplicates in the result set
seen = set()
duplicates = []

for row in rows:
    key = f"{row[0]}::{row[1]}"
    if key in seen:
        duplicates.append(key)
    seen.add(key)

conn.close()

if duplicates:
    print(f"FAIL: Duplicates still found in result set: {duplicates}")
    sys.exit(1)
else:
    print(f"SUCCESS: No duplicates found in result set for user {user_id}.")
    print(f"Total unique recommendations: {len(rows)}")
    sys.exit(0)
