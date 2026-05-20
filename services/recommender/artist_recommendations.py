import os
import time
import re
import threading
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
import sqlite3

MB_BASE = "https://musicbrainz.org/ws/2"
DISCOGS_BASE = "https://api.discogs.com"

HEADERS = {
    "User-Agent": "Vinilogy/1.0 (+https://vinilogy.com; contact@vinilogy.com)"
}

_RE_DISCOGS_MASTER = re.compile(
    r"https?://(?:www\.)?discogs\.com/(?:[a-z]{2}/)?master/(\d+)", re.I
)

CLIENT = httpx.Client(
    headers=HEADERS,
    http2=False,
    timeout=httpx.Timeout(30.0),
    limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
    follow_redirects=True,
)

_last_discogs_call_time = 0.0
_MIN_DISCOGS_DELAY = 1.5
_discogs_lock = threading.Lock()

# SQLite database path
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vinylbe.db")


def dict_factory(cursor, row):
    """Convert SQLite row to dictionary"""
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create artists and albums tables if they do not exist."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS artists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            mbid TEXT,
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
        
    # Migration: Add spotify_id column to artists if it doesn't exist
    try:
        cur.execute("ALTER TABLE artists ADD COLUMN spotify_id TEXT UNIQUE")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_artists_spotify_id ON artists(spotify_id)")
    except sqlite3.OperationalError:
        pass  # Column likely already exists

    # Migration: Add spotify_id column to albums if it doesn't exist
    try:
        cur.execute("ALTER TABLE albums ADD COLUMN spotify_id TEXT")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_albums_spotify_id ON albums(spotify_id)")
    except sqlite3.OperationalError:
        pass  # Column likely already exists
        
    conn.commit()


