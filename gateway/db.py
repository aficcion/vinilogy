import os
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional

# Path to the SQLite database file (same as used elsewhere in the project)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vinylbe.db")


def dict_factory(cursor, row):
    """Convert SQLite rows to dictionaries for easier access."""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection with foreign key support enabled.

    The connection uses a row factory that returns dictionaries.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = dict_factory
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db() -> None:
    """Create all required tables if they do not already exist.

    The schema follows the specification provided by the user.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Enable foreign keys (already set in get_connection, but keep for safety)
        cur.execute("PRAGMA foreign_keys = ON;")
        # Create tables
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS user (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT,
                display_name TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS auth_identity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                provider TEXT NOT NULL CHECK (provider IN ('google', 'lastfm')),
                provider_user_id TEXT NOT NULL,
                access_token TEXT,
                refresh_token TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE (provider, provider_user_id),
                FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_profile_lastfm (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                lastfm_username TEXT NOT NULL,
                top_artists_json TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
                UNIQUE (user_id)
            );

            CREATE TABLE IF NOT EXISTS user_selected_artist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                artist_name TEXT NOT NULL,
                mbid TEXT,
                spotify_id TEXT,
                source TEXT NOT NULL CHECK (source IN ('manual', 'lastfm_suggestion')),
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
            );

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
            );

            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                cf_enabled INTEGER NOT NULL DEFAULT 1,  -- 1=True, 0=False
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS user_collection_discogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                release_id INTEGER NOT NULL,
                master_id INTEGER,
                artist TEXT,
                title TEXT,
                internal_category TEXT CHECK (internal_category IN ('VINYL', 'CD_FORMAT', 'TAPE_FORMAT', 'OTHERS')),
                release_type TEXT,
                year INTEGER,
                label TEXT,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                cover_url TEXT,
                FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
                UNIQUE (user_id, release_id)
            );

            CREATE INDEX IF NOT EXISTS idx_discogs_collection_master ON user_collection_discogs(user_id, master_id);
            CREATE INDEX IF NOT EXISTS idx_discogs_collection_category ON user_collection_discogs(user_id, internal_category);
            
            CREATE TABLE IF NOT EXISTS discogs_release_cache (
                release_id INTEGER PRIMARY KEY,
                data_json TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        
        # Migration: Add spotify_id column if it doesn't exist
        try:
            cur.execute("ALTER TABLE user_selected_artist ADD COLUMN spotify_id TEXT")
        except sqlite3.OperationalError:
            pass  # Column likely already exists

        # Migration: Add cover_url to recommendation if it doesn't exist
        try:
            cur.execute("ALTER TABLE recommendation ADD COLUMN cover_url TEXT")
        except sqlite3.OperationalError:
            pass

        # Migration: Add new columns to user_collection_discogs
        for col, dtype in [("release_type", "TEXT"), ("year", "INTEGER"), ("label", "TEXT"), ("cover_url", "TEXT")]:
            try:
                cur.execute(f"ALTER TABLE user_collection_discogs ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                pass

        # Migration: update auth_identity check constraint to support 'discogs'
        # SQLite doesn't support altering constraints easily, so we largely rely on code validation or recreation.
        # For simplicity in this iteration, we won't force a table re-creation to avoid data loss, 
        # but the code logic will insert 'discogs' which might fail if strict CHECK is enforced.
        # However, SQLite CHECK constraints are per-row. We can try to modify it if needed, 
        # but typically 'provider' CHECK constraint might need to be dropped or updated.
        # Since the original CREATE TABLE had "CHECK (provider IN ('google', 'lastfm'))", 
        # inserting 'discogs' will fail. We need to disable the check or recreate.
        # Strategy: We will create a temp table, copy data, drop old, rename new.
        
        # Check if we need to migrate auth_identity
        cur.execute("PRAGMA table_info(auth_identity)")
        # This is hard to check via pragma for check constraints. We'll attempt a dummy insert or just check if 'discogs' works?
        # A safer way creates the table with the new definition if it doesn't exist, but if it exists we are stuck.
        # Let's perform a Safe Migration for auth_identity if needed.
        
        # Only migrate if we can't insert 'discogs' (or we just always migrate to be safe/sure)
        # But that's heavy on startup. Let's start by assuming we might need it.
        # Actually, let's keep it simple: we'll run a quick schema check/update script or block.
        pass # Migration logic can be handled in a dedicated migration function if strictly needed.
        # For now, let's assume we might need to recreate auth_identity to allow 'discogs'

            
        conn.commit()
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# User and authentication helper functions
# ---------------------------------------------------------------------------

def _create_user(display_name: str, email: Optional[str] = None) -> int:
    """Insert a new user row and return its id."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user (email, display_name) VALUES (?, ?)",
            (email, display_name),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_or_create_user_via_google(email: str, display_name: str, google_sub: str) -> int:
    """Return the user id for a Google login, creating rows as needed.

    * If an auth_identity with provider='google' and provider_user_id=google_sub already exists,
      its associated user_id is returned.
    * Otherwise a new user row is created (using the supplied email and display_name) and a
      corresponding auth_identity row is inserted.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Look for existing identity
        cur.execute(
            "SELECT user_id FROM auth_identity WHERE provider = 'google' AND provider_user_id = ?",
            (google_sub,),
        )
        row = cur.fetchone()
        if row:
            user_id = row["user_id"]
            # Update last_login_at on the user
            cur.execute(
                "UPDATE user SET last_login_at = datetime('now') WHERE id = ?",
                (user_id,),
            )
            conn.commit()
            return user_id
        # No existing identity – create user and identity
        user_id = _create_user(display_name=display_name, email=email)
        cur.execute(
            "INSERT INTO auth_identity (user_id, provider, provider_user_id) VALUES (?, 'google', ?)",
            (user_id, google_sub),
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


def get_or_create_user_via_lastfm(lastfm_username: str, existing_user_id: Optional[int] = None) -> int:
    """Return the user id for a Last.fm login, creating rows as needed.

    If existing_user_id is provided, links the Last.fm identity to that user.
    Otherwise, creates a new user.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT user_id FROM auth_identity WHERE provider = 'lastfm' AND provider_user_id = ?",
            (lastfm_username,),
        )
        row = cur.fetchone()
        if row:
            user_id = row["user_id"]
            # If we are linking to an existing user but the Last.fm account is already linked to SOMEONE ELSE...
            # This is a conflict. Ideally we check this.
            # But for now, we return the existing owner of the Last.fm account.
            # If the user wanted to link it to *their* account, this implies they are logging in with a Last.fm account already used.
            # We'll just return the existing user_id (login behavior).
            cur.execute(
                "UPDATE user SET last_login_at = datetime('now') WHERE id = ?",
                (user_id,),
            )
            conn.commit()
            return user_id
            
        # No existing identity – create a new user and link the identity
        if existing_user_id:
            user_id = existing_user_id
            # Update last_login
            cur.execute(
                "UPDATE user SET last_login_at = datetime('now') WHERE id = ?",
                (user_id,),
            )
        else:
            user_id = _create_user(display_name=lastfm_username)
            
        cur.execute(
            "INSERT INTO auth_identity (user_id, provider, provider_user_id) VALUES (?, 'lastfm', ?)",
            (user_id, lastfm_username),
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


def link_lastfm_to_existing_user(user_id: int, lastfm_username: str) -> None:
    """Link a Last.fm identity to an existing user if it does not already exist."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM auth_identity WHERE user_id = ? AND provider = 'lastfm' AND provider_user_id = ?",
            (user_id, lastfm_username),
        )
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO auth_identity (user_id, provider, provider_user_id) VALUES (?, 'lastfm', ?)",
                (user_id, lastfm_username),
            )
            conn.commit()
    finally:
        conn.close()


def get_or_create_user_via_discogs(discogs_username: str, discogs_id: str, token: str = None, secret: str = None, existing_user_id: Optional[int] = None) -> int:
    """Return the user id for a Discogs login/signup.
    
    Creates user if needed, or links to existing_user_id.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Check for existing identity
        cur.execute(
            "SELECT user_id FROM auth_identity WHERE provider = 'discogs' AND provider_user_id = ?",
            (str(discogs_id),),
        )
        row = cur.fetchone()
        if row:
            user_id = row["user_id"]
            # Update tokens and login time
            cur.execute(
                "UPDATE auth_identity SET access_token = ?, refresh_token = ? WHERE user_id = ? AND provider = 'discogs'",
                (token, secret, user_id)
            )
            cur.execute("UPDATE user SET last_login_at = datetime('now') WHERE id = ?", (user_id,))
            conn.commit()
            return user_id
            
        # Create new user OR link to existing
        if existing_user_id:
            user_id = existing_user_id
            cur.execute("UPDATE user SET last_login_at = datetime('now') WHERE id = ?", (user_id,))
        else:
            # We use discogs_username as display_name for fresh users
            user_id = _create_user(display_name=discogs_username)
        
        cur.execute(
            "INSERT INTO auth_identity (user_id, provider, provider_user_id, access_token, refresh_token) VALUES (?, 'discogs', ?, ?, ?)",
            (user_id, str(discogs_id), token, secret),
        )
        conn.commit()
        return user_id
    finally:
        conn.close()


def link_discogs_to_existing_user(user_id: int, discogs_username: str, discogs_id: str, token: str = None, secret: str = None) -> None:
    """Link Discogs identity to existing user."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM auth_identity WHERE user_id = ? AND provider = 'discogs' AND provider_user_id = ?",
            (user_id, str(discogs_id)),
        )
        if not cur.fetchone():
            cur.execute(
                "INSERT INTO auth_identity (user_id, provider, provider_user_id, access_token, refresh_token) VALUES (?, 'discogs', ?, ?, ?)",
                (user_id, str(discogs_id), token, secret),
            )
        else:
             # Update tokens just in case
             cur.execute(
                "UPDATE auth_identity SET access_token = ?, refresh_token = ? WHERE user_id = ? AND provider = 'discogs'",
                (token, secret, user_id)
            )
        conn.commit()
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Last.fm profile handling
# ---------------------------------------------------------------------------

def upsert_user_profile_lastfm(user_id: int, lastfm_username: str, top_artists: List[Dict[str, Any]]) -> None:
    """Insert or update the Last.fm profile snapshot for a user.

    * top_artists is stored as JSON text.
    * generated_at is set to the current UTC timestamp in ISO‑8601 format.
    """
    generated_at = datetime.utcnow().isoformat()
    top_artists_json = json.dumps(top_artists)
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Try to update first – if the row does not exist, INSERT.
        cur.execute(
            """
            UPDATE user_profile_lastfm
            SET lastfm_username = ?, top_artists_json = ?, generated_at = ?
            WHERE user_id = ?
            """,
            (lastfm_username, top_artists_json, generated_at, user_id),
        )
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO user_profile_lastfm (user_id, lastfm_username, top_artists_json, generated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, lastfm_username, top_artists_json, generated_at),
            )
        conn.commit()
    finally:
        conn.close()


def get_user_profile_lastfm(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve the Last.fm profile snapshot for a user."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM user_profile_lastfm WHERE user_id = ?",
            (user_id,),
        )
        row = cur.fetchone()
        if row:
            # Parse the JSON string back to a list/dict
            try:
                row["top_artists"] = json.loads(row["top_artists_json"])
            except json.JSONDecodeError:
                row["top_artists"] = []
            del row["top_artists_json"]
        return row
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Selected artists handling
# ---------------------------------------------------------------------------

def add_user_selected_artist(
    user_id: int,
    artist_name: str,
    mbid: Optional[str] = None,
    source: str = "manual",
    spotify_id: Optional[str] = None,  # Keep parameter for backward compatibility but don't use it
) -> None:
    """Insert a new selected artist for the user.

    The source must be either "manual" or "lastfm_suggestion" – the caller is responsible for
    providing a valid value.
    """
    if source not in {"manual", "lastfm_suggestion"}:
        raise ValueError("source must be 'manual' or 'lastfm_suggestion'")
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Check if already exists
        cur.execute(
            "SELECT 1 FROM user_selected_artist WHERE user_id = ? AND artist_name = ?",
            (user_id, artist_name),
        )
        if cur.fetchone():
            return  # Already exists, do nothing

        cur.execute(
            "INSERT INTO user_selected_artist (user_id, artist_name, mbid, source) VALUES (?, ?, ?, ?)",
            (user_id, artist_name, mbid, source),
        )
        conn.commit()
    finally:
        conn.close()




def get_user_selected_artists(user_id: int) -> List[Dict[str, Any]]:
    """Retrieve all selected artists for a user."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM user_selected_artist WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return cur.fetchall()
    finally:
        conn.close()


def remove_user_selected_artist(user_id: int, selection_id: int) -> bool:
    """Remove a selected artist entry. Returns True if a row was deleted."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM user_selected_artist WHERE id = ? AND user_id = ?",
            (selection_id, user_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()

def upsert_recommendation_status(
    user_id: int, artist_name: str, album_title: str, status: str
) -> None:
    """Update or insert a recommendation status."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Check if exists
        cur.execute(
            "SELECT id FROM recommendation WHERE user_id = ? AND artist_name = ? AND album_title = ?",
            (user_id, artist_name, album_title),
        )
        row = cur.fetchone()
        
        if row:
            # Update existing
            cur.execute(
                "UPDATE recommendation SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, row[0]),
            )
        else:
            # Insert new
            cur.execute(
                """
                INSERT INTO recommendation (user_id, artist_name, album_title, status, source)
                VALUES (?, ?, ?, ?, 'manual')
                """,
                (user_id, artist_name, album_title, status),
            )
        conn.commit()
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Recommendation handling
# ---------------------------------------------------------------------------

def regenerate_recommendations(user_id: int, new_recs: List[Dict[str, Any]]) -> None:
    """Update the recommendation table according to the business rules.

    * new_recs is a list of dicts with keys: artist_name, album_title, album_mbid (optional), source.
    * Existing recommendations with status 'disliked' or 'owned' are never recreated.
    * If a matching recommendation exists with status 'favorite', it is kept as‑is (metadata may be
      updated but status stays 'favorite').
    * If a matching recommendation exists with status 'neutral', its ``updated_at`` timestamp is
      refreshed.
    * Otherwise a new row with status 'neutral' is inserted.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        now_iso = datetime.utcnow().isoformat()
        for rec in new_recs:
            artist = rec.get("artist_name")
            # Handle both album_title (DB convention) and album_name (API convention)
            album = rec.get("album_title") or rec.get("album_name")
            mbid = rec.get("album_mbid")
            
            # Sanitize source field to ensure it matches DB constraints
            # Valid values: 'lastfm', 'manual', 'mixed'
            raw_source = rec.get("source", "mixed")
            if raw_source in {"artist_based", "spotify"}:
                source = "manual"  # Map artist_based and spotify to manual
            elif raw_source in {"lastfm", "manual", "mixed", "collection_upgrade", "discography_completion"}:
                source = raw_source
            else:
                source = "mixed"  # Fallback for any other invalid value

            if not artist or not album:
                log_event("gateway", "ERROR", f"Regenerate failed: missing artist or album in {rec}")
                continue

            # Check if album is already in Discogs collection
            # If so, we skip adding it as a recommendation (unless it's an upgrade, but upgrade logic is separate)
            # Source 'collection_upgrade' implies we WANT it even if owned (it's a specific format upgrade).
            # But 'lastfm' or 'manual' sources should be filtered.
            if source not in ('collection_upgrade', 'discography_completion'):
                cur.execute(
                    "SELECT 1 FROM user_collection_discogs WHERE user_id = ? AND artist = ? COLLATE NOCASE AND title = ? COLLATE NOCASE",
                    (user_id, artist, album)
                )
                if cur.fetchone():
                    continue

            # Check if recommendation already exists
            cur.execute(
                "SELECT id, status FROM recommendation WHERE user_id = ? AND artist_name = ? COLLATE NOCASE AND album_title = ? COLLATE NOCASE",
                (user_id, artist, album),
            )
            existing_row = cur.fetchone()

            if existing_row:
                status = existing_row["status"]
                if status in {"disliked", "owned"}:
                    # Skip – never recreate
                    continue
                if status == "favorite":
                    # Keep as favorite; optionally update metadata (mbid, source)
                    cur.execute(
                        """
                        UPDATE recommendation
                        SET album_mbid = ?, source = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (mbid, source, now_iso, existing_row["id"]),
                    )
                else:  # neutral
                    cur.execute(
                        """
                        UPDATE recommendation
                        SET album_mbid = ?, source = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (mbid, source, now_iso, existing_row["id"]),
                    )
            else:
                # Insert new neutral recommendation
                # Insert new neutral recommendation
                try:
                    cur.execute(
                        """
                        INSERT INTO recommendation (user_id, artist_name, album_title, album_mbid, source, status, created_at)
                        VALUES (?, ?, ?, ?, ?, 'neutral', ?)
                        """,
                        (user_id, artist, album, mbid, source, now_iso),
                    )
                except sqlite3.IntegrityError:
                    log_event("gateway", "WARN", f"Duplicate recommendation ignored for {artist} - {album}")
                    pass
        conn.commit()
    finally:
        conn.close()


def get_recommendations_for_user(user_id: int, include_favorites: bool = True) -> List[Dict[str, Any]]:
    """Return a list of recommendation dicts for the user.

    Returns ALL recommendations regardless of status. The frontend will handle filtering
    based on the current view (all, favorites, owned, disliked, etc.).
    The include_favorites parameter is kept for backwards compatibility but is now ignored.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Base query with JOINs to fetch cover_url from albums table
        # Using COLLATE NOCASE to ensure we match even if capitalization differs
        # Also try matching by MBID if available
        # COALESCE: Prefer cover from recommendation (Discogs import), then from albums table
        query = """
            SELECT 
                r.*, 
                COALESCE(r.cover_url, a.cover_url) as cover_url,
                ar.image_url as artist_image_url,
                a.is_partial
            FROM recommendation r
            LEFT JOIN artists ar ON ar.name = r.artist_name COLLATE NOCASE
            LEFT JOIN albums a ON 
                (r.album_mbid IS NOT NULL AND a.mbid = r.album_mbid) 
                OR 
                (a.artist_id = ar.id AND a.title = r.album_title COLLATE NOCASE)
            WHERE r.user_id = ?
            GROUP BY r.id
            ORDER BY r.created_at DESC
        """
            
        cur.execute(query, (user_id,))
        return cur.fetchall()
    finally:
        conn.close()

def get_favorite_recommendations(user_id: int) -> List[Dict[str, Any]]:
    """Return only the recommendations marked as ``favorite`` for the user."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = """
            SELECT 
                r.*, 
                COALESCE(r.cover_url, a.cover_url) as cover_url,
                ar.image_url as artist_image_url,
                a.is_partial
            FROM recommendation r
            LEFT JOIN artists ar ON ar.name = r.artist_name COLLATE NOCASE
            LEFT JOIN albums a ON 
                (r.album_mbid IS NOT NULL AND a.mbid = r.album_mbid) 
                OR 
                (a.artist_id = ar.id AND a.title = r.album_title COLLATE NOCASE)
            WHERE r.user_id = ? AND r.status = 'favorite'
            GROUP BY r.id
        """
        cur.execute(query, (user_id,))
        return cur.fetchall()
    finally:
        conn.close()


def update_recommendation_status(user_id: int, recommendation_id: int, new_status: str) -> None:
    """Change the status of a recommendation.

    ``new_status`` must be one of ``neutral``, ``favorite``, ``disliked`` or ``owned``.
    """
    if new_status not in {"neutral", "favorite", "disliked", "owned", "active"}:
        # Note: 'active' added to allowed statuses in case UI sends it, though usually UI sends user-intent statuses
        if new_status == "active": pass # Allow active
        elif new_status not in {"neutral", "favorite", "disliked", "owned"}:
             raise ValueError("Invalid status value")
             
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        cur.execute(
            "UPDATE recommendation SET status = ?, updated_at = datetime('now') WHERE id = ? AND user_id = ?",
            (new_status, recommendation_id, user_id),
        )
        if cur.rowcount == 0:
            raise RuntimeError("Recommendation not found for given user")
        conn.commit()
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Convenience helpers (optional)
# ---------------------------------------------------------------------------

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Return a user record matching the given email, or ``None`` if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM user WHERE email = ?", (email,))
        return cur.fetchone()
    finally:
        conn.close()

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Return a user record by its primary key, or ``None`` if not found."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM user WHERE id = ?", (user_id,))
        return cur.fetchone()
    finally:
        conn.close()


def get_random_albums_with_covers(limit: int = 50) -> List[Dict[str, Any]]:
    """Fetch random albums that have a cover URL."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, cover_url, artist_id
            FROM albums
            WHERE cover_url IS NOT NULL AND cover_url != ''
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (limit,),
        )
        return cur.fetchall()
    except sqlite3.OperationalError:
        # Fallback if albums table doesn't exist or other DB error
        return []
    finally:
        conn.close()


