#!/usr/bin/env python3
"""
Interactive SQLite Database Explorer for Vinylbe
Explora tu base de datos de forma interactiva
"""

import sqlite3
import sys
from typing import List, Dict, Any
from datetime import datetime

DB_PATH = "vinylbe.db"

def dict_factory(cursor, row):
    """Convert row to dictionary"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    return conn

def print_table(rows: List[Dict[str, Any]], max_width: int = 50):
    """Pretty print table results"""
    if not rows:
        print("  No results found.")
        return
    
    # Get column names
    columns = list(rows[0].keys())
    
    # Calculate column widths
    widths = {}
    for col in columns:
        widths[col] = min(max(len(col), max(len(str(row.get(col, ''))) for row in rows)), max_width)
    
    # Print header
    header = " | ".join(col.ljust(widths[col]) for col in columns)
    print("  " + header)
    print("  " + "-" * len(header))
    
    # Print rows
    for row in rows:
        line = " | ".join(str(row.get(col, '')).ljust(widths[col])[:widths[col]] for col in columns)
        print("  " + line)
    
    print(f"\n  Total: {len(rows)} rows")

def show_summary():
    """Show database summary"""
    conn = get_connection()
    cursor = conn.cursor()
    
    print("\n" + "="*70)
    print("📊 DATABASE SUMMARY")
    print("="*70)
    
    # Count tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    tables = [row['name'] for row in cursor.fetchall()]
    
    print(f"\n📋 Tables ({len(tables)}):")
    for table in tables:
        cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
        count = cursor.fetchone()['count']
        print(f"  • {table}: {count} rows")
    
    # Show some interesting stats
    print("\n🎵 Content Statistics:")
    
    # Top artists by album count
    cursor.execute("""
        SELECT a.name, COUNT(al.id) as album_count
        FROM artists a
        LEFT JOIN albums al ON a.id = al.artist_id
        GROUP BY a.id
        ORDER BY album_count DESC
        LIMIT 5
    """)
    top_artists = cursor.fetchall()
    print("\n  Top 5 Artists by Album Count:")
    for artist in top_artists:
        print(f"    • {artist['name']}: {artist['album_count']} albums")
    
    # Top rated albums
    cursor.execute("""
        SELECT ar.name as artist, al.title, al.year, al.rating, al.votes
        FROM albums al
        JOIN artists ar ON al.artist_id = ar.id
        WHERE al.rating IS NOT NULL
        ORDER BY al.rating DESC, al.votes DESC
        LIMIT 5
    """)
    top_albums = cursor.fetchall()
    print("\n  Top 5 Rated Albums:")
    for album in top_albums:
        print(f"    • {album['artist']} - {album['title']} ({album['year']}): {album['rating']:.2f}/5 ({album['votes']} votes)")
    
    # User stats
    cursor.execute("SELECT COUNT(*) as count FROM user")
    user_count = cursor.fetchone()['count']
    
    if user_count > 0:
        print(f"\n👥 Users: {user_count}")
        
        cursor.execute("""
            SELECT u.display_name, COUNT(r.id) as rec_count
            FROM user u
            LEFT JOIN recommendation r ON u.id = r.user_id
            GROUP BY u.id
            ORDER BY rec_count DESC
        """)
        user_recs = cursor.fetchall()
        print("\n  Recommendations by User:")
        for user in user_recs:
            name = user['display_name'] or 'Unknown'
            print(f"    • {name}: {user['rec_count']} recommendations")
    
    conn.close()
    print("\n" + "="*70 + "\n")

def search_artists(query: str):
    """Search for artists"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, mbid, 
               (SELECT COUNT(*) FROM albums WHERE artist_id = artists.id) as album_count
        FROM artists
        WHERE name LIKE ?
        ORDER BY name
    """, (f"%{query}%",))
    
    results = cursor.fetchall()
    print(f"\n🔍 Artists matching '{query}':")
    print_table(results)
    
    conn.close()

def search_albums(query: str):
    """Search for albums"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT al.id, ar.name as artist, al.title, al.year, al.rating, al.votes
        FROM albums al
        JOIN artists ar ON al.artist_id = ar.id
        WHERE al.title LIKE ? OR ar.name LIKE ?
        ORDER BY ar.name, al.year
    """, (f"%{query}%", f"%{query}%"))
    
    results = cursor.fetchall()
    print(f"\n🔍 Albums matching '{query}':")
    print_table(results)
    
    conn.close()

def show_artist_albums(artist_name: str):
    """Show all albums for an artist"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT al.title, al.year, al.rating, al.votes, al.discogs_master_id
        FROM albums al
        JOIN artists ar ON al.artist_id = ar.id
        WHERE ar.name LIKE ?
        ORDER BY al.year
    """, (f"%{artist_name}%",))
    
    results = cursor.fetchall()
    print(f"\n📀 Albums by '{artist_name}':")
    print_table(results)
    
    conn.close()

def show_user_recommendations(user_id: int = None):
    """Show recommendations for a user"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if user_id is None:
        cursor.execute("SELECT id, display_name FROM user ORDER BY id")
        users = cursor.fetchall()
        print("\n👥 Available Users:")
        print_table(users)
        return
    
    cursor.execute("""
        SELECT artist_name, album_title, source, status, created_at
        FROM recommendation
        WHERE user_id = ?
        ORDER BY created_at DESC
    """, (user_id,))
    
    results = cursor.fetchall()
    print(f"\n💿 Recommendations for User ID {user_id}:")
    print_table(results)
    
    conn.close()