def _get_db_connection():
    """Get SQLite connection"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = dict_factory
        _ensure_schema(conn)
        return conn
    except Exception as e:
        print(f"[DB] Connection failed: {e}")
        return None


def _get_cached_artist_albums(artist_name: str, ignore_expiry: bool = False) -> Optional[List[Dict[str, Any]]]:
    """Get cached artist albums from SQLite
    
    Args:
        artist_name: Name of the artist to search for
        ignore_expiry: Deprecated parameter, kept for compatibility (cache never expires)
    """
    conn = _get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT id, mbid, last_updated FROM artists WHERE LOWER(name) = LOWER(?)",
            (artist_name,)
        )
        artist = cursor.fetchone()
        
        if not artist:
            return None
        
        # Parse last_updated timestamp for logging
        last_updated_str = artist["last_updated"]
        if isinstance(last_updated_str, str):
            last_updated = datetime.fromisoformat(last_updated_str)
        else:
            last_updated = last_updated_str
        
        cache_age = datetime.now() - last_updated
        
        cursor.execute(
            """SELECT title, year, discogs_master_id, discogs_release_id, 
                      rating, votes, cover_url
               FROM albums 
               WHERE artist_id = ? 
               ORDER BY rating DESC, votes DESC""",
            (artist["id"],)
        )
        albums = cursor.fetchall()
        
        if not albums:
            return None

        # Filtrar ediciones especiales también al leer de caché
        EXCLUDE_KEYWORDS = [
            "live", "compilation", "anthology", "best of", "greatest hits",
            "deluxe", "promo", "single", "ep", "directo", "remaster", "remastered",
            "reissue", "anniversary", "edition", "collector", "box set", "oknotok",
            "mnesia", "recordings", "sessions", "demos", "acoustic", "unplugged",
            "radio", "broadcast", "concert", "tour", "pompeii", "mix", "redux",
            "revisited", "revisit", "restored", "re-recorded", "rerecorded",
            "super deluxe", "immersion", "experience", "infinite",
        ]
        import re as _re
        def _is_special(title: str) -> bool:
            t = (title or "").lower()
            if any(kw in t for kw in EXCLUDE_KEYWORDS):
                return True
            # Título que termina en número suelto ≥ 20 → edición aniversario (ej. "50", "40")
            if _re.search(r'\s\d{2,}$', t):
                return True
            return False

        filtered = [dict(a) for a in albums if not _is_special(a["title"])]
        # Si el filtro elimina todo, devolver sin filtrar (mejor algo que nada)
        result = filtered if filtered else [dict(a) for a in albums]

        # Deduplicar por discogs_master_id (mantener el de mayor rating/votes)
        seen_master = {}
        deduped = []
        for a in result:
            mid = a.get("discogs_master_id")
            if mid:
                if mid not in seen_master:
                    seen_master[mid] = a
                    deduped.append(a)
                # else: skip duplicate master
            else:
                deduped.append(a)
        result = deduped

        print(f"[DB] ✓ Found {len(result)}/{len(albums)} cached albums for '{artist_name}' (age: {cache_age.days}d, filtered specials)")
        return result
    
    except Exception as e:
        print(f"[DB] Error reading cache for '{artist_name}': {e}")
        return None
    finally:
        conn.close()


def _save_artist_albums(artist_name: str, mbid: str, albums: List['StudioAlbum'], 
                        image_url: Optional[str] = None):
    """Save artist and albums to SQLite"""
    conn = _get_db_connection()
    if not conn:
        print(f"[DB] Cannot save '{artist_name}' - no database connection")
        return
    
    try:
        cursor = conn.cursor()
        
        # Insert or update artist
        cursor.execute(
            """INSERT INTO artists (name, mbid, image_url, last_updated) 
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET 
                   mbid = excluded.mbid,
                   image_url = excluded.image_url,
                   last_updated = excluded.last_updated""",
            (artist_name, mbid, image_url, datetime.now())
        )
        
        # Get artist_id
        cursor.execute("SELECT id FROM artists WHERE LOWER(name) = LOWER(?)", (artist_name,))
        result = cursor.fetchone()
        if not result:
            return
        artist_id = result["id"]
        
        # Delete old albums
        cursor.execute("DELETE FROM albums WHERE artist_id = ?", (artist_id,))
        
        # Insert new albums
        for album in albums:
            cursor.execute(
                """INSERT INTO albums (artist_id, title, year, discogs_master_id, 
                                      discogs_release_id, rating, votes, cover_url, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (artist_id, album.title, album.year, album.discogs_master_id,
                 album.discogs_release_id, album.rating, album.votes, album.cover_image, datetime.now())
            )
        
        conn.commit()
        print(f"[DB] ✓ Saved {len(albums)} albums for '{artist_name}' to cache")

    except Exception as e:
        conn.rollback()
        print(f"[DB] Error saving '{artist_name}': {e}")
    finally:
        conn.close()


def enrich_ratings_for_artist(artist_name: str, discogs_key: str, discogs_secret: str) -> int:
    """
    Busca ratings en Discogs para los álbumes cacheados de un artista que tienen rating=NULL.
    Devuelve el número de álbumes enriquecidos.
    Diseñado para ejecutarse en background (asyncio.to_thread).
    """
    conn = _get_db_connection()
    if not conn:
        return 0

    enriched = 0
    try:
        cursor = conn.cursor()
        cursor.execute(
            """SELECT al.id, al.discogs_master_id, al.discogs_release_id, al.title
               FROM albums al
               JOIN artists ar ON ar.id = al.artist_id
               WHERE LOWER(ar.name) = LOWER(?)
                 AND al.rating IS NULL
                 AND (al.discogs_master_id IS NOT NULL OR al.discogs_release_id IS NOT NULL)""",
            (artist_name,)
        )
        albums_to_enrich = cursor.fetchall()

        for album in albums_to_enrich:
            master_id = album["discogs_master_id"]
            release_id = album["discogs_release_id"]
            rating, votes, cover = None, None, None

            try:
                if master_id:
                    rating, votes, cover, year = _discogs_master_data(master_id, discogs_key, discogs_secret)
                elif release_id:
                    rating, votes, cover, year = _discogs_release_data(release_id, discogs_key, discogs_secret)
                else:
                    rating, votes, cover, year = None, None, None, None
            except Exception as e:
                print(f"[ENRICH] Error fetching rating for '{album['title']}': {e}")
                continue

            if rating is not None or year is not None:
                cursor.execute(
                    """UPDATE albums
                       SET rating=COALESCE(?, rating),
                           votes=COALESCE(?, votes),
                           cover_url=COALESCE(NULLIF(cover_url,''), ?),
                           year=COALESCE(NULLIF(year,''), ?)
                       WHERE id=?""",
                    (rating, votes, cover, year, album["id"])
                )
                enriched += 1
                print(f"[ENRICH] ✓ {artist_name} — {album['title']}: rating={rating}, year={year}")

        conn.commit()
        print(f"[ENRICH] Done: {enriched}/{len(albums_to_enrich)} albums enriched for '{artist_name}'")
        return enriched

    except Exception as e:
        conn.rollback()
        print(f"[ENRICH] Error: {e}")
        return 0
    finally:
        conn.close()


