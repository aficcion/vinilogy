"""Acceso a datos de Vinylbe v2.

Única fuente de datos: `vinology_core` (DSN en env `VINYLBE_DB_DSN`).
La app SOLO LEE — jamás hace DDL contra core.

Todas las queries son parametrizadas (nada de f-strings con input de usuario).
Los cursores devuelven dicts (RealDictCursor).

Contratos del proyecto respetados aquí:
  - Solo works con vinilo (`has_vinyl = true`) salen en búsqueda/discografía.
  - Discografía se ordena por escuchas (`lastfm_playcount DESC NULLS LAST`),
    NUNCA cronológico. El playcount CRUDO no se expone al render (regla de números).
  - Precios: match por `artist_id` + trigram de título (en core `release_id`
    de marketplace_listings es 100% NULL — ver nota en get_prices_for_work).
    Nunca se inventa precio: sin datos → lista vacía.
"""
import os
import atexit
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

DSN = os.environ.get("VINYLBE_DB_DSN", "postgresql://localhost/vinology_core")

# Umbral de frescura de datos de tienda (días). Contrato heredado del proyecto.
STORE_FRESHNESS_MAX_DAYS = int(os.environ.get("VINYLBE_STORE_FRESHNESS_DAYS", "3"))

# Filtro anti-morralla para discografía (contrato del proyecto).
_DISCOGRAPHY_WORK_TYPES = ("studio_album", "ep")

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DSN)
    return _pool


@contextmanager
def _cursor():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@atexit.register
def _close_pool():
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

def search_works(q, limit=20):
    """Works que casan `q`, SOLO con vinilo.

    Combina full-text (search_doc @@ websearch) con trigram sobre el título
    para tolerar typos/parciales. Orden por relevancia FTS y luego popularidad
    (releases_count DESC NULLS LAST). Incluye artista y cover.
    """
    q = (q or "").strip()
    if not q:
        return []
    sql = """
        SELECT w.id,
               w.title,
               w.work_type,
               w.year,
               w.releases_count,
               a.id   AS artist_id,
               a.name AS artist_name,
               vc.preferred_thumb AS cover_thumb,
               vc.preferred_url   AS cover_url,
               ts_rank(w.search_doc, websearch_to_tsquery('simple', %(q)s)) AS fts_rank,
               similarity(lower(immutable_unaccent(w.title)),
                          lower(immutable_unaccent(%(q)s)))                 AS trgm_sim
        FROM works w
        JOIN artists a ON a.id = w.primary_artist_id
        LEFT JOIN v_work_cover vc ON vc.work_id = w.id
        WHERE w.has_vinyl = true
          AND (
              w.search_doc @@ websearch_to_tsquery('simple', %(q)s)
              OR lower(immutable_unaccent(w.title)) %% lower(immutable_unaccent(%(q)s))
          )
        ORDER BY fts_rank DESC,
                 trgm_sim DESC,
                 w.releases_count DESC NULLS LAST
        LIMIT %(limit)s
    """
    with _cursor() as cur:
        cur.execute(sql, {"q": q, "limit": limit})
        return cur.fetchall()


def search_artists(q, limit=20):
    """Artistas por nombre/search_doc, prefiriendo `is_primary`.

    Orden: primary primero, luego relevancia y `listeners DESC NULLS LAST`.
    """
    q = (q or "").strip()
    if not q:
        return []
    sql = """
        SELECT a.id,
               a.name,
               a.kind,
               a.disambiguation,
               a.country,
               a.is_primary,
               a.listeners,
               a.image_url,
               ts_rank(a.search_doc, websearch_to_tsquery('simple', %(q)s)) AS fts_rank,
               similarity(lower(immutable_unaccent(a.name)),
                          lower(immutable_unaccent(%(q)s)))                  AS trgm_sim
        FROM artists a
        WHERE a.search_doc @@ websearch_to_tsquery('simple', %(q)s)
           OR lower(immutable_unaccent(a.name)) %% lower(immutable_unaccent(%(q)s))
        ORDER BY a.is_primary DESC,
                 fts_rank DESC,
                 a.listeners DESC NULLS LAST,
                 trgm_sim DESC
        LIMIT %(limit)s
    """
    with _cursor() as cur:
        cur.execute(sql, {"q": q, "limit": limit})
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Ficha de obra
# ---------------------------------------------------------------------------

