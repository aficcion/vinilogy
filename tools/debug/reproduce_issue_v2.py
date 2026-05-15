import sqlite3
import os

DB_PATH = "test_repro.db"

if os.path.exists(DB_PATH):
    os.remove(DB_PATH)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Create table
cursor.execute("""
CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT,
    display_name TEXT
);
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS recommendation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    artist_name TEXT NOT NULL,
    album_title TEXT NOT NULL,
    album_mbid TEXT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT,
    UNIQUE (user_id, artist_name, album_title)
);
""")

# Insert user
cursor.execute("INSERT INTO user (display_name) VALUES ('test_user')")
user_id = cursor.lastrowid

# Insert first recommendation
cursor.execute("""
INSERT INTO recommendation (user_id, artist_name, album_title, source, status)
VALUES (?, 'The Beatles', 'Abbey Road', 'manual', 'neutral')
""", (user_id,))
conn.commit()

print("Inserted 'The Beatles' - 'Abbey Road'")

# Try to insert duplicate with different case
artist = "the beatles"
album = "abbey road"

cursor.execute(
    "SELECT id, status FROM recommendation WHERE user_id = ? AND artist_name = ? AND album_title = ?",
    (user_id, artist, album),
)
existing = cursor.fetchone()

if existing:
    print("Found existing recommendation, updating...")
else:
    print("No existing recommendation found, inserting new one...")
    cursor.execute("""
    INSERT INTO recommendation (user_id, artist_name, album_title, source, status)
    VALUES (?, ?, ?, 'manual', 'neutral')
    """, (user_id, artist, album))
    conn.commit()

# Check count
cursor.execute("SELECT count(*) FROM recommendation")
count = cursor.fetchone()[0]

print(f"Total recommendations: {count}")

if count > 1:
    print("FAIL: Duplicates found!")
else:
    print("SUCCESS: No duplicates found.")

conn.close()
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