def purge_special_editions_from_cache() -> int:
    """
    Elimina de la caché SQLite todos los álbumes que son ediciones especiales/live/compilaciones.
    Llamar una vez para limpiar datos sucios acumulados.
    """
    EXCLUDE_KEYWORDS = [
        "live", "compilation", "anthology", "best of", "greatest hits",
        "deluxe", "promo", "single", "ep", "directo", "remaster", "remastered",
        "reissue", "anniversary", "edition", "collector", "box set", "oknotok",
        "mnesia", "recordings", "sessions", "demos", "acoustic", "unplugged",
        "radio", "broadcast", "concert", "tour",
    ]
    conn = _get_db_connection()
    if not conn:
        return 0
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title FROM albums")
        all_albums = cursor.fetchall()
        to_delete = [
            a["id"] for a in all_albums
            if any(kw in (a["title"] or "").lower() for kw in EXCLUDE_KEYWORDS)
        ]
        if to_delete:
            cursor.executemany("DELETE FROM albums WHERE id=?", [(i,) for i in to_delete])
            conn.commit()
        print(f"[PURGE] Eliminated {len(to_delete)}/{len(all_albums)} special edition albums from cache")
        return len(to_delete)
    except Exception as e:
        conn.rollback()
        print(f"[PURGE] Error: {e}")
        return 0
    finally:
        conn.close()


class StudioAlbum:
    def __init__(self, title: str, year: str, discogs_master_id: Optional[str],
                 artist_name: str, rating: Optional[float] = None,
                 votes: Optional[int] = None, cover_image: Optional[str] = None,
                 discogs_release_id: Optional[str] = None, discogs_type: str = "master"):
        self.title = title
        self.year = year
        self.discogs_master_id = discogs_master_id
        self.discogs_release_id = discogs_release_id
        self.discogs_type = discogs_type
        self.artist_name = artist_name
        self.rating = rating
        self.votes = votes
        self.cover_image = cover_image


def _mb_get(path: str, params: Dict[str, Any], tries: int = 5,
            sleep_after_ok: float = 1.0) -> Dict[str, Any]:
    url = f"{MB_BASE}{path}"
    params = {**params, "fmt": "json"}
    last_exc = None
    backoff = 0.6

    for attempt in range(1, tries + 1):
        try:
            r = CLIENT.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError("Transient", request=r.request, response=r)
            r.raise_for_status()
            time.sleep(sleep_after_ok)
            return r.json()
        except Exception as e:
            last_exc = e
            time.sleep(backoff)
            backoff = min(backoff * 1.7, 5.0)

    raise RuntimeError(f"MB failed: {last_exc}")


def _find_artist_mbid(name: str) -> Optional[str]:
    try:
        data = _mb_get("/artist", {"query": f'artist:"{name}"', "limit": 10})
        artists = data.get("artists", []) or []
        if not artists:
            return None
        exact = [a for a in artists if a.get("name", "").lower() == name.lower()]
        chosen = exact[0] if exact else artists[0]
        return chosen.get("id")
    except Exception:
        return None


def _fetch_release_groups(artist_mbid: str, limit: int = 100):
    try:
        data = _mb_get(
            "/release-group",
            {
                "artist": artist_mbid,
                "primary-type": "Album",
                "inc": "artist-credits+url-rels",
                "limit": min(limit, 100),
            }
        )
        return data.get("release-groups", []) or []
    except Exception:
        return []