def get_work(work_id):
    """Work + artista primario + géneros + estilos + cover. None si no existe."""
    sql = """
        SELECT w.id,
               w.title,
               w.work_type,
               w.year,
               w.notes,
               w.releases_count,
               w.has_vinyl,
               a.id   AS artist_id,
               a.name AS artist_name,
               a.disambiguation AS artist_disambiguation,
               vc.preferred_url   AS cover_url,
               vc.preferred_thumb AS cover_thumb,
               COALESCE(g.genres, ARRAY[]::text[]) AS genres,
               COALESCE(s.styles, ARRAY[]::text[]) AS styles
        FROM works w
        JOIN artists a ON a.id = w.primary_artist_id
        LEFT JOIN v_work_cover vc ON vc.work_id = w.id
        LEFT JOIN LATERAL (
            SELECT array_agg(gn.name ORDER BY gn.name) AS genres
            FROM work_genres wg JOIN genres gn ON gn.id = wg.genre_id
            WHERE wg.work_id = w.id
        ) g ON true
        LEFT JOIN LATERAL (
            SELECT array_agg(st.name ORDER BY st.name) AS styles
            FROM work_styles ws JOIN styles st ON st.id = ws.style_id
            WHERE ws.work_id = w.id
        ) s ON true
        WHERE w.id = %(work_id)s
    """
    with _cursor() as cur:
        cur.execute(sql, {"work_id": work_id})
        return cur.fetchone()


def get_work_vinyl_editions(work_id):
    """Releases en vinilo de la work: year, país, sello, catno, is_reissue, cover.

    Orden por year NULLS LAST, luego país.
    """
    sql = """
        SELECT r.id,
               r.title,
               r.year,
               r.country,
               r.catno,
               r.is_reissue,
               r.cover_url,
               l.name AS label_name
        FROM releases r
        LEFT JOIN labels l ON l.id = r.label_id
        WHERE r.work_id = %(work_id)s
          AND r.format = 'vinyl'
        ORDER BY r.year ASC NULLS LAST,
                 r.country ASC NULLS LAST
    """
    with _cursor() as cur:
        cur.execute(sql, {"work_id": work_id})
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Artista
# ---------------------------------------------------------------------------

def get_artist(artist_id):
    """Artista por id. None si no existe."""
    sql = """
        SELECT a.id,
               a.name,
               a.kind,
               a.disambiguation,
               a.country,
               a.is_primary,
               a.listeners,
               a.bio,
               a.tags,
               a.image_url
        FROM artists a
        WHERE a.id = %(artist_id)s
    """
    with _cursor() as cur:
        cur.execute(sql, {"artist_id": artist_id})
        return cur.fetchone()


def get_artist_discography(artist_id, limit=40):
    """Discografía en vinilo del artista.

    SOLO has_vinyl. Filtro anti-morralla: work_type IN ('studio_album','ep').
    Orden por escuchas: lastfm_playcount DESC NULLS LAST, releases_count DESC
    NULLS LAST (NUNCA cronológico — contrato del proyecto).
    El playcount crudo NO se devuelve al render (regla de números).
    """
    sql = """
        SELECT w.id,
               w.title,
               w.work_type,
               w.year,
               w.releases_count,
               vc.preferred_thumb AS cover_thumb,
               vc.preferred_url   AS cover_url
        FROM works w
        LEFT JOIN v_work_cover vc ON vc.work_id = w.id
        WHERE w.primary_artist_id = %(artist_id)s
          AND w.has_vinyl = true
          AND w.work_type = ANY(%(work_types)s::work_type[])
        ORDER BY w.lastfm_playcount DESC NULLS LAST,
                 w.releases_count DESC NULLS LAST
        LIMIT %(limit)s
    """
    with _cursor() as cur:
        cur.execute(sql, {
            "artist_id": artist_id,
            "work_types": list(_DISCOGRAPHY_WORK_TYPES),
            "limit": limit,
        })
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Precios (marketplace_listings)
# ---------------------------------------------------------------------------

