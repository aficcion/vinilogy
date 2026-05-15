import sqlite3
import os

DB_PATH = "vinylbe.db"

def list_users():
    if not os.path.exists(DB_PATH):
        print(f"Database file {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM user")
        rows = cur.fetchall()
        
        print(f"Total users found: {len(rows)}")
        for row in rows:
            print(f"User: {dict(row)}")
            
            # Check auth identity
            cur.execute("SELECT * FROM auth_identity WHERE user_id = ?", (row['id'],))
            identities = cur.fetchall()
            for identity in identities:
                print(f"  - Identity: {identity['provider']} ({identity['provider_user_id']})")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    list_users()