def _is_studio_album(rg: Dict[str, Any], artist_mbid: str) -> bool:
    if rg.get("primary-type") != "Album":
        return False
    if rg.get("secondary-types"):
        return False
    ac = rg.get("artist-credit") or []
    if len(ac) != 1:
        return False
    return (ac[0].get("artist") or {}).get("id") == artist_mbid


def _year_from_date(item: Dict[str, Any]) -> str:
    d = item.get("first-release-date") or ""
    return d.split("-")[0] if d else ""


def _discogs_master_from_rels(relations: Any) -> str:
    if not relations:
        return ""
    for rel in relations:
        if rel.get("type") == "discogs":
            url = (rel.get("url") or {}).get("resource", "")
            m = _RE_DISCOGS_MASTER.search(url)
            if m:
                return m.group(1)
    return ""


def _get_artist_image_from_discogs(artist_name: str, discogs_key: str, discogs_secret: str, csv_mode: bool = False) -> Optional[str]:
    """Get artist image from Discogs search"""
    try:
        sleep_time = 1.0 if csv_mode else 0.25
        data = _discogs_get("/database/search", {
            "q": artist_name,
            "type": "artist",
            "per_page": 1
        }, discogs_key, discogs_secret, sleep_after_ok=sleep_time)
        results = data.get("results", [])
        if results:
            return results[0].get("cover_image")
    except Exception as e:
        print(f"[ARTIST IMAGE] Could not get image for {artist_name}: {e}")
    return None


def _discogs_get(path: str, params: Dict[str, Any],
                 key: str, secret: str,
                 sleep_after_ok: float = 0.25,
                 tries: int = 5):
    url = f"{DISCOGS_BASE}{path}"
    params = {**params, "key": key, "secret": secret}
    last_exc = None
    backoff = 1.0
    
    for attempt in range(1, tries + 1):
        try:
            r = CLIENT.get(url, params=params)
            if r.status_code == 429:
                if attempt < tries:
                    wait_time = 60.0
                    print(f"[DISCOGS] ⚠️  RATE LIMIT HIT (429) - sleeping {wait_time}s before retry (attempt {attempt}/{tries})")
                    time.sleep(wait_time)
                    continue
            r.raise_for_status()
            time.sleep(sleep_after_ok)
            return r.json()
        except Exception as e:
            last_exc = e
            if attempt < tries:
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 10.0)
    
    raise RuntimeError(f"Discogs API failed after {tries} attempts: {last_exc}")


def _search_discogs_master(artist_name: str, album_title: str, key: str, secret: str, csv_mode: bool = False) -> Optional[str]:
    """Fallback: Search Discogs for master_id by artist + album title"""
    try:
        query = f"{artist_name} {album_title}"
        sleep_time = 1.0 if csv_mode else 0.25
        data = _discogs_get("/database/search", {
            "q": query,
            "type": "master",
            "per_page": 5
        }, key, secret, sleep_after_ok=sleep_time)
        
        results = data.get("results", [])
        if not results:
            return None
        
        for result in results:
            result_title = result.get("title", "").lower()
            if album_title.lower() in result_title:
                return str(result.get("id", ""))
        
        return str(results[0].get("id", "")) if results else None
    except Exception:
        return None


def _search_discogs_release(artist_name: str, album_title: str, key: str, secret: str, csv_mode: bool = False) -> Optional[str]:
    """Second fallback: Search Discogs for release_id by artist + album title"""
    try:
        query = f"{artist_name} {album_title}"
        sleep_time = 1.0 if csv_mode else 0.25
        data = _discogs_get("/database/search", {
            "q": query,
            "type": "release",
            "format": "vinyl",
            "per_page": 5
        }, key, secret, sleep_after_ok=sleep_time)
        
        results = data.get("results", [])
        if not results:
            return None
        
        for result in results:
            result_title = result.get("title", "").lower()
            if album_title.lower() in result_title:
                return str(result.get("id", ""))
        
        return str(results[0].get("id", "")) if results else None
    except Exception:
        return None