def get_prices_for_work(work_id, max_age_days=None):
    """Listings de tienda para la obra, ordenados por precio ASC.

    Estrategia de match (paridad con el prototipo):
      1. Por release_id de las releases de la work — camino canónico, PERO en
         core `marketplace_listings.release_id` es 100% NULL hoy (verificado
         8-jul-2026: 0 de 25.582). Se deja implementado por si core lo puebla.
      2. Por artist_id = primary_artist_id de la work, cruzado con match de
         título por trigram sobre title_text (usa título de la work + de sus
         releases). Es el camino REAL en M0.

    Cada fila lleva `data_as_of` (fecha de last_seen) y `stale` (bool) según
    STORE_FRESHNESS_MAX_DAYS (o `max_age_days` si se pasa). Sin datos → [].
    Nunca inventa precio.
    """
    stale_days = max_age_days if max_age_days is not None else STORE_FRESHNESS_MAX_DAYS

    # Título de la work + títulos de sus releases, como semillas de match.
    with _cursor() as cur:
        cur.execute("""
            SELECT w.title AS work_title,
                   w.primary_artist_id AS artist_id,
                   COALESCE(
                       (SELECT array_agg(DISTINCT r.title)
                        FROM releases r WHERE r.work_id = w.id),
                       ARRAY[]::text[]
                   ) AS release_titles,
                   COALESCE(
                       (SELECT array_agg(r.id)
                        FROM releases r WHERE r.work_id = w.id),
                       ARRAY[]::bigint[]
                   ) AS release_ids
            FROM works w
            WHERE w.id = %(work_id)s
        """, {"work_id": work_id})
        meta = cur.fetchone()

    if not meta:
        return []

    titles = [meta["work_title"]] + list(meta["release_titles"] or [])
    titles = [t for t in titles if t]
    artist_id = meta["artist_id"]
    release_ids = list(meta["release_ids"] or [])

    sql = """
        SELECT ml.source,
               ml.price_cents,
               ml.currency,
               ml.url,
               ml.availability,
               ml.condition_media,
               ml.condition_sleeve,
               ml.title_text,
               ml.last_seen_at,
               ml.last_seen_at::date AS data_as_of,
               (ml.last_seen_at < (now() - make_interval(days => %(stale_days)s))) AS stale
        FROM marketplace_listings ml
        WHERE ml.price_cents > 0
          AND (
                -- Camino 1: por release_id (hoy vacío en core, dejado por robustez)
                (%(release_ids)s::bigint[] <> ARRAY[]::bigint[]
                 AND ml.release_id = ANY(%(release_ids)s))
                OR
                -- Camino 2 (real en M0): artist_id + match de título por trigram
                (ml.artist_id = %(artist_id)s
                 AND EXISTS (
                     SELECT 1 FROM unnest(%(titles)s::text[]) t(title)
                     WHERE similarity(lower(immutable_unaccent(ml.title_text)),
                                      lower(immutable_unaccent(t.title))) > 0.35
                        OR lower(immutable_unaccent(ml.title_text))
                           LIKE '%%' || lower(immutable_unaccent(t.title)) || '%%'
                 ))
          )
        ORDER BY ml.price_cents ASC
    """
    with _cursor() as cur:
        cur.execute(sql, {
            "artist_id": artist_id,
            "titles": titles,
            "release_ids": release_ids,
            "stale_days": stale_days,
        })
        return cur.fetchall()
