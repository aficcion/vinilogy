#!/usr/bin/env python3
import sqlite3
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

# Import the db_utils from recommender service
from services.recommender import db_utils

# Get a connection using the service's method
conn = db_utils.get_db_connection()
cur = conn.cursor()

# Check the schema
cur.execute("PRAGMA table_info(albums)")
columns = cur.fetchall()

print("Albums table columns:")
for col in columns:
    print(f"  {col}")

# Check if spotify_id exists
spotify_id_exists = any(col['name'] == 'spotify_id' for col in columns)
print(f"\nspotify_id column exists: {spotify_id_exists}")

conn.close()