def _discogs_release_data(release_id: str, key: str, secret: str, csv_mode: bool = False) -> Tuple[Optional[float], Optional[int], Optional[str], Optional[str]]:
    """Get rating, cover and year from a Discogs release (not master)"""
    if not release_id:
        return None, None, None, None

    try:
        sleep_time = 1.0 if csv_mode else 0.25
        rel = _discogs_get(f"/releases/{release_id}", {}, key, secret, sleep_after_ok=sleep_time)
        rr = (rel.get("community") or {}).get("rating") or {}

        cover_image = None
        rel_images = rel.get("images", [])
        if rel_images and len(rel_images) > 0:
            cover_image = rel_images[0].get("uri")

        year = str(rel.get("year", "") or "").strip() or None

        if rr.get("average") is None:
            print(f"[RATING] Release {release_id}: NO RATING")
            return None, None, cover_image, year

        rating = float(rr["average"])
        votes = int(rr.get("count", 0))
        print(f"[RATING] Release {release_id}: rating={rating}, votes={votes}, year={year}")
        return rating, votes, cover_image, year
    except Exception as e:
        print(f"[RATING] Release {release_id}: ERROR - {str(e)}")
        return None, None, None, None


def _discogs_master_data(master_id: str, key: str, secret: str, csv_mode: bool = False) -> Tuple[Optional[float], Optional[int], Optional[str], Optional[str]]:
    if not master_id:
        return None, None, None, None

    try:
        sleep_time = 1.0 if csv_mode else 0.25
        data = _discogs_get(f"/masters/{master_id}", {}, key, secret, sleep_after_ok=sleep_time)
        r = (data.get("community") or {}).get("rating") or {}

        cover_image = None
        images = data.get("images", [])
        if images and len(images) > 0:
            cover_image = images[0].get("uri")

        year = str(data.get("year", "") or "").strip() or None

        if r.get("average") is not None:
            rating = float(r["average"])
            votes = int(r.get("count", 0))
            print(f"[RATING] Master {master_id}: rating={rating}, votes={votes}, year={year} (from master)")
            return rating, votes, cover_image, year

        main_rel = data.get("main_release")
        if not main_rel:
            print(f"[RATING] Master {master_id}: NO RATING (no master rating, no main_release)")
            return None, None, cover_image, year

        print(f"[RATING] Master {master_id}: No master rating, checking main_release {main_rel}")
        rel = _discogs_get(f"/releases/{main_rel}", {}, key, secret, sleep_after_ok=sleep_time)
        rr = (rel.get("community") or {}).get("rating") or {}

        if not cover_image:
            rel_images = rel.get("images", [])
            if rel_images and len(rel_images) > 0:
                cover_image = rel_images[0].get("uri")

        if not year:
            year = str(rel.get("year", "") or "").strip() or None

        if rr.get("average") is None:
            print(f"[RATING] Master {master_id}: NO RATING (main_release {main_rel} has no rating)")
            return None, None, cover_image, year

        rating = float(rr["average"])
        votes = int(rr.get("count", 0))
        print(f"[RATING] Master {master_id}: rating={rating}, votes={votes}, year={year} (from main_release {main_rel})")
        return rating, votes, cover_image, year
    except Exception as e:
        print(f"[RATING] Master {master_id}: ERROR - {str(e)}")
        return None, None, None, None


