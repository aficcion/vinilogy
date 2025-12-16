import os
import sqlite3
from datetime import datetime
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from libs.shared.utils import log_event

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vinylbe.db")

def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

def get_db_connection():
    """Get SQLite connection and ensure required tables exist"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    _ensure_schema(conn)
    return conn

def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create artists and albums tables if they do not exist."""
    log_event("recommender-db", "DEBUG", "🔧 _ensure_schema called - checking database schema...")
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS artists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            mbid TEXT,
            image_url TEXT,
            image_url TEXT,
            last_updated TIMESTAMP,
            is_partial INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            year TEXT,
            mbid TEXT,
            discogs_master_id TEXT,
            discogs_release_id TEXT,
            rating REAL,
            votes INTEGER,
            cover_url TEXT,
            last_updated TIMESTAMP,
            is_partial INTEGER DEFAULT 0,
            FOREIGN KEY (artist_id) REFERENCES artists(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS recommendation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            artist_name TEXT NOT NULL,
            album_title TEXT NOT NULL,
            album_mbid TEXT,
            source TEXT NOT NULL CHECK (source IN ('lastfm', 'manual', 'mixed', 'collection_upgrade', 'discography_completion')),
            status TEXT NOT NULL CHECK (status IN ('neutral', 'favorite', 'disliked', 'owned', 'active')),
            cover_url TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
            UNIQUE (user_id, artist_name, album_title)
        )
        """
    )
    
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            focus_artists TEXT, -- JSON string or comma-separated
            strategies TEXT, -- JSON string e.g. ["complete", "upgrade"]
            last_updated TIMESTAMP
        )
        """
    )
    
    # Migration: Add mbid column if it doesn't exist
    try:
        cur.execute("ALTER TABLE albums ADD COLUMN mbid TEXT")
    except sqlite3.OperationalError:
        pass  # Column likely already exists
        
    # Migration: Add is_partial column if it doesn't exist
    try:
        cur.execute("ALTER TABLE albums ADD COLUMN is_partial INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column likely already exists
        
    # Migration: Add is_partial column to artists if it doesn't exist
    try:
        cur.execute("ALTER TABLE artists ADD COLUMN is_partial INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column likely already exists
        # Migration: Add spotify_id column if it doesn't exist
    # Migration: Add spotify_id column to albums if it doesn't exist
    cur.execute("PRAGMA table_info(albums)")
    columns = [col['name'] for col in cur.fetchall()]
    if 'spotify_id' not in columns:
        try:
            log_event("recommender-db", "INFO", "Adding spotify_id column to albums...")
            cur.execute("ALTER TABLE albums ADD COLUMN spotify_id TEXT")
            log_event("recommender-db", "INFO", "✅ Added spotify_id column")
        except sqlite3.OperationalError as e:
            # Don't pass silently if it's not "duplicate column"
            if "duplicate column" not in str(e):
                log_event("recommender-db", "ERROR", f"Failed to add spotify_id: {e}")
    
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_albums_spotify_id ON albums(spotify_id)")
    except Exception as e:
        log_event("recommender-db", "WARNING", f"Error creating index: {e}")
        
    conn.commit()

def get_cached_album(artist_name: str, album_name: str, mbid: str = None, spotify_id: str = None) -> dict:
    """Check if album exists in cache"""
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            
            # 1. Try matching by Spotify ID
            if spotify_id:
                query_spotify = """
                    SELECT 
                        a.id as album_id,
                        a.title,
                        a.year,
                        a.mbid,
                        a.spotify_id,
                        a.discogs_master_id,
                        a.discogs_release_id,
                        a.rating,
                        a.votes,
                        a.cover_url,
                        a.is_partial,
                        ar.name as artist_name
                    FROM albums a
                    JOIN artists ar ON a.artist_id = ar.id
                    WHERE a.spotify_id = ?
                    LIMIT 1
                """
                cur.execute(query_spotify, (spotify_id,))
                result = cur.fetchone()
                if result:
                    log_event("recommender-db", "DEBUG", f"✓ Cache HIT (Spotify ID): {spotify_id}")
                    return result

            # 2. Try matching by MBID
            if mbid:
                query_mbid = """
                    SELECT 
                        a.id as album_id,
                        a.title,
                        a.year,
                        a.mbid,
                        a.spotify_id,
                        a.discogs_master_id,
                        a.discogs_release_id,
                        a.rating,
                        a.votes,
                        a.cover_url,
                        a.is_partial,
                        ar.name as artist_name
                    FROM albums a
                    JOIN artists ar ON a.artist_id = ar.id
                    WHERE a.mbid = ?
                    LIMIT 1
                """
                cur.execute(query_mbid, (mbid,))
                result = cur.fetchone()
                if result:
                    log_event("recommender-db", "DEBUG", f"✓ Cache HIT (MBID): {mbid}")
                    return result

            # 3. Fallback to name matching
            query = """
                SELECT 
                    a.id as album_id,
                    a.title,
                    a.year,
                    a.mbid,
                    a.spotify_id,
                    a.discogs_master_id,
                    a.discogs_release_id,
                    a.rating,
                    a.votes,
                    a.cover_url,
                    a.is_partial,
                    ar.name as artist_name
                FROM albums a
                JOIN artists ar ON a.artist_id = ar.id
                WHERE LOWER(ar.name) = LOWER(?)
                AND LOWER(a.title) = LOWER(?)
                LIMIT 1
            """
            cur.execute(query, (artist_name, album_name))
            result = cur.fetchone()
            
            if result:
                log_event("recommender-db", "DEBUG", f"✓ Cache HIT: {artist_name} - {album_name}")
                return result
            else:
                log_event("recommender-db", "DEBUG", f"○ Cache MISS: {artist_name} - {album_name}")
                return None
        finally:
            conn.close()
    except Exception as e:
        log_event("recommender-db", "ERROR", f"Error fetching album: {str(e)}")
        return None

def create_basic_album_entry(artist_name: str, album_name: str, cover_url: str = None, mbid: str = None, spotify_id: str = None, artist_spotify_id: str = None, discogs_master_id: str = None, discogs_release_id: str = None) -> bool:
    """Create basic artist and album entries"""
    # log_event("recommender-db", "INFO", f"💥💥💥 FUNCTION ENTRY: create_basic_album_entry for {artist_name} - {album_name}")
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            
            # Get actual schema first
            try:
                cur.execute("PRAGMA table_info(albums)")
                columns = {col['name'] for col in cur.fetchall()}
            except:
                columns = set()
            
            artist_id = _get_or_create_artist(cur, artist_name, artist_spotify_id)
            
            # Check existence by Spotify ID, MBID or Name
            existing = None
            
            if spotify_id and "spotify_id" in columns:
                try:
                    cur.execute("SELECT id FROM albums WHERE spotify_id = ?", (spotify_id,))
                    existing = cur.fetchone()
                except sqlite3.OperationalError:
                    log_event("recommender-db", "WARNING", "SELECT by spotify_id failed despite column existing in schema")
                    pass
            
            if not existing and mbid and "mbid" in columns:
                try:
                    cur.execute("SELECT id FROM albums WHERE mbid = ?", (mbid,))
                    existing = cur.fetchone()
                except sqlite3.OperationalError:
                    pass
            
            if not existing:
                # Fetch all albums for this artist to do a normalized comparison in Python
                # SQLite's LIKE is case-insensitive for ASCII but not robust for accents/unicode without extensions
                cur.execute("SELECT id, title FROM albums WHERE artist_id = ?", (artist_id,))
                artist_albums = cur.fetchall()
                
                import unicodedata
                def normalize(s):
                    return ''.join(c for c in unicodedata.normalize('NFD', s)
                                 if unicodedata.category(c) != 'Mn').lower().replace(' ', '')
                
                target_norm = normalize(album_name)
                
                for alb in artist_albums:
                    if normalize(alb['title']) == target_norm:
                        existing = alb
                        log_event("recommender-db", "INFO", f"Found existing album via normalization: '{alb['title']}' matches '{album_name}'")
                        break
            
            if not existing:
                # Fallback to exact match just in case
                cur.execute("SELECT id FROM albums WHERE artist_id = ? AND title = ?", (artist_id, album_name))
                existing = cur.fetchone()

            if existing:
                # Update existing record with new IDs if they are missing
                updates = []
                update_vals = []
                
                if mbid and "mbid" in columns:
                    updates.append("mbid = ?")
                    update_vals.append(mbid)
                if spotify_id and "spotify_id" in columns:
                    updates.append("spotify_id = ?")
                    update_vals.append(spotify_id)
                if discogs_master_id and "discogs_master_id" in columns:
                    updates.append("discogs_master_id = ?")
                    update_vals.append(discogs_master_id)
                if discogs_release_id and "discogs_release_id" in columns:
                    updates.append("discogs_release_id = ?")
                    update_vals.append(discogs_release_id)
                
                if updates:
                    # Simplified update logic - only update if currently NULL to avoid overwriting good data
                    # But for simplicity here we just update. In a real scenario we might check IS NULL.
                    # Given this is "create basic", we assume we are filling in gaps.
                    set_clause = ", ".join(updates)
                    update_vals.append(existing['id'])
                    
                    try:
                        # This is a bit aggressive (overwriting), but acceptable for filling in IDs
                        # Ideally we would do "mbid = COALESCE(mbid, ?)" but SQLite syntax is different
                        # For now, let's just update specific fields if we have them
                        pass 
                        # Actually, let's only update if we have something new.
                        # The previous logic was:
                        # cur.execute("UPDATE albums SET mbid = ? WHERE id = ? AND mbid IS NULL", (mbid, existing['id']))
                        
                        if mbid and "mbid" in columns:
                            cur.execute("UPDATE albums SET mbid = ? WHERE id = ? AND mbid IS NULL", (mbid, existing['id']))
                        if spotify_id and "spotify_id" in columns:
                            cur.execute("UPDATE albums SET spotify_id = ? WHERE id = ? AND spotify_id IS NULL", (spotify_id, existing['id']))
                        if discogs_master_id and "discogs_master_id" in columns:
                            cur.execute("UPDATE albums SET discogs_master_id = ? WHERE id = ? AND discogs_master_id IS NULL", (discogs_master_id, existing['id']))
                        if discogs_release_id and "discogs_release_id" in columns:
                            cur.execute("UPDATE albums SET discogs_release_id = ? WHERE id = ? AND discogs_release_id IS NULL", (discogs_release_id, existing['id']))
                            
                        conn.commit()
                    except sqlite3.OperationalError:
                        log_event("recommender-db", "WARNING", "UPDATE failed despite columns existing in schema")
                        pass
                
                log_event("recommender-db", "DEBUG", f"Album exists: {artist_name} - {album_name}")
                return False
            
            # Dynamic INSERT based on actual schema
            insert_cols = ["artist_id", "title", "cover_url", "last_updated", "is_partial"]
            insert_vals = [artist_id, album_name, cover_url, datetime.now(), 1]
            
            if mbid and "mbid" in columns:
                insert_cols.append("mbid")
                insert_vals.append(mbid)
                
            if spotify_id and "spotify_id" in columns:
                insert_cols.append("spotify_id")
                insert_vals.append(spotify_id)
            
            if discogs_master_id and "discogs_master_id" in columns:
                insert_cols.append("discogs_master_id")
                insert_vals.append(discogs_master_id)
                
            if discogs_release_id and "discogs_release_id" in columns:
                insert_cols.append("discogs_release_id")
                insert_vals.append(discogs_release_id)

            placeholders = ", ".join(["?"] * len(insert_cols))
            col_names = ", ".join(insert_cols)
            
            insert_album = f"INSERT INTO albums ({col_names}) VALUES ({placeholders})"
            
            # print(f"📂 DB_PATH: {os.path.abspath(DB_PATH)}")
            log_event("recommender-db", "DEBUG", f"🚀 Dynamic INSERT SQL: {insert_album}")
            try:
                cur.execute(insert_album, tuple(insert_vals))
                conn.commit()
                log_event("recommender-db", "DEBUG", f"✓ Created album: {artist_name} - {album_name}")
                return True
            except Exception as e:
                # print(f"❌ INSERT FAILED: {e}")
                if "no such column: spotify_id" in str(e):
                    # print("⚠️ Retrying without spotify_id...")
                    log_event("recommender-db", "WARNING", "INSERT failed with spotify_id. Retrying without it.")
                    # Fallback: remove spotify_id and try again
                    if "spotify_id" in insert_cols:
                        idx = insert_cols.index("spotify_id")
                        insert_cols.pop(idx)
                        insert_vals.pop(idx)
                        placeholders = ", ".join(["?"] * len(insert_cols))
                        col_names = ", ".join(insert_cols)
                        insert_album = f"INSERT INTO albums ({col_names}) VALUES ({placeholders})"
                        # print(f"🚀 Fallback INSERT SQL: {insert_album}")
                        try:
                            cur.execute(insert_album, tuple(insert_vals))
                            conn.commit()
                            log_event("recommender-db", "INFO", f"✓ Created album (fallback): {artist_name} - {album_name}")
                            return True
                        except Exception as fallback_error:
                            log_event("recommender-db", "ERROR", f"Fallback INSERT FAILED: {fallback_error}")
                            raise fallback_error
                raise e
            except Exception as insert_error:
                log_event("recommender-db", "ERROR", f"INSERT failed: {insert_error}")
                cur.execute("PRAGMA table_info(albums)")
                schema = cur.fetchall()
                log_event("recommender-db", "ERROR", f"Current schema: {[col['name'] for col in schema]}")
                raise
        finally:
            conn.close()
    except Exception as e:
        log_event("recommender-db", "ERROR", f"Error creating album: {artist_name} - {album_name}: {str(e)}")
        return False

def _get_or_create_artist(cur, artist_name: str, spotify_id: str = None) -> int:
    """Get or create artist (cursor transaction)"""
    
    # Check schema for artists table
    try:
        cur.execute("PRAGMA table_info(artists)")
        columns = {col['name'] for col in cur.fetchall()}
    except:
        columns = set()
    
    # Try by Spotify ID first
    if spotify_id and "spotify_id" in columns:
        try:
            cur.execute("SELECT id FROM artists WHERE spotify_id = ?", (spotify_id,))
            result = cur.fetchone()
            if result:
                return result['id']
        except sqlite3.OperationalError:
            pass
            
    # Try by name
    check_query = "SELECT id FROM artists WHERE LOWER(name) = LOWER(?)"
    cur.execute(check_query, (artist_name,))
    result = cur.fetchone()
    
    if result:
        # Update spotify_id if missing and column exists
        if spotify_id and "spotify_id" in columns:
            try:
                cur.execute("UPDATE artists SET spotify_id = ? WHERE id = ? AND spotify_id IS NULL", (spotify_id, result['id']))
            except sqlite3.OperationalError:
                pass
        return result['id']
    
    # Create new
    try:
        if spotify_id and "spotify_id" in columns:
            try:
                cur.execute(
                    "INSERT INTO artists (name, spotify_id, last_updated, is_partial) VALUES (?, ?, ?, 1)", 
                    (artist_name, spotify_id, datetime.now())
                )
                return cur.lastrowid
            except sqlite3.OperationalError as e:
                if "no such column: spotify_id" in str(e):
                    # Fallback without spotify_id
                    cur.execute(
                        "INSERT INTO artists (name, last_updated, is_partial) VALUES (?, ?, 1)", 
                        (artist_name, datetime.now())
                    )
                    return cur.lastrowid
                raise e
        else:
            # Insert without spotify_id
            cur.execute(
                "INSERT INTO artists (name, last_updated, is_partial) VALUES (?, ?, 1)", 
                (artist_name, datetime.now())
            )
            return cur.lastrowid
            
    except sqlite3.Error:
        # Fallback if insert fails (race condition?)
        cur.execute(check_query, (artist_name,))
        result = cur.fetchone()
        if result:
            return result['id']
        raise


def save_user_preferences(user_id: int, focus_artists: str, strategies: str):
    """Save user preferences (upsert)"""
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO user_preferences (user_id, focus_artists, strategies, last_updated)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    focus_artists=excluded.focus_artists,
                    strategies=excluded.strategies,
                    last_updated=excluded.last_updated
            """, (user_id, focus_artists, strategies, datetime.now()))
            conn.commit()
            log_event("recommender-db", "INFO", f"Saved preferences for user {user_id}")
            return True
        finally:
            conn.close()
    except Exception as e:
        log_event("recommender-db", "ERROR", f"Failed to save preferences: {e}")
        return False

def get_user_preferences(user_id: int):
    """Get user preferences"""
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_preferences WHERE user_id = ?", (user_id,))
            return cur.fetchone()
        finally:
            conn.close()
    except Exception as e:
        log_event("recommender-db", "ERROR", f"Failed to get preferences: {e}")
        return None

def save_recommendations_batch(user_id: int, recs: list):
    """Save generated recommendations to the main recommendation table"""
    if not recs:
        return 0
        
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            
            # Check schema
            cur.execute("PRAGMA table_info(recommendation)")
            cols = {col['name'] for col in cur.fetchall()}
            
            count = 0
            for r in recs:
                artist = r.get("artist_name")
                album = r.get("album_name")
                source = r.get("source")
                cover = r.get("image_url")
                
                # Check for existing recommendation for this album (ignoring source)
                cur.execute(
                    "SELECT id FROM recommendation WHERE user_id = ? AND artist_name = ? AND album_title = ?",
                    (user_id, artist, album)
                )
                existing = cur.fetchone()
                
                if existing:
                    # UPDATE existing record to reflect new source (e.g. upgrade 'manual' -> 'collection_upgrade')
                    cur.execute("""
                        UPDATE recommendation 
                        SET source = ?, cover_url = ?, created_at = ?
                        WHERE id = ?
                    """, (source, cover, datetime.now(), existing['id']))
                else:
                    # INSERT new record
                    cur.execute("""
                        INSERT INTO recommendation (user_id, artist_name, album_title, source, status, created_at, cover_url)
                        VALUES (?, ?, ?, ?, 'active', ?, ?)
                    """, (user_id, artist, album, source, datetime.now(), cover))
                
                count += 1
            
            conn.commit()
            return count

        finally:
            conn.close()
    except Exception as e:
        log_event("recommender-db", "ERROR", f"Failed to save recs batch: {e}")
        return 0

def close_pool():
    """No-op for SQLite"""
    pass
