#!/usr/bin/env python3
"""Direct test of the create_basic_album_entry function"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Force reload of the module
if 'services.recommender.db_utils' in sys.modules:
    del sys.modules['services.recommender.db_utils']

from services.recommender import db_utils

# Print the actual INSERT statement being used
import inspect
source = inspect.getsource(db_utils.create_basic_album_entry)
print("Current source code of create_basic_album_entry:")
print("=" * 80)
# Find the INSERT statement
for line in source.split('\n'):
    if 'INSERT INTO albums' in line or 'VALUES' in line or 'cur.execute(insert_album' in line:
        print(line)
print("=" * 80)

# Now test it
print("\nTesting create_basic_album_entry...")
result = db_utils.create_basic_album_entry(
    artist_name="Final Test Artist",
    album_name="Final Test Album",
    cover_url="https://example.com/cover.jpg",
    mbid=None,
    spotify_id="final_test_spotify_id",
    artist_spotify_id="final_test_artist_spotify_id"
)

print(f"Result: {result}")

# Check if it was saved
conn = db_utils.get_db_connection()
cur = conn.cursor()
cur.execute("SELECT * FROM artists WHERE name = 'Final Test Artist'")
artist = cur.fetchone()
print(f"\nArtist: {artist}")

if artist:
    cur.execute("SELECT * FROM albums WHERE artist_id = ?", (artist['id'],))
    album = cur.fetchone()
    print(f"Album: {album}")

conn.close()