def get_artist_studio_albums(artist_name: str, discogs_key: str, discogs_secret: str,
                              top_n: int = 3, csv_mode: bool = False, cache_only: bool = False, 
                              use_mb: bool = True) -> List[StudioAlbum]:
    # When cache_only=True, ignore expiry to prevent unnecessary Discogs searches
    cached_albums = _get_cached_artist_albums(artist_name, ignore_expiry=cache_only)
    if cached_albums:
        result = []
        for album_data in cached_albums[:top_n]:
            discogs_type = "master" if album_data.get("discogs_master_id") else "release"
            album = StudioAlbum(
                title=album_data["title"],
                year=album_data["year"],
                discogs_master_id=album_data.get("discogs_master_id"),
                discogs_release_id=album_data.get("discogs_release_id"),
                discogs_type=discogs_type,
                artist_name=artist_name,
                rating=album_data.get("rating"),
                votes=album_data.get("votes"),
                cover_image=album_data.get("cover_url")
            )
            result.append(album)
        return result
    
    # If cache_only mode and not in cache, return empty list
    if cache_only:
        print(f"[CACHE_ONLY] '{artist_name}' not in cache, skipping MusicBrainz/Discogs lookup")
        return []

    # --- DISCOGS ONLY MODE (Fast, No MB) ---
    if not use_mb:
        print(f"[DISCOGS ONLY] Fetching top vinyls for {artist_name} directly from Discogs...")
        # Use our robust search helper
        results = get_top_albums_from_discogs_search(
            artist_name, discogs_key, discogs_secret, limit=100
        )
        
        studio_albums = []
        for res in results:
            master_id = res.get("discogs_master_id")
            release_id = res.get("discogs_release_id")
            discogs_type = "master" if master_id else "release"
            
            # Use 'score' (have+want) as rating proxy if needed, or None
            # The UI uses rating/votes.
            rating = 5.0 # Dummy high rating for found items
            votes = res.get("score", 0)
            
            album = StudioAlbum(
                title=res["title"],
                year=str(res.get("year", "")),
                discogs_master_id=master_id,
                discogs_release_id=release_id,
                discogs_type=discogs_type,
                artist_name=artist_name,
                rating=rating,
                votes=votes,
                cover_image=res.get("cover_image")
            )
            studio_albums.append(album)
            
        # Save to DB for next time!
        if studio_albums:
            # Use a placeholder MBID since valid MBID is not fetched
            artist_img = studio_albums[0].cover_image if studio_albums else None
            _save_artist_albums(artist_name, f"discogs-{artist_name}", studio_albums, artist_img)
            
        return studio_albums[:top_n]
    
    mbid = _find_artist_mbid(artist_name)
    if not mbid:
        return []

    release_groups = _fetch_release_groups(mbid, limit=100)
    
    studio_albums: List[StudioAlbum] = []
    for rg in release_groups:
        if not _is_studio_album(rg, mbid):
            continue
        
        title = rg.get("title", "")
        year = _year_from_date(rg)
        rels = rg.get("relations", [])
        discogs_master_id = _discogs_master_from_rels(rels)
        
        album = StudioAlbum(
            title=title,
            year=year,
            discogs_master_id=discogs_master_id,
            artist_name=artist_name,
            rating=None,
            votes=None
        )
        studio_albums.append(album)
    
    albums_with_discogs = []
    albums_without_discogs = []
    
    for album in studio_albums:
        if album.discogs_master_id:
            albums_with_discogs.append(album)
        else:
            albums_without_discogs.append(album)
    
    for album in albums_without_discogs:
        master_id = _search_discogs_master(artist_name, album.title, discogs_key, discogs_secret, csv_mode)
        if master_id:
            album.discogs_master_id = master_id
            album.discogs_type = "master"
            albums_with_discogs.append(album)
        else:
            release_id = _search_discogs_release(artist_name, album.title, discogs_key, discogs_secret, csv_mode)
            if release_id:
                album.discogs_release_id = release_id
                album.discogs_type = "release"
                albums_with_discogs.append(album)
    
    def fetch_data(album: StudioAlbum) -> StudioAlbum:
        print(f"[ALBUM] Fetching rating for '{album.title}' ({album.year}) by {album.artist_name}")
        
        if album.discogs_type == "master" and album.discogs_master_id:
            rating, votes, cover_image, year = _discogs_master_data(album.discogs_master_id, discogs_key, discogs_secret, csv_mode)
        elif album.discogs_type == "release" and album.discogs_release_id:
            rating, votes, cover_image, year = _discogs_release_data(album.discogs_release_id, discogs_key, discogs_secret, csv_mode)
        else:
            print(f"[ALBUM] '{album.title}': No Discogs ID available")
            rating, votes, cover_image, year = None, None, None, None

        album.rating = rating
        album.votes = votes
        album.cover_image = cover_image
        if year and not album.year:
            album.year = year
        
        if rating is not None:
            print(f"[ALBUM] ✓ '{album.title}': FINAL rating={rating}, votes={votes}")
        else:
            print(f"[ALBUM] ✗ '{album.title}': NO RATING - will be discarded")
        
        return album
    
    # CSV mode: ultra-conservative (1 worker, slow)
    # Normal mode: fast (5 workers, parallel)
    max_workers = 1 if csv_mode else 5
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_album = {executor.submit(fetch_data, album): album for album in albums_with_discogs}
        for future in as_completed(future_to_album):
            try:
                future.result()
            except Exception:
                pass
    
    rated_albums = [a for a in albums_with_discogs if a.rating is not None]
    discarded_albums = [a for a in albums_with_discogs if a.rating is None]
    rated_albums.sort(key=lambda a: (a.rating or 0, a.votes or 0), reverse=True)
    
    total_found = len(albums_with_discogs)
    with_rating = len(rated_albums)
    without_rating = len(discarded_albums)
    
    if without_rating > 0:
        print(f"[STATS] ⚠️  {artist_name}: {without_rating} albums discarded (no rating from Discogs)")
        for album in discarded_albums:
            print(f"  - '{album.title}' ({album.year})")
    
    if rated_albums and mbid:
        artist_image = _get_artist_image_from_discogs(artist_name, discogs_key, discogs_secret, csv_mode)
        _save_artist_albums(artist_name, mbid, rated_albums, artist_image)
    
    print(f"[DB] ✓ Saved {with_rating} albums for '{artist_name}' to cache (discarded {without_rating})")
    
    return rated_albums[:top_n]


