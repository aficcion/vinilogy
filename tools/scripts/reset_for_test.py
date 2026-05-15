import sqlite3

DB_PATH = "vinylbe.db"

# Delete all users and reset
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

try:
    print("🗑️ Deleting all users...")
    cursor.execute("DELETE FROM user")
    cursor.execute("DELETE FROM auth_identity")
    cursor.execute("DELETE FROM user_profile_lastfm")
    cursor.execute("DELETE FROM user_selected_artist")
    cursor.execute("DELETE FROM recommendation")
    cursor.execute("DELETE FROM user_albums")
    conn.commit()
    print("✅ All users deleted")
    
    # Show final count
    cursor.execute("SELECT COUNT(*) FROM user")
    print(f"Users remaining: {cursor.fetchone()[0]}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()
finally:
    conn.close()

print("\n⚠️ IMPORTANT: Clear browser localStorage:")
print("1. Open browser console (F12)")
print("2. Run: localStorage.clear()")
print("3. Reload the page")
print("4. Then try logging in with Last.fm again")