def run_custom_query(query: str):
    """Run a custom SQL query"""
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(query)
        results = cursor.fetchall()
        print(f"\n📊 Query Results:")
        print_table(results)
    except Exception as e:
        print(f"\n❌ Error: {e}")
    finally:
        conn.close()

def show_menu():
    """Show interactive menu"""
    print("\n" + "="*70)
    print("🎵 VINYLBE DATABASE EXPLORER")
    print("="*70)
    print("\nOptions:")
    print("  1. Show database summary")
    print("  2. Search artists")
    print("  3. Search albums")
    print("  4. Show artist's albums")
    print("  5. Show user recommendations")
    print("  6. Run custom SQL query")
    print("  7. Show tables and schema")
    print("  0. Exit")
    print("\n" + "="*70)

def show_schema():
    """Show database schema"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    schemas = cursor.fetchall()
    
    print("\n" + "="*70)
    print("📋 DATABASE SCHEMA")
    print("="*70)
    
    for schema in schemas:
        print(f"\n{schema['sql']}\n")
    
    conn.close()

def main():
    """Main interactive loop"""
    if len(sys.argv) > 1:
        # Command line mode
        command = sys.argv[1].lower()
        
        if command == "summary":
            show_summary()
        elif command == "schema":
            show_schema()
        elif command == "artist" and len(sys.argv) > 2:
            search_artists(" ".join(sys.argv[2:]))
        elif command == "album" and len(sys.argv) > 2:
            search_albums(" ".join(sys.argv[2:]))
        elif command == "albums" and len(sys.argv) > 2:
            show_artist_albums(" ".join(sys.argv[2:]))
        elif command == "query" and len(sys.argv) > 2:
            run_custom_query(" ".join(sys.argv[2:]))
        else:
            print("Usage:")
            print("  python explore_db.py summary          - Show database summary")
            print("  python explore_db.py schema           - Show database schema")
            print("  python explore_db.py artist <name>    - Search for artists")
            print("  python explore_db.py album <name>     - Search for albums")
            print("  python explore_db.py albums <artist>  - Show artist's albums")
            print("  python explore_db.py query <sql>      - Run custom SQL query")
            print("  python explore_db.py                  - Interactive mode")
        return
    
    # Interactive mode
    while True:
        show_menu()
        choice = input("\nSelect option: ").strip()
        
        if choice == "0":
            print("\n👋 Goodbye!\n")
            break
        elif choice == "1":
            show_summary()
        elif choice == "2":
            query = input("Enter artist name to search: ").strip()
            if query:
                search_artists(query)
        elif choice == "3":
            query = input("Enter album name to search: ").strip()
            if query:
                search_albums(query)
        elif choice == "4":
            artist = input("Enter artist name: ").strip()
            if artist:
                show_artist_albums(artist)
        elif choice == "5":
            show_user_recommendations()
            user_id = input("\nEnter user ID (or press Enter to skip): ").strip()
            if user_id:
                try:
                    show_user_recommendations(int(user_id))
                except ValueError:
                    print("❌ Invalid user ID")
        elif choice == "6":
            print("\nEnter SQL query (or 'cancel' to go back):")
            query = input("> ").strip()
            if query.lower() != 'cancel':
                run_custom_query(query)
        elif choice == "7":
            show_schema()
        else:
            print("\n❌ Invalid option")
        
        input("\nPress Enter to continue...")

if __name__ == "__main__":
    main()