def get_artist_based_recommendations(artist_names: List[str], discogs_key: str,
                                      discogs_secret: str, top_per_artist: int = 3,
                                      progress_callback=None) -> List[Dict[str, Any]]:
    all_albums: List[StudioAlbum] = []
    
    for idx, artist_name in enumerate(artist_names, 1):
        if progress_callback:
            progress_callback(idx, artist_name)
        
        artist_albums = get_artist_studio_albums(artist_name, discogs_key, discogs_secret, top_n=top_per_artist)
        all_albums.extend(artist_albums)
    
    all_albums.sort(key=lambda a: (a.rating or 0, a.votes or 0), reverse=True)
    
    recommendations = []
    for album in all_albums:
        rec = {
            "album_name": album.title,
            "artist_name": album.artist_name,
            "year": album.year,
            "rating": album.rating,
            "votes": album.votes,
            "discogs_master_id": album.discogs_master_id or album.discogs_release_id,
            "discogs_type": album.discogs_type,
            "image_url": album.cover_image or "https://via.placeholder.com/300x300?text=No+Cover",
            "source": "artist_based"
        }
        recommendations.append(rec)
    
    return recommendations


def get_top_albums_from_discogs_search(artist_name: str, key: str, secret: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Search Discogs for Vinyl LPs by the artist, filter, sort by popularity, and return top albums.
    Used as a fallback when local DB has no data.
    """
    print(f"[DISCOGS SEARCH] Searching top vinyls for: {artist_name}")
    
    try:
        # Search for Vinyl Albums/LPs by the artist
        # We fetch more than needed to allow for filtering
        data = _discogs_get("/database/search", {
            "artist": artist_name,
            "format": "Vinyl,LP,Album",
            "type": "release",  # We want releases to get specific vinyl editions
            "per_page": 50      # Fetch enough to filter
        }, key, secret, sleep_after_ok=1.0)
        
        results = data.get("results", [])
        if not results:
            print(f"[DISCOGS SEARCH] No results found for {artist_name}")
            return []
            
        filtered_albums = []
        seen_titles = set()
        
        # Keywords to exclude
        exclude_keywords = ["live", "compilation", "anthology", "best of", "greatest hits", "deluxe", "promo", "single", "ep", "directo"]
        
        for res in results:
            title = res.get("title", "")
            # Title format is usually "Artist - Album"
            if " - " in title:
                album_title = title.split(" - ", 1)[1]
            else:
                album_title = title
                
            album_title_lower = album_title.lower()
            
            # 1. Filter by keywords
            if any(keyword in album_title_lower for keyword in exclude_keywords):
                continue
                
            # 2. Filter by format (double check)
            # 2. Filter by format (double check)
            formats = res.get("format", [])
            format_str = ", ".join(formats).lower()
            if any(x in format_str for x in ["promo", "unofficial", "compilation", "single", "ep", "maxi-single"]):
                continue
                
            # 3. Deduplicate by title (simple normalization)
            norm_title = re.sub(r'[^a-z0-9]', '', album_title_lower)
            if norm_title in seen_titles:
                continue
            
            seen_titles.add(norm_title)
            
            # 4. Calculate score (Have + Want)
            community = res.get("community", {})
            have = int(community.get("have", 0))
            want = int(community.get("want", 0))
            score = have + want
            
            # 5. Get IDs
            discogs_id = res.get("id")
            master_id = res.get("master_id") # Might be present in search results
            
            filtered_albums.append({
                "title": album_title,
                "year": res.get("year", ""),
                "cover_image": res.get("cover_image") or res.get("thumb", ""),
                "discogs_release_id": str(discogs_id) if discogs_id else None,
                "discogs_master_id": str(master_id) if master_id else None,
                "score": score,
                "have": have,
                "want": want,
                "artist_name": artist_name # Keep original search artist name
            })
            
        # Sort by score (popularity)
        filtered_albums.sort(key=lambda x: x["score"], reverse=True)
        
        # Take top N
        top_albums = filtered_albums[:limit]
        
        print(f"[DISCOGS SEARCH] Found {len(filtered_albums)} valid albums, returning top {len(top_albums)}")
        for alb in top_albums:
            print(f"  - {alb['title']} (Score: {alb['score']}, Year: {alb['year']})")
            
        return top_albums
        
    except Exception as e:
        print(f"[DISCOGS SEARCH] Error searching for {artist_name}: {e}")
        return []


def validate_album_with_discogs(artist_name: str, album_title: str, key: str, secret: str) -> Optional[Dict[str, Any]]:
    """
    Search for a specific album in Discogs to validate if it exists as a Vinyl/LP 
    and passes our filters (no singles, live, etc.).
    Returns album data if valid, None otherwise.
    """
    try:
        # Search for specific release title
        data = _discogs_get("/database/search", {
            "artist": artist_name,
            "release_title": album_title,
            "format": "Vinyl,LP,Album",
            "type": "release",
            "per_page": 5  # We only need to find one valid match
        }, key, secret, sleep_after_ok=1.0)
        
        results = data.get("results", [])
        if not results:
            return None
            
        # Keywords to exclude (same as above)
        exclude_keywords = ["live", "compilation", "anthology", "best of", "greatest hits", "deluxe", "promo", "single", "ep", "directo"]
        
        for res in results:
            res_title = res.get("title", "")
            # Title format is usually "Artist - Album"
            if " - " in res_title:
                real_title = res_title.split(" - ", 1)[1]
            else:
                real_title = res_title
                
            title_lower = real_title.lower()
            
            # 1. Filter by keywords
            if any(keyword in title_lower for keyword in exclude_keywords):
                continue
                
            # 2. Filter by format details
            formats = res.get("format", [])
            format_str = ", ".join(formats).lower()
            if "promo" in format_str or "unofficial" in format_str:
                continue
                
            # Found a valid match!
            discogs_id = res.get("id")
            master_id = res.get("master_id")
            
            return {
                "title": real_title, # Use the clean title from Discogs
                "year": res.get("year", ""),
                "cover_image": res.get("cover_image") or res.get("thumb", ""),
                "discogs_release_id": str(discogs_id) if discogs_id else None,
                "discogs_master_id": str(master_id) if master_id else None,
                "artist_name": artist_name
            }
            
        return None
        
    except Exception as e:
        print(f"[DISCOGS VALIDATION] Error validating {artist_name} - {album_title}: {e}")
        return None
