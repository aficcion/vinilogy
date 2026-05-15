#!/usr/bin/env python3
"""Verify the exact database path and schema being used"""
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from services.recommender import db_utils

# Get the DB path
print(f"DB_PATH from db_utils: {db_utils.DB_PATH}")
print(f"Absolute path: {os.path.abspath(db_utils.DB_PATH)}")
print(f"File exists: {os.path.exists(db_utils.DB_PATH)}")

# Get a connection and check the schema
conn = db_utils.get_db_connection()
cur = conn.cursor()

# Check the albums table schema
cur.execute("PRAGMA table_info(albums)")
columns = cur.fetchall()

print("\nAlbums table columns:")
for col in columns:
    print(f"  {col['name']}: {col['type']}")

# Check if spotify_id exists
spotify_id_exists = any(col['name'] == 'spotify_id' for col in columns)
print(f"\nspotify_id column exists: {spotify_id_exists}")

# Try a direct INSERT to see the exact error
try:
    print("\nAttempting direct INSERT...")
    cur.execute("""
        INSERT INTO albums (artist_id, title, cover_url, mbid, spotify_id, last_updated, is_partial)
        VALUES (1, 'Direct Test Album', 'http://test.com', NULL, 'test_spotify_123', datetime('now'), 1)
    """)
    conn.commit()
    print("✓ Direct INSERT succeeded!")
except Exception as e:
    print(f"✗ Direct INSERT failed: {e}")

conn.close()
