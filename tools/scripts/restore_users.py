import sqlite3
import datetime

DB_PATH = "vinylbe.db"

def restore_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Restoring users...")
    
    # Users data recovered from previous query
    users_to_restore = [
        (1, 'test@example.com', 'Test User', '2025-11-23 00:34:27', None),
        (2, None, 'lf_user', '2025-11-23 00:34:27', None),
        (3, 'test_user_1763885753@example.com', 'Test User', '2025-11-23 08:15:53', None),
        (4, None, 'user_1763885753', '2025-11-23 08:15:53', None),
        (5, 'test_user_1763885777@example.com', 'Test User', '2025-11-23 08:16:17', '2025-11-23 08:16:17'),
        (6, None, 'user_1763885777', '2025-11-23 08:16:17', '2025-11-23 08:16:17'),
        (7, 'user@example.com', 'Demo User', '2025-11-23 08:24:55', None),
        (8, None, 'aficcion@gmail.com', '2025-11-23 08:26:28', '2025-11-23 08:56:43'),
        # Adding user 10 found in auth_identity but missing in previous list
        (10, None, 'aficcion', '2025-11-23 11:19:46', None) 
    ]
    
    restored_count = 0
    for user in users_to_restore:
        try:
            # Check if user exists
            cursor.execute("SELECT id FROM user WHERE id = ?", (user[0],))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO user (id, email, display_name, created_at, last_login_at)
                    VALUES (?, ?, ?, ?, ?)
                """, user)
                restored_count += 1
                print(f"Restored user: {user[2]} (ID: {user[0]})")
            else:
                print(f"User already exists: {user[2]} (ID: {user[0]})")
        except Exception as e:
            print(f"Error restoring user {user[0]}: {e}")
            
    conn.commit()
    conn.close()
    print(f"\nTotal users restored: {restored_count}")

if __name__ == "__main__":
    restore_users()
