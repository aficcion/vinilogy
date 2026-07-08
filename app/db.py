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

# Filtro anti-morralla para RECOMENDACIÓN por contenido (solo obras de verdad).
_RECO_WORK_TYPES = ("studio_album", "ep")

# Candidatos holgados a traer del índice ANN antes de filtrar/capar por artista.
# Filtramos POST-índice (has_vinyl, work_type, exclusión de artista, cap 1/artista),
# así que pedimos un margen amplio para no quedarnos cortos tras el capado.
_ANN_CANDIDATE_LIMIT = 400

# Boost de popularidad en el re-rank de contenido. La distancia coseno manda; el
# boost es un empujón SUAVE (log escalado) para que, a distancias parecidas, gane
# el disco con más ediciones. Ver nota de fórmula en recommend_similar_to_work.
_RECO_POP_BOOST = 0.02

# Anti-morralla de ARTISTA en recomendación (nit de M1): fuera "Various Artists"
# (kind='various') y tributos evidentes (nombre con 'tribute'). Se aplica en TODOS
# los caminos de reco (afines de obra/artista, mood, prensa). Es una condición SQL
# sobre un alias de `artists` llamado `a`.
#
# OJO: core tiene ademas artistas kind='band' literalmente llamados "Various" /
# "Various Artists" (fugas de compilación mal etiquetadas) → se excluyen por nombre
# exacto normalizado, no solo por kind.
_ARTIST_NOT_MORRALLA_SQL = (
    "a.kind <> 'various' "
    "AND lower(btrim(a.name)) NOT IN "
    "('various', 'various artists', 'varios', 'v.a.', 'va') "
    "AND lower(a.name) NOT LIKE '%%tribute%%'"
)

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
    # Dos fases: el ranking FTS+trgm y el LIMIT se resuelven sobre `works` PURO
    # (sin cover ni artists); la portada (v_work_cover, cara) y el artista se juntan
    # DESPUÉS, sobre las <=limit filas ya elegidas — no sobre todo el conjunto que
    # casa la búsqueda. Semántica idéntica (mismo orden, mismo LIMIT).
    sql = """
        WITH cand AS (
            SELECT w.id,
                   w.title,
                   w.work_type,
                   w.year,
                   w.releases_count,
                   w.primary_artist_id,
                   ts_rank(w.search_doc,
                           websearch_to_tsquery('simple', %(q)s)) AS fts_rank,
                   similarity(lower(immutable_unaccent(w.title)),
                              lower(immutable_unaccent(%(q)s)))    AS trgm_sim
            FROM works w
            WHERE w.has_vinyl = true
              AND (
                  w.search_doc @@ websearch_to_tsquery('simple', %(q)s)
                  OR lower(immutable_unaccent(w.title)) %% lower(immutable_unaccent(%(q)s))
              )
            ORDER BY fts_rank DESC,
                     trgm_sim DESC,
                     w.releases_count DESC NULLS LAST
            LIMIT %(limit)s
        )
        SELECT cand.id,
               cand.title,
               cand.work_type,
               cand.year,
               cand.releases_count,
               a.id   AS artist_id,
               a.name AS artist_name,
               vc.preferred_thumb AS cover_thumb,
               vc.preferred_url   AS cover_url,
               cand.fts_rank,
               cand.trgm_sim
        FROM cand
        JOIN artists a ON a.id = cand.primary_artist_id
        LEFT JOIN v_work_cover vc ON vc.work_id = cand.id
        ORDER BY cand.fts_rank DESC,
                 cand.trgm_sim DESC,
                 cand.releases_count DESC NULLS LAST
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
    """Releases en vinilo de la work, enriquecidas para la ficha.

    Por edición: year, país, sello, catno, cover, y la CADENA DE REEDICIÓN
    (is_reissue + año de la edición original si `reissue_of_release_id` resuelve).
    Orden por year NULLS LAST, luego país.

    NOTA (verificado core, 8-jul-2026): hoy `is_reissue`/`reissue_of_release_id`
    están sin poblar en releases de vinilo (0 filas) — la cadena de reedición se
    materializa aquí por robustez y se activará SOLA cuando el pipeline de core
    la puebla. Mientras tanto `is_reissue=false` y `original_year=None` en todas.
    """
    sql = """
        SELECT r.id,
               r.title,
               r.year,
               r.country,
               r.catno,
               r.is_reissue,
               r.reissue_of_release_id,
               orig.year AS original_year,
               r.cover_url,
               l.name AS label_name
        FROM releases r
        LEFT JOIN labels l ON l.id = r.label_id
        LEFT JOIN releases orig ON orig.id = r.reissue_of_release_id
        WHERE r.work_id = %(work_id)s
          AND r.format = 'vinyl'
        ORDER BY r.year ASC NULLS LAST,
                 r.country ASC NULLS LAST
    """
    with _cursor() as cur:
        cur.execute(sql, {"work_id": work_id})
        return cur.fetchall()


def get_work_tracklist(work_id):
    """Tracklist normalizada de una edición de vinilo representativa de la work.

    Estrategia: de las releases de vinilo con `tracklist_cache` (JSONB, 100%
    cubierto en vinilo en core), toma la MÁS COMPLETA (mayor nº de pistas) — la
    edición representativa que enseña la obra entera. Sin release de vinilo con
    tracklist → [].

    Forma real de `tracklist_cache` (verificada core): array de
    `{title, position, duration, extraartists?}`. Se normaliza a
    `[{position, title, duration}]` (se descartan extraartists y entradas sin
    título; posición/duración pueden faltar → None).
    """
    sql = """
        SELECT r.tracklist_cache
        FROM releases r
        WHERE r.work_id = %(work_id)s
          AND r.format = 'vinyl'
          AND r.tracklist_cache IS NOT NULL
          AND jsonb_typeof(r.tracklist_cache) = 'array'
          AND jsonb_array_length(r.tracklist_cache) > 0
        ORDER BY jsonb_array_length(r.tracklist_cache) DESC
        LIMIT 1
    """
    with _cursor() as cur:
        cur.execute(sql, {"work_id": work_id})
        row = cur.fetchone()
    if not row or not row["tracklist_cache"]:
        return []
    out = []
    for t in row["tracklist_cache"]:
        if not isinstance(t, dict):
            continue
        title = (t.get("title") or "").strip()
        if not title:
            continue
        pos = t.get("position") or None
        dur = t.get("duration") or None
        out.append({
            "position": pos.strip() if isinstance(pos, str) else pos,
            "title": title,
            "duration": dur.strip() if isinstance(dur, str) else dur,
        })
    return out


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


# ---------------------------------------------------------------------------
# Capa de PRENSA española (work_press_signals) — EL CORAZÓN de M2
# ---------------------------------------------------------------------------
#
# Cada obra puede tener VARIAS filas (varias cabeceras la reseñaron). Se agregan:
# frase(s)-vibra con atribución al outlet, unión de vibra/suena_a/temas y las
# fuentes con su URL para poder enlazar la reseña. Sin señales → estructura vacía
# (la ficha simplemente no muestra el bloque; nada de inventar).

# Nombres legibles de las cabeceras (por `source` en core).
PRESS_SOURCE_LABELS = {
    "mondosonoro": "MondoSonoro",
    "jenesaispop": "Jenesaispop",
    "muzikalia": "Muzikalia",
    "dirtyrock": "Dirty Rock",
    "mariskalrock": "Mariskal Rock",
    "crazyminds": "Crazyminds",
    "binaural": "Binaural",
    "ruta66": "Ruta 66",
}


def _dedup_preserve(seq):
    """Dedup case-insensitive preservando orden y la primera grafía vista."""
    out = []
    seen = set()
    for x in seq or []:
        if not x:
            continue
        k = x.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(x.strip())
    return out


def _aggregate_press_rows(rows):
    """Colapsa las filas de work_press_signals de UNA obra en un dict agregado.

    Devuelve:
      - frases: [{frase, source, source_label, review_url, published_at}] (con
        frase_vibra no vacía), ordenadas por published_at DESC NULLS LAST.
      - vibra / suena_a / temas_destacados: unión dedup (case-insensitive).
      - sources: [{source, source_label, review_url, published_at}] (todas).
    Sin filas → todo vacío.
    """
    frases = []
    vibra, suena_a, temas = [], [], []
    sources = []
    for r in rows:
        src = r.get("source")
        label = PRESS_SOURCE_LABELS.get(src, src)
        sources.append({
            "source": src,
            "source_label": label,
            "review_url": r.get("review_url"),
            "published_at": r.get("published_at"),
        })
        frase = (r.get("frase_vibra") or "").strip()
        if frase:
            frases.append({
                "frase": frase,
                "source": src,
                "source_label": label,
                "review_url": r.get("review_url"),
                "published_at": r.get("published_at"),
            })
        vibra += list(r.get("vibra") or [])
        suena_a += list(r.get("suena_a") or [])
        temas += list(r.get("temas_destacados") or [])
    return {
        "frases": frases,
        "vibra": _dedup_preserve(vibra),
        "suena_a": _dedup_preserve(suena_a),
        "temas_destacados": _dedup_preserve(temas),
        "sources": sources,
    }


def get_press_signals(work_id):
    """Señales de prensa agregadas para UNA obra. Estructura vacía si no hay.

    Ver `_aggregate_press_rows` para la forma del retorno.
    """
    sql = """
        SELECT source, review_url, vibra, suena_a, temas_destacados,
               frase_vibra, published_at
        FROM work_press_signals
        WHERE work_id = %(work_id)s
        ORDER BY published_at DESC NULLS LAST, source
    """
    with _cursor() as cur:
        cur.execute(sql, {"work_id": work_id})
        rows = cur.fetchall()
    return _aggregate_press_rows(rows)


def press_signals_batch(work_ids):
    """Señales de prensa para un CONJUNTO de obras, en UNA sola query (sin N+1).

    Devuelve {work_id: agregado} solo para las obras que tienen señales. Las
    obras sin señales simplemente no aparecen en el dict. Usado por la reco para
    apoyar el `porque` en la crítica real sin disparar una query por obra.
    """
    ids = [int(w) for w in (work_ids or []) if w is not None]
    if not ids:
        return {}
    sql = """
        SELECT work_id, source, review_url, vibra, suena_a, temas_destacados,
               frase_vibra, published_at
        FROM work_press_signals
        WHERE work_id = ANY(%(ids)s)
        ORDER BY published_at DESC NULLS LAST, source
    """
    with _cursor() as cur:
        cur.execute(sql, {"ids": ids})
        rows = cur.fetchall()
    by_work = {}
    for r in rows:
        by_work.setdefault(r["work_id"], []).append(r)
    return {wid: _aggregate_press_rows(rws) for wid, rws in by_work.items()}


def resolve_suena_a_artists(names):
    """Mapea nombres de `suena_a` (crítica) a artistas de core CON vinilo.

    Devuelve {nombre_original: artist_id} SOLO para los que resuelven a un
    artista primary con al menos una obra en vinilo (para que el enlace a
    /artista tenga sentido). Match exacto por nombre normalizado (unaccent+lower);
    la crítica escribe el nombre canónico, no hace falta trigram agresivo.
    Sin match → el nombre no aparece (la vista lo pinta como texto plano).
    """
    names = _dedup_preserve(names)
    if not names:
        return {}
    sql = """
        SELECT DISTINCT ON (norm) input.name AS input_name, a.id AS artist_id
        FROM unnest(%(names)s::text[]) input(name)
        JOIN LATERAL (
            SELECT lower(immutable_unaccent(input.name)) AS norm
        ) n ON true
        JOIN artists a
          ON lower(immutable_unaccent(a.name)) = n.norm
         AND a.is_primary = true
         AND EXISTS (
             SELECT 1 FROM works w
             WHERE w.primary_artist_id = a.id AND w.has_vinyl = true
         )
        ORDER BY norm, a.listeners DESC NULLS LAST
    """
    with _cursor() as cur:
        cur.execute(sql, {"names": names})
        rows = cur.fetchall()
    return {r["input_name"]: r["artist_id"] for r in rows}


# ---------------------------------------------------------------------------
# Recomendación por CONTENIDO (embeddings precalculados de core, SQL puro)
# ---------------------------------------------------------------------------
#
# Toda la reco por contenido usa `works.embedding` (512d, HNSW cosine, operador
# `<=>`). CERO embed en vivo, CERO API externa (decisión de Carlos): la semilla
# SIEMPRE es un embedding YA calculado en core.
#
# Naturaleza del embedding v1 (verificado): la fuente es "artista - título (año).
# Géneros. Estilos." → la similitud está dominada por artista+título+género. Los
# vecinos crudos de una obra son casi-duplicados del MISMO artista (variantes,
# directos, demos). Por eso el motor EXCLUYE el mismo primary_artist_id y CAPA a
# 1 obra por artista: el objetivo es DESCUBRIR otros artistas afines.
#
# Como filtramos POST-índice (has_vinyl, work_type, exclusión de artista) se activa
# `SET LOCAL hnsw.iterative_scan = relaxed_order` (pgvector 0.8) en la transacción
# de la consulta ANN, y se pide un LIMIT holgado de candidatos antes de capar.


def _rerank_candidates(rows, limit):
    """Cap 1 obra por artista + re-rank distancia+popularidad.

    Entrada: filas ya ordenadas por distancia ASC (la MÁS cercana por artista es
    la primera que vemos de ese artista → nos la quedamos, descartamos el resto).

    Re-rank (fórmula documentada): `score = dist - _RECO_POP_BOOST * log1p(rc)`.
    La distancia coseno MANDA; el boost es un empujón suave para que, a distancias
    parecidas, gane el disco con más ediciones (proxy de relevancia). Menor score
    = mejor. Devuelve las `limit` mejores.
    """
    import math
    seen_artists = set()
    capped = []
    for r in rows:
        aid = r["artist_id"]
        if aid in seen_artists:
            continue
        seen_artists.add(aid)
        rc = r.get("releases_count") or 0
        r = dict(r)
        r["_score"] = float(r["dist"]) - _RECO_POP_BOOST * math.log1p(rc)
        capped.append(r)
    capped.sort(key=lambda x: x["_score"])
    return capped[:limit]


def _seed_embedding_for_work(cur, work_id, column="embedding"):
    """Devuelve (embedding_literal, primary_artist_id, title) de la obra.

    El embedding se trae a Python como LITERAL de texto (`[x,y,…]`) para pasarlo
    después como parámetro `::vector` al KNN por índice — NO como subquery dentro
    del ORDER BY (una subquery ahí puede impedir que el planner use el índice HNSW).
    (None, None, None) si la obra no existe o no tiene ese embedding.
    """
    cur.execute(
        "SELECT primary_artist_id, title, {col}::text AS emb "
        "FROM works WHERE id = %(id)s".format(col=column),
        {"id": work_id},
    )
    row = cur.fetchone()
    if not row or row["emb"] is None:
        return None, None, None
    return row["emb"], row["primary_artist_id"], row["title"]


# SQL compartido: fase 2 del patrón de dos fases. El CTE `cand` (definido por
# cada caller) ya viene CAPADO a 1 obra por artista y limitado a %(cand)s ARTISTAS
# DISTINTOS por distancia — exactamente el mismo conjunto que producía el viejo
# `SELECT DISTINCT ON (primary_artist_id) … ORDER BY primary_artist_id, dist LIMIT`
# (misma semántica: la obra MÁS cercana de cada uno de los %(cand)s artistas más
# próximos). Aquí SOLO ENTONCES se juntan `artists` + `v_work_cover` (la portada,
# cara) sobre ese puñado de filas, no sobre el ~1,6M de works que pasan el WHERE.
_RECO_PHASE2_SQL = """
    SELECT w.id,
           w.title,
           w.work_type,
           w.year,
           w.releases_count,
           a.id   AS artist_id,
           a.name AS artist_name,
           vc.preferred_thumb AS cover_thumb,
           vc.preferred_url   AS cover_url,
           cand.dist AS dist
    FROM cand
    JOIN works w   ON w.id = cand.id
    JOIN artists a ON a.id = cand.artist_id
    LEFT JOIN v_work_cover vc ON vc.work_id = w.id
    ORDER BY cand.dist
