#!/usr/bin/env python3
"""
Script to initialize SQLite database for Vinylbe.
SQLite databases are created automatically when first accessed,
but this script ensures the schema is properly set up.
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "vinylbe.db")


def dict_factory(cursor, row):
    """Convert SQLite row to dictionary"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def create_schema():
    """Create database schema"""
    print(f"Initializing SQLite database at: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    cursor = conn.cursor()
    
    # Create artists table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS artists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            mbid TEXT,
            image_url TEXT,
            last_updated TIMESTAMP
        )
    """)
    print("✓ Artists table created/verified")
    
    # Create albums table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            year TEXT,
            discogs_master_id TEXT,
            discogs_release_id TEXT,
            rating REAL,
            votes INTEGER,
            cover_url TEXT,
            last_updated TIMESTAMP,
            FOREIGN KEY (artist_id) REFERENCES artists(id)
        )
    """)
    print("✓ Albums table created/verified")
    
    # Create indexes for better performance
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_artists_name 
        ON artists(name)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_albums_artist_id 
        ON albums(artist_id)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_albums_title 
        ON albums(title)
    """)
    
    print("✓ Indexes created/verified")
    
    conn.commit()
    conn.close()
    
    print(f"\n✓ Database initialized successfully!")
    print(f"  Location: {DB_PATH}")
    
    # Show database size
    if os.path.exists(DB_PATH):
        size_bytes = os.path.getsize(DB_PATH)
        size_mb = size_bytes / (1024 * 1024)
        print(f"  Size: {size_mb:.2f} MB")


if __name__ == "__main__":
    create_schema()
