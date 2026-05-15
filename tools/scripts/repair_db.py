import sys
import os

# Add current directory to path so we can import 'gateway'
sys.path.append(os.getcwd())

try:
    from gateway import db
    print("Initializing database...")
    db.init_db()
    print("Database initialized successfully.")
except Exception as e:
    print(f"Error initializing database: {e}")
