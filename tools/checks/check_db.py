import sqlite3
import os

DB_PATH = "vinylbe.db"

def check_user(user_id):
    if not os.path.exists(DB_PATH):
        print(f"Database file {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM user WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            print(f"User {user_id} found: {dict(row)}")
        else:
            print(f"User {user_id} NOT found.")
            
        # Also check recommendations for this user
        cur.execute("SELECT count(*) as count FROM recommendation WHERE user_id = ?", (user_id,))
        count = cur.fetchone()['count']
        print(f"User {user_id} has {count} recommendations.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_user(11)