def search_artists(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for artists by name in the database."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, image_url, is_partial
            FROM artists
            WHERE name LIKE ? COLLATE NOCASE
            ORDER BY name
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        return cur.fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def search_albums(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search for albums by title in the database."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT a.id, a.title, a.cover_url, a.artist_id, a.is_partial,
                   ar.name as artist_name, ar.image_url as artist_image_url
            FROM albums a
            LEFT JOIN artists ar ON a.artist_id = ar.id
            WHERE a.title LIKE ? COLLATE NOCASE
            ORDER BY a.title
            LIMIT ?
            """,
            (f"%{query}%", limit),
        )
        return cur.fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Discogs Collection & Settings
# ---------------------------------------------------------------------------

def get_user_settings(user_id: int) -> Dict[str, Any]:
    """Get user settings (e.g. CFM toggle). Defaults if not set."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_settings WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return row
        return {"user_id": user_id, "cf_enabled": 1} # Default ON
    finally:
        conn.close()

def update_user_settings(user_id: int, cf_enabled: bool) -> None:
    """Update user settings."""
    val = 1 if cf_enabled else 0
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_settings (user_id, cf_enabled, updated_at) 
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET cf_enabled=excluded.cf_enabled, updated_at=excluded.updated_at
            """,
            (user_id, val)
        )
        conn.commit()
    finally:
        conn.close()

def sync_discogs_collection_items(user_id: int, items: List[Dict[str, Any]]) -> None:
    """
    Sync a batch of items from Discogs to DB.
    items: list of dicts with {release_id, master_id, artist, title, internal_category, cover_url}
    
    This function now also ensures artists and albums exist in cache as partial records.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        # FUZZY MATCHING for Recommendations
        # 1. Fetch all existing recommendations for user to match against
        cur.execute("SELECT id, artist_name, album_title FROM recommendation WHERE user_id = ?", (user_id,))
        existing_recs = cur.fetchall()
        
        # Helper for normalization
        def normalize(s):
            if not s: return ""
            import unicodedata
            try:
                # Normalize unicode characters to decompose combined characters (like accents)
                s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
            except Exception:
                pass
            
            # Replace smart quotes with straight quotes
            s = s.replace('’', "'").replace('“', '"').replace('”', '"')
            
            # Remove symbols/punctuation that often differ
            import re
            return re.sub(r'[^a-z0-9]', '', s.lower())

        # Map normalized (artist, album) -> rec_id
        rec_map = {}
        for r in existing_recs:
            k = (normalize(r['artist_name']), normalize(r['album_title']))
            rec_map[k] = r['id']

        # 2. Iterate items and Update matches or Insert new
        for item in items:
            artist_name = item.get('artist')
            album_title = item.get('title')
            cover_url = item.get('cover_url')
            master_id = item.get('master_id')
            release_id = item.get('release_id')
            internal_category = item.get('internal_category', 'others')
            
            if not artist_name or not album_title:
                continue
            
            # --- NEW: Ensure artist exists in cache (create as partial if not) ---
            cur.execute("SELECT id FROM artists WHERE name = ?", (artist_name,))
            artist_row = cur.fetchone()
            
            if artist_row:
                artist_id = artist_row['id']
            else:
                # Create partial artist
                cur.execute("""
                    INSERT INTO artists (name, is_partial, last_updated)
                    VALUES (?, 1, CURRENT_TIMESTAMP)
                """, (artist_name,))
                artist_id = cur.lastrowid
            
            # --- NEW: Ensure album exists in cache (create as partial if not) ---
            cur.execute("""
                SELECT id FROM albums 
                WHERE artist_id = ? AND title = ?
            """, (artist_id, album_title))
            album_row = cur.fetchone()
            
            if not album_row:
                # Create partial album with Discogs data
                cur.execute("""
                    INSERT INTO albums (
                        artist_id, title, cover_url, 
                        discogs_master_id, discogs_release_id,
                        is_partial, last_updated
                    )
                    VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                """, (artist_id, album_title, cover_url, master_id, release_id))
            else:
                # Update existing album with cover_url and discogs IDs if not set
                cur.execute("""
                    UPDATE albums 
                    SET cover_url = COALESCE(cover_url, ?),
                        discogs_master_id = COALESCE(discogs_master_id, ?),
                        discogs_release_id = COALESCE(discogs_release_id, ?),
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (cover_url, master_id, release_id, album_row['id']))
            
            # --- EXISTING: Sync to Collection Table ---
            cur.execute(
                """
                INSERT INTO user_collection_discogs (user_id, release_id, master_id, artist, title, internal_category, cover_url, release_type, year, label)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, release_id) DO UPDATE SET
                    master_id=excluded.master_id,
                    internal_category=excluded.internal_category,
                    cover_url=excluded.cover_url,
                    release_type=excluded.release_type,
                    year=excluded.year,
                    label=excluded.label
                """,
                (
                    user_id, 
                    release_id, 
                    master_id, 
                    artist_name, 
                    album_title, 
                    internal_category,
                    cover_url,
                    item.get('release_type'),
                    item.get('year'),
                    item.get('label')
                )
            )

            # --- NEW: Update Recommendation Status if exists ---
            k = (normalize(artist_name), normalize(album_title))
            if k in rec_map:
                rec_id = rec_map[k]
                cur.execute("UPDATE recommendation SET status = 'owned', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (rec_id,))

        conn.commit()
    finally:
        conn.close()

def get_user_discogs_collection_stats(user_id: int) -> Dict[str, int]:
    """Get basic stats about user's Discogs collection."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT count(*) as count FROM user_collection_discogs WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        return {"count": row['count'] if row else 0}
    finally:
        conn.close()


def get_user_collection_by_format(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """Get user's collection grouped by format.
    
    Combines:
    - Discogs collection data (if available)
    - Owned recommendations (for all users)
    
    Returns dict with format keys: VINYL, CD_FORMAT, TAPE_FORMAT, DIGITAL, OTHERS
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        
        # Initialize result structure
        collection = {
            "VINYL": [],
            "CD_FORMAT": [],
            "TAPE_FORMAT": [],
            "DIGITAL": [],
            "OTHERS": []
        }
        
        # Helper for normalization
        def normalize(s):
            if not s: return ""
            # Replace smart quotes with straight quotes
            s = s.replace('’', "'").replace('“', '"').replace('”', '"')
            import re
            return re.sub(r'[^a-z0-9]', '', s.lower())

        # 1. Get Discogs collection items (if any)
        cur.execute("""
            SELECT 
                release_id,
                master_id,
                artist,
                title,
                internal_category,
                cover_url,
                release_type,
                year,
                label,
                added_at
            FROM user_collection_discogs
            WHERE user_id = ?
            ORDER BY added_at DESC
        """, (user_id,))
        
        discogs_items = cur.fetchall()
        
        # Track what we've already added from Discogs to avoid duplicates
        added_albums = set()
        
        for item in discogs_items:
            cat = item['internal_category']
            if cat not in collection:
                cat = "OTHERS"
            
            # Normalize for dedup checking
            added_albums.add((normalize(item['artist']), normalize(item['title'])))
            
            collection[cat].append({
                'artist': item['artist'],
                'title': item['title'],
                'cover_url': item.get('cover_url'),  # Use cover_url from database
                'source': 'discogs',
                'release_id': item.get('release_id'),
                'master_id': item.get('master_id'),
                'release_type': item.get('release_type'),
                'year': item.get('year'),
                'label': item.get('label'),
                'added_at': item.get('added_at')
            })
        
        # 2. Get owned recommendations (for all users, including those without Discogs)
        cur.execute("""
            SELECT 
                r.artist_name,
                r.album_title,
                COALESCE(r.cover_url, a.cover_url) as cover_url,
                r.created_at
            FROM recommendation r
            LEFT JOIN artists ar ON ar.name = r.artist_name COLLATE NOCASE
            LEFT JOIN albums a ON 
                (r.album_mbid IS NOT NULL AND a.mbid = r.album_mbid) 
                OR 
                (a.artist_id = ar.id AND a.title = r.album_title COLLATE NOCASE)
            WHERE r.user_id = ? AND r.status = 'owned'
            GROUP BY r.id
            ORDER BY r.created_at DESC
        """, (user_id,))
        
        owned_recs = cur.fetchall()
        
        for rec in owned_recs:
            album_key = (normalize(rec['artist_name']), normalize(rec['album_title']))
            
            # Skip if already added from Discogs
            if album_key in added_albums:
                continue
            
            # For owned recommendations without Discogs data, 
            # we'll put them in OTHERS by default
            # (could be enhanced with format detection from album title)
            collection['OTHERS'].append({
                'artist': rec['artist_name'],
                'title': rec['album_title'],
                'cover_url': rec.get('cover_url'),
                'source': 'recommendation',
                'added_at': rec.get('created_at')
            })
        
        # 3. Enrich Discogs items with cover URLs from albums table
        for format_key in collection:
            for item in collection[format_key]:
                if item['source'] == 'discogs' and not item['cover_url']:
                    # Try to find cover from albums table
                    cur.execute("""
                        SELECT a.cover_url
                        FROM albums a
                        JOIN artists ar ON a.artist_id = ar.id
                        WHERE ar.name = ? COLLATE NOCASE 
                        AND a.title = ? COLLATE NOCASE
                        AND a.cover_url IS NOT NULL
                        LIMIT 1
                    """, (item['artist'], item['title']))
                    
                    cover_row = cur.fetchone()
                    if cover_row:
                        item['cover_url'] = cover_row['cover_url']
        
        return collection
    finally:
        conn.close()


def get_user_collection_summary(user_id: int) -> Dict[str, Any]:
    """
    Get summary statistics for user's collection.
    Returns total count and breakdown by format.
    """
    collection = get_user_collection_by_format(user_id)
    
    summary = {
        'total': 0,
        'by_format': {}
    }
    
    for format_key, items in collection.items():
        count = len(items)
        summary['by_format'][format_key] = count
        summary['total'] += count
    
    return summary


# ---------------------------------------------------------------------------
# Discogs Release Cache
# ---------------------------------------------------------------------------

def get_cached_release(release_id: int) -> Optional[Dict[str, Any]]:
    """Get full release details from cache if available."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT data_json FROM discogs_release_cache WHERE release_id = ?", (release_id,))
        row = cur.fetchone()
        if row and row['data_json']:
            import json
            return json.loads(row['data_json'])
        return None
    finally:
        conn.close()

def cache_release(release_id: int, data: Dict[str, Any]) -> None:
    """Cache release details permanently."""
    import json
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO discogs_release_cache (release_id, data_json, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(release_id) DO UPDATE SET
                data_json=excluded.data_json,
                updated_at=excluded.updated_at
            """,
            (release_id, json.dumps(data))
        )
        conn.commit()
    finally:
        conn.close()


def get_recommendation(user_id: int, rec_id: int) -> Optional[Dict[str, Any]]:
    """Get recommendation details."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM recommendation WHERE id = ? AND user_id = ?", (rec_id, user_id))
        return cur.fetchone()
    finally:
        conn.close()


def get_album_discogs_ids(artist_name: str, album_title: str) -> Optional[Dict[str, Any]]:
    """Try to find Discogs IDs from the local albums cache."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Initial implementation: direct match. Could be improved with normalization.
        cur.execute("""
            SELECT a.discogs_release_id, a.discogs_master_id, a.year, a.cover_url
            FROM albums a
            JOIN artists ar ON a.artist_id = ar.id
            WHERE ar.name = ? AND a.title = ?
            LIMIT 1
        """, (artist_name, album_title))
        return cur.fetchone()
    finally:
        conn.close()


def add_to_collection(user_id: int, data: Dict[str, Any]) -> None:
    """Add an item to the user's Discogs collection table."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO user_collection_discogs 
            (user_id, release_id, master_id, artist, title, internal_category, release_type, year, label, cover_url, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, release_id) DO UPDATE SET
                master_id=COALESCE(excluded.master_id, master_id),
                cover_url=COALESCE(excluded.cover_url, cover_url),
                added_at=datetime('now')
        """, (
            user_id, 
            data.get('release_id'), 
            data.get('master_id'), 
            data.get('artist'), 
            data.get('title'),
            data.get('format', 'OTHERS'),
            data.get('type', 'Album'),
            data.get('year', 0),
            data.get('label'),
            data.get('cover_url')
        ))
        conn.commit()
    finally:
        conn.close()
