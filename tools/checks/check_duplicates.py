#!/usr/bin/env python3
"""
Script to check for and remove duplicate entries in user_selected_artist table.
"""
import sqlite3
import os

DB_PATH = "vinylbe.db"

def check_and_fix_duplicates():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("🔍 Checking for duplicates in user_selected_artist...")
        
        # Find duplicates
        cursor.execute("""
            SELECT user_id, artist_name, COUNT(*) as count
            FROM user_selected_artist
            GROUP BY user_id, artist_name
            HAVING count > 1
        """)
        
        duplicates = cursor.fetchall()
        
        if not duplicates:
            print("✅ No duplicates found.")
            return

        print(f"⚠️  Found {len(duplicates)} sets of duplicates:")
        for user_id, artist_name, count in duplicates:
            print(f"   - User {user_id}: '{artist_name}' ({count} copies)")
            
        response = input("\nDo you want to remove duplicates? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("❌ Operation cancelled.")
            return

        print("\n🧹 Removing duplicates...")
        
        # Delete duplicates, keeping the one with the lowest ID (oldest)
        cursor.execute("""
            DELETE FROM user_selected_artist
            WHERE id NOT IN (
                SELECT MIN(id)
                FROM user_selected_artist
                GROUP BY user_id, artist_name
            )
        """)
        
        deleted_count = cursor.rowcount
        conn.commit()
        print(f"✅ Removed {deleted_count} duplicate records.")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    check_and_fix_duplicates()
