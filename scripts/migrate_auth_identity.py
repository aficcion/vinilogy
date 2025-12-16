import sqlite3
import os
import sys

# Add parent directory to path to import db module if needed, 
# but for this script we can just use the path directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from gateway.db import DB_PATH

def migrate_auth_identity():
    print(f"Migrating database at {DB_PATH}")
    if not os.path.exists(DB_PATH):
        print("Database not found. Skipping migration.")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    try:
        # Check if we need to migrate
        # We can try to insert a dummy discogs row in a transaction and see if it fails
        # But easier to just check the schema SQL
        cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='auth_identity'")
        row = cur.fetchone()
        if not row:
            print("Table auth_identity does not exist yet. Init DB will handle it.")
            return
            
        create_sql = row[0]
        if "'discogs'" in create_sql:
            print("Table auth_identity already supports 'discogs'.")
            return

        print("Migrating auth_identity to support 'discogs'...")
        
        # 1. Rename old table
        cur.execute("ALTER TABLE auth_identity RENAME TO auth_identity_old")
        
        # 2. Create new table with updated CHECK constraint
        cur.execute("""
            CREATE TABLE auth_identity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL CHECK (provider IN ('google', 'lastfm', 'discogs')),
                provider_user_id TEXT NOT NULL,
                access_token TEXT,
                refresh_token TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (provider, provider_user_id),
                FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
            )
        """)
        
        # 3. Copy data
        cur.execute("""
            INSERT INTO auth_identity (id, user_id, provider, provider_user_id, access_token, refresh_token, created_at)
            SELECT id, user_id, provider, provider_user_id, access_token, refresh_token, created_at
            FROM auth_identity_old
        """)
        
        # 4. Drop old table
        cur.execute("DROP TABLE auth_identity_old")
        
        conn.commit()
        print("Migration successful: auth_identity table updated.")
        
        # Also run init_db to create the new tables (user_settings, etc) if they don't exist
        # We import here to avoid circular dependencies or early execution
        from gateway.db import init_db
        init_db()
        print("Verified all other tables.")
        
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {e}")
        # Restore if needed (if we renamed but didn't finish)
        # In a transaction, rollback should cover it.
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_auth_identity()
