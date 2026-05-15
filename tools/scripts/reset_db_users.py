import sqlite3
import os

DB_PATH = "vinylbe.db"

def reset_users():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    tables_to_clear = [
        "user_albums",
        "user_profile_lastfm",
        "user_selected_artist",
        "user_collection_discogs",
        "user_settings",
        "user_preferences",
        "auth_identity",
        "recommendation", # Often linked to users
        "user" # Delete users last to satisfy foreign keys if any (sqlite defaults usually don't enforce unless enabled, but good practice)
    ]
    
    print("⚠️  WARNING: Deleting ALL user data...")
    
    for table in tables_to_clear:
        try:
            # Check if table exists first
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cursor.fetchone():
                cursor.execute(f"DELETE FROM {table}")
                print(f"✅ Cleared table: {table}")
            else:
                print(f"ℹ️  Table not found (skipping): {table}")
        except Exception as e:
            print(f"❌ Error clearing {table}: {e}")
    
    # Clean up partial data in albums/artists
    try:
        cursor.execute("DELETE FROM albums WHERE is_partial = 1")
        print(f"✅ Cleared {cursor.rowcount} partial albums")
        cursor.execute("DELETE FROM artists WHERE is_partial = 1")
        print(f"✅ Cleared {cursor.rowcount} partial artists")
    except Exception as e:
         print(f"❌ Error clearing partials: {e}")
            
    conn.commit()
    conn.close()
    print("\n✨ Database user data reset complete.")

if __name__ == "__main__":
    reset_users()
