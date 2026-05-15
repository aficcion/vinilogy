#!/usr/bin/env python3
import sqlite3
import sys
import os
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import the db_utils from recommender service
from services.recommender import db_utils

# Test the actual create_basic_album_entry function
print("Testing create_basic_album_entry...")
result = db_utils.create_basic_album_entry(
    artist_name="Test Artist",
    album_name="Test Album",
    cover_url="https://example.com/cover.jpg",
    mbid=None,
    spotify_id="test_spotify_id_123",
    artist_spotify_id="test_artist_spotify_id_456"
)

print(f"Result: {result}")

# Check if it was saved
conn = db_utils.get_db_connection()
cur = conn.cursor()
cur.execute("SELECT * FROM artists WHERE name = 'Test Artist'")
artist = cur.fetchone()
print(f"\nArtist: {artist}")

if artist:
    cur.execute("SELECT * FROM albums WHERE artist_id = ?", (artist['id'],))
    album = cur.fetchone()
    print(f"Album: {album}")

conn.close()
