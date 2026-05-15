import sqlite3
import os

DB_PATH = "vinylbe.db"

def check_user_data():
    if not os.path.exists(DB_PATH):
        print(f"Database file {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        
        # Get user
        cur.execute("SELECT * FROM user")
        users = cur.fetchall()
        
        print(f"Total users: {len(users)}")
        for user in users:
            user_id = user['id']
            print(f"\nUser ID: {user_id}")
            print(f"  Display name: {user['display_name']}")
            print(f"  Created: {user['created_at']}")
            
            # Check auth identity
            cur.execute("SELECT * FROM auth_identity WHERE user_id = ?", (user_id,))
            identities = cur.fetchall()
            print(f"  Identities: {len(identities)}")
            for identity in identities:
                print(f"    - {identity['provider']}: {identity['provider_user_id']}")
            
            # Check Last.fm profile
            cur.execute("SELECT * FROM user_profile_lastfm WHERE user_id = ?", (user_id,))
            profile = cur.fetchone()
            if profile:
                print(f"  Last.fm profile: {profile['lastfm_username']}")
                print(f"    Generated at: {profile['generated_at']}")
            else:
                print(f"  Last.fm profile: None")
            
            # Check selected artists
            cur.execute("SELECT COUNT(*) as count FROM user_selected_artist WHERE user_id = ?", (user_id,))
            artist_count = cur.fetchone()['count']
            print(f"  Selected artists: {artist_count}")
            
            # Check recommendations
            cur.execute("SELECT COUNT(*) as count FROM recommendation WHERE user_id = ?", (user_id,))
            rec_count = cur.fetchone()['count']
            print(f"  Recommendations: {rec_count}")
            
            if rec_count > 0:
                cur.execute("SELECT status, COUNT(*) as count FROM recommendation WHERE user_id = ? GROUP BY status", (user_id,))
                statuses = cur.fetchall()
                for status in statuses:
                    print(f"    - {status['status']}: {status['count']}")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_user_data()
