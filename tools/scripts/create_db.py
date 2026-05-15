import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import sys

def get_env_var(name):
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line.startswith(name + '='):
                    return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return os.environ.get(name)

def create_db():
    db_url = get_env_var('DATABASE_URL')
    if not db_url:
        print("Error: DATABASE_URL not found in .env")
        sys.exit(1)

    # Basic parsing of postgres://user:pass@host:port/dbname
    try:
        # Remove prefix
        if db_url.startswith("postgresql://"):
            url = db_url[13:]
        elif db_url.startswith("postgres://"):
            url = db_url[11:]
        else:
            print("Error: Invalid DATABASE_URL format")
            sys.exit(1)

        # Split user:pass@host...
        if '@' in url:
            creds, location = url.split('@', 1)
            user_pass = creds.split(':')
            user = user_pass[0]
            password = user_pass[1] if len(user_pass) > 1 else ''
        else:
            print("Error: Could not parse credentials from DATABASE_URL")
            sys.exit(1)

        # Split host:port/dbname
        if '/' in location:
            host_port, dbname = location.split('/', 1)
        else:
            host_port = location
            dbname = 'postgres'

        if ':' in host_port:
            host, port = host_port.split(':')
        else:
            host = host_port
            port = '5432'

        print(f"Connecting to postgres at {host}:{port} as {user}...")
        
        # Connect to default 'postgres' db to create new db
        con = psycopg2.connect(
            dbname='postgres',
            user=user,
            password=password,
            host=host,
            port=port
        )
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()
        
        target_db = 'vinylbe'
        
        # Check if exists
        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = '{target_db}'")
        exists = cur.fetchone()
        
        if not exists:
            print(f"Creating database '{target_db}'...")
            cur.execute(f"CREATE DATABASE {target_db}")
            print("Database created successfully!")
        else:
            print(f"Database '{target_db}' already exists.")
            
        cur.close()
        con.close()
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    create_db()