"""


def recommend_similar_to_work(work_id, limit=12):
    """Vinilos afines a una OBRA por embedding precalculado.

    ANN sobre `works.embedding <=> (embedding del seed)`, filtrando a vinilo +
    obra de verdad (studio_album/ep), EXCLUYENDO el mismo primary_artist_id que la
    semilla (los vecinos crudos serían variantes del propio artista) y la propia
    semilla. Trae candidatos holgados por distancia, capa 1 por artista y re-rankea
    con distancia+popularidad (ver _rerank_candidates).

    RENDIMIENTO (dos fases): el KNN corre sobre `works` PURO (sin joins) con el
    embedding del seed como literal `::vector` → usa el índice HNSW; la portada
    (cara) y `artists` solo se juntan DESPUÉS, sobre el puñado de candidatos ya
    capados por artista. Semántica idéntica a la versión de un solo pase.

    Cada fila lleva `porque` explicable. Si el seed no tiene embedding → [] honesto.
    """
    # Fase 1: KNN puro sobre works (sin cover). El seed embedding va como literal
    # ::vector. El WHERE aplica todos los filtros duros post-índice y el
    # `DISTINCT ON (primary_artist_id) … ORDER BY primary_artist_id, dist LIMIT`
    # capa 1/artista DENTRO del corte (misma semántica que el pase único original:
    # los %(cand)s artistas más próximos, su obra más cercana), pero SIN el join de
    # portada — por eso corre en ~2s en vez de ~18s.
    cand_sql = """
        WITH cand AS (
            SELECT DISTINCT ON (w.primary_artist_id)
                   w.id,
                   w.primary_artist_id AS artist_id,
                   (w.embedding <=> %(seed)s::vector) AS dist
            FROM works w
            JOIN artists a ON a.id = w.primary_artist_id
            WHERE w.embedding IS NOT NULL
              AND w.has_vinyl = true
              AND w.work_type = ANY(%(work_types)s::work_type[])
              AND w.primary_artist_id <> %(seed_artist)s
              AND w.id <> %(work_id)s
              AND {artist_ok}
            ORDER BY w.primary_artist_id, w.embedding <=> %(seed)s::vector
            LIMIT %(cand)s
        )
    """.format(artist_ok=_ARTIST_NOT_MORRALLA_SQL)
    sql = cand_sql + _RECO_PHASE2_SQL

    with _cursor() as cur:
        seed_emb, seed_artist, seed_title = _seed_embedding_for_work(cur, work_id)
        if seed_emb is None:
            return []
        seed_title = seed_title or "esta obra"

        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, {
            "work_id": work_id,
            "seed": seed_emb,
            "seed_artist": seed_artist,
            "work_types": list(_RECO_WORK_TYPES),
            "cand": _ANN_CANDIDATE_LIMIT,
        })
        rows = cur.fetchall()

    ranked = _rerank_candidates(rows, limit)
    for r in ranked:
        r["porque"] = "afín en género y estilo a {}".format(seed_title)
    return ranked


def recommend_similar_to_artist(artist_id, limit=12):
    """Vinilos afines a un ARTISTA por centroide de sus embeddings.

    Centroide = avg de los embeddings de sus works con vinilo/obra-de-verdad. Si
    el centroide falla (sin works embebidos) → DEGRADA a la semilla de su obra más
    popular con embedding. Vecinos con primary_artist_id <> artist_id, mismas reglas
    de filtro/cap. `porque` = "en la onda de {artista}". Sin semilla posible → [].
    """
    # Dos fases: el SEED (centroide o embedding de la obra más popular) se
    # calcula/trae a Python como LITERAL ::vector; luego KNN puro sobre works y
    # cap+portada sobre lo reducido (ver recommend_similar_to_work).
    with _cursor() as cur:
        cur.execute("SELECT name FROM artists WHERE id = %(id)s", {"id": artist_id})
        arow = cur.fetchone()
        if not arow:
            return []
        artist_name = arow["name"]

        # Centroide sobre sus works con vinilo/obra de verdad → literal de texto.
        cur.execute("""
            SELECT avg(w.embedding)::vector(512)::text AS centroid, count(*) AS n
            FROM works w
            WHERE w.primary_artist_id = %(id)s
              AND w.embedding IS NOT NULL
              AND w.has_vinyl = true
              AND w.work_type = ANY(%(work_types)s::work_type[])
        """, {"id": artist_id, "work_types": list(_RECO_WORK_TYPES)})
        crow = cur.fetchone()
        seed_emb = crow["centroid"] if (crow and crow["n"]) else None

        if seed_emb is None:
            # Degradación: embedding de la obra más popular con embedding.
            cur.execute("""
                SELECT embedding::text AS emb
                FROM works
                WHERE primary_artist_id = %(id)s AND embedding IS NOT NULL
                ORDER BY releases_count DESC NULLS LAST, lastfm_playcount DESC NULLS LAST
                LIMIT 1
            """, {"id": artist_id})
            frow = cur.fetchone()
            if not (frow and frow["emb"] is not None):
                return []
            seed_emb = frow["emb"]

        cand_sql = """
            WITH cand AS (
                SELECT DISTINCT ON (w.primary_artist_id)
                       w.id,
                       w.primary_artist_id AS artist_id,
                       (w.embedding <=> %(seed)s::vector) AS dist
                FROM works w
                JOIN artists a ON a.id = w.primary_artist_id
                WHERE w.embedding IS NOT NULL
                  AND w.has_vinyl = true
                  AND w.work_type = ANY(%(work_types)s::work_type[])
                  AND w.primary_artist_id <> %(artist_id)s
                  AND {artist_ok}
                ORDER BY w.primary_artist_id, w.embedding <=> %(seed)s::vector
                LIMIT %(cand)s
            )
        """.format(artist_ok=_ARTIST_NOT_MORRALLA_SQL)
        sql = cand_sql + _RECO_PHASE2_SQL

        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, {
            "artist_id": artist_id,
            "seed": seed_emb,
            "work_types": list(_RECO_WORK_TYPES),
            "cand": _ANN_CANDIDATE_LIMIT,
        })
        rows = cur.fetchall()

    ranked = _rerank_candidates(rows, limit)
    for r in ranked:
        r["porque"] = "en la onda de {}".format(artist_name)
    return ranked


# ---------------------------------------------------------------------------
# Afines por VIBRA DE CRÍTICA (embedding_press) — BONUS de M2
# ---------------------------------------------------------------------------
#
# Complementa (no sustituye) a recommend_similar_to_work. `embedding_press`
# destila la voz de la crítica española y solo cubre ~9K works con vinilo, así
# que esta señal es un BONUS: donde el seed tiene embedding_press, damos "afines
# por lo que dice la crítica"; donde no, [] y la ficha oculta la sub-sección.
# Mismas reglas duras: excluir el mismo artista, cap 1/artista, solo vinilo +
# obra de verdad, sin morralla de artista.


def similar_by_press(work_id, limit=8):
    """Afines a la OBRA por VIBRA DE CRÍTICA (`embedding_press <=>`).

    Solo funciona si el seed tiene embedding_press. Vecinos con embedding_press,
    de OTRO artista, capados 1/artista y re-rankeados igual que la reco general.
    Seed sin embedding_press → [] (la ficha no muestra la sub-sección).
    """
    # Dos fases (ver recommend_similar_to_work): KNN puro sobre works por
    # `embedding_press`, luego cap 1/artista + join de portada sobre lo reducido.
    cand_sql = """
        WITH cand AS (
            SELECT DISTINCT ON (w.primary_artist_id)
                   w.id,
                   w.primary_artist_id AS artist_id,
                   (w.embedding_press <=> %(seed)s::vector) AS dist
            FROM works w
            JOIN artists a ON a.id = w.primary_artist_id
            WHERE w.embedding_press IS NOT NULL
              AND w.has_vinyl = true
              AND w.work_type = ANY(%(work_types)s::work_type[])
              AND w.primary_artist_id <> %(seed_artist)s
              AND w.id <> %(work_id)s
              AND {artist_ok}
            ORDER BY w.primary_artist_id, w.embedding_press <=> %(seed)s::vector
            LIMIT %(cand)s
        )
    """.format(artist_ok=_ARTIST_NOT_MORRALLA_SQL)
    sql = cand_sql + _RECO_PHASE2_SQL

    with _cursor() as cur:
        seed_emb, seed_artist, _title = _seed_embedding_for_work(
            cur, work_id, column="embedding_press")
        if seed_emb is None:
            return []
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, {
            "work_id": work_id,
            "seed": seed_emb,
            "seed_artist": seed_artist,
            "work_types": list(_RECO_WORK_TYPES),
            "cand": _ANN_CANDIDATE_LIMIT,
        })
        rows = cur.fetchall()

    ranked = _rerank_candidates(rows, limit)
    for r in ranked:
        r["porque"] = "la crítica lo sitúa en una vibra afín"
    return ranked


# ---------------------------------------------------------------------------
# Recomendación por MOOD (léxico curado → styles + tags whitelisted)
# ---------------------------------------------------------------------------

def works_by_styles_and_tags(style_names, tag_whitelist, limit=20,
                             per_artist_cap=2):
    """Works con vinilo que casan un conjunto de STYLES (base) + tags whitelisted.

    Base fiable = `work_styles` con styles limpios. Los tags (folksonomía Last.fm,
    ruidosos) solo SUMAN señal si están en la whitelist del mood — nunca deciden
    solos. Ranked por popularidad (releases_count/playcount). Cap por artista para
    diversidad. El número de styles/tags casados va en `match_count` (para el
    `porque`), pero NUNCA se expone playcount crudo.

    Sin styles → [] (el caller degrada honesto).
    """
    style_names = [s for s in (style_names or []) if s]
    tag_whitelist = [t.lower() for t in (tag_whitelist or []) if t]
    if not style_names:
        return []

    # Dos fases (patrón de rendimiento): todo el ranking/cap/LIMIT se resuelve SIN
    # tocar la portada (v_work_cover, cara); `artists` entra en `scored` solo porque
    # el filtro anti-morralla es por nombre de artista, pero la portada se junta al
    # FINAL, sobre las <=limit filas ya elegidas — no sobre todas las matched.
    sql = """
        WITH matched AS (
            SELECT w.id,
                   w.title,
                   w.work_type,
                   w.year,
                   w.releases_count,
                   w.lastfm_playcount,
                   w.primary_artist_id,
                   COUNT(DISTINCT st.name) AS style_hits,
                   ARRAY_AGG(DISTINCT st.name) AS matched_styles
            FROM works w
            JOIN work_styles ws ON ws.work_id = w.id
            JOIN styles st ON st.id = ws.style_id
                          AND st.name = ANY(%(styles)s)
            WHERE w.has_vinyl = true
              AND w.work_type = ANY(%(work_types)s::work_type[])
            GROUP BY w.id, w.title, w.work_type, w.year, w.releases_count,
                     w.lastfm_playcount, w.primary_artist_id
        ),
        scored AS (
            SELECT m.*,
                   a.name AS artist_name,
                   -- tag hits desde la whitelist (folksonomía, solo suma)
                   (SELECT COUNT(*) FROM unnest(w.lastfm_tags) tg
                    WHERE lower(tg) = ANY(%(tags)s)) AS tag_hits
            FROM matched m
            JOIN works w ON w.id = m.id
            JOIN artists a ON a.id = m.primary_artist_id
            WHERE {artist_ok}
        ),
        ranked AS (
            SELECT s.*,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.primary_artist_id
                       ORDER BY (s.style_hits + s.tag_hits) DESC,
                                s.releases_count DESC NULLS LAST,
                                s.lastfm_playcount DESC NULLS LAST
                   ) AS rn_artist
            FROM scored s
        ),
        picked AS (
            SELECT id, title, work_type, year, releases_count, lastfm_playcount,
                   primary_artist_id AS artist_id, artist_name,
                   style_hits, tag_hits, matched_styles
            FROM ranked
            WHERE rn_artist <= %(cap)s
            ORDER BY (style_hits + tag_hits) DESC,
                     releases_count DESC NULLS LAST,
                     lastfm_playcount DESC NULLS LAST
            LIMIT %(limit)s
        )
        SELECT p.id, p.title, p.work_type, p.year, p.releases_count,
               p.artist_id, p.artist_name,
               vc.preferred_thumb AS cover_thumb,
               vc.preferred_url   AS cover_url,
               p.style_hits, p.tag_hits, p.matched_styles
        FROM picked p
        LEFT JOIN v_work_cover vc ON vc.work_id = p.id
        ORDER BY (p.style_hits + p.tag_hits) DESC,
                 p.releases_count DESC NULLS LAST,
                 p.lastfm_playcount DESC NULLS LAST
    """.format(artist_ok=_ARTIST_NOT_MORRALLA_SQL)
    with _cursor() as cur:
        cur.execute(sql, {
            "styles": style_names,
            "tags": tag_whitelist,
            "work_types": list(_RECO_WORK_TYPES),
            "cap": per_artist_cap,
            "limit": limit,
        })
        return cur.fetchall()