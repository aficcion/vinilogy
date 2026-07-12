"""Acceso a datos de Vinilogy.

Única fuente de datos: `vinology_core` (DSN en env `VINILOGY_DB_DSN`).
La app SOLO LEE — jamás hace DDL contra core.

Todas las queries son parametrizadas (nada de f-strings con input de usuario).
Los cursores devuelven dicts (RealDictCursor).

Contratos del proyecto respetados aquí:
  - Solo works con vinilo (`has_vinyl = true`) salen en búsqueda/discografía.
  - Discografía se ordena por escuchas (`lastfm_playcount DESC NULLS LAST`),
    NUNCA cronológico. El playcount CRUDO no se expone al render (regla de números).
  - Precios: match por `marketplace_listings.work_id`, pre-resuelto en el port
    de core (migración 056 — ver nota en get_prices_for_work). Nunca se inventa
    precio: sin datos → lista vacía.
"""
import os
import atexit
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

DSN = os.environ.get("VINILOGY_DB_DSN", "postgresql://localhost/vinology_core")

# Umbral de frescura de datos de tienda (días). Contrato heredado del proyecto.
STORE_FRESHNESS_MAX_DAYS = int(os.environ.get("VINILOGY_STORE_FRESHNESS_DAYS", "3"))

# Filtro anti-morralla para discografía (contrato del proyecto).
_DISCOGRAPHY_WORK_TYPES = ("studio_album", "ep")

# Tipos de obra visibles en BÚSQUEDA. Contrato del selftest (§1: "search_works NUNCA
# devuelve compilation/live_album/single"): solo álbum de estudio + EP. Es una
# constante propia por si se decide ampliarla en el futuro (recopilatorios/BSOs/
# directos que la gente sí busca) — ese cambio exigiría actualizar ese contrato.
_SEARCH_WORK_TYPES = _DISCOGRAPHY_WORK_TYPES

# Filtro anti-morralla para RECOMENDACIÓN por contenido (solo obras de verdad).
_RECO_WORK_TYPES = ("studio_album", "ep")

# OBRA OFICIAL — excluye ediciones no oficiales (bootlegs). Core marca
# `is_official=false` en los works cuyas ediciones son todas "unofficial release"
# (formato Discogs); sin este filtro un bootleg en LP (p.ej. Arctic Monkeys
# "Soiled", master Discogs 865304) aparece como studio_album normal. Se interpola
# en los ~13 sitios de búsqueda/reco/discografía reutilizando el scaffolding
# {album_track_ok} del antiguo parche de singles-disfrazados (ya retirado).
# El índice parcial de core `idx_works_artist_type ... WHERE is_official=true`
# soporta justo este predicado.
def _album_track_ok_sql(work_alias="w"):
    """Predicado anti-bootleg: exige is_official=true en el work indicado."""
    return f"{work_alias}.is_official"


# Regla TRANSVERSAL de PORTADA OBLIGATORIA: un work solo se MUESTRA si tiene una
# portada de Discogs en `cover_images` (source='discogs'). Se añade al WHERE de
# TODA query que devuelva works a mostrar (search, todas las recos, afines,
# discografía, mood, gap, multi-seed).
#
# CONVERGENCIA (crítico): este predicado NUNCA se aplica a solas — cada camino
# calcula candidatos SIN filtro de portada primero, ENCOLA en el worker de covers
# los candidatos aún sin portada, y solo DESPUÉS filtra por esta condición. Si
# solo se consultaran los ya-con-portada, los nuevos jamás se pedirían. Por eso los
# callers piden un candidate-limit HOLGADO y devuelven, además de los works a
# mostrar, los ids de candidatos SIN portada para que el router los encole.
#
# RENDIMIENTO: cuando el conjunto de candidatos ya está ACOTADO (fase 2 / CTE
# `cand` capado), este EXISTS por work_id usa `cover_images_work_id_idx` y es
# barato. NUNCA aplicarlo sobre un conjunto de millones de works sin acotar antes
# (el planner tiende a barrer las ~205K filas discogs de `cover_images` y a
# re-ejecutar el candidato por cada una — ver nota en `search_works`).
def _has_discogs_cover_sql(work_alias="w"):
    """Predicado SQL: `<alias>` tiene portada de Discogs en `cover_images`."""
    return (
        "EXISTS (SELECT 1 FROM cover_images ci_hdc"
        " WHERE ci_hdc.work_id = {w}.id AND ci_hdc.source = 'discogs')"
    ).format(w=work_alias)


# Normalización US→UK de la query ANTES de buscar (el catálogo de core rotula en
# grafía británica con frecuencia). Palabra COMPLETA, case-insensitive; no toca
# subcadenas ("colored" no pasa a "coloured" por accidente — el mapa es por token).
# Los ~20 pares comunes. Se aplica a works y artists.
_US_UK_SPELLING = {
    "favorite": "favourite",
    "favorites": "favourites",
    "color": "colour",
    "colors": "colours",
    "colored": "coloured",
    "honor": "honour",
    "honors": "honours",
    "theater": "theatre",
    "theaters": "theatres",
    "catalog": "catalogue",
    "catalogs": "catalogue",
    "analog": "analogue",
    "license": "licence",
    "defense": "defence",
    "gray": "grey",
    "traveled": "travelled",
    "traveling": "travelling",
    "traveler": "traveller",
    "labor": "labour",
    "neighbor": "neighbour",
    "neighbors": "neighbours",
    "rumor": "rumour",
    "rumors": "rumours",
    "harbor": "harbour",
    "flavor": "flavour",
    "flavors": "flavours",
    "behavior": "behaviour",
    "center": "centre",
    "centers": "centres",
    "meter": "metre",
    "fiber": "fibre",
    "liter": "litre",
    "organize": "organise",
    "realize": "realise",
    "apologize": "apologise",
}

# Mínimo de caracteres de la query (más corto → sin resultados). Contrato del spec.
_SEARCH_MIN_CHARS = 3


def normalize_search_query(q):
    """Normaliza la query de búsqueda: trim + US→UK por palabra completa.

    Devuelve la query normalizada (misma si no hay nada que mapear). El mínimo de
    caracteres lo comprueba el caller (query < 3 → sin resultados)."""
    q = (q or "").strip()
    if not q:
        return q
    import re
    def _sub(m):
        w = m.group(0)
        repl = _US_UK_SPELLING.get(w.lower())
        return repl if repl else w
    return re.sub(r"[A-Za-z]+", _sub, q)


# Candidatos holgados a traer del índice ANN antes de filtrar/capar por artista.
# Filtramos POST-índice (has_vinyl, work_type, exclusión de artista, cap 1/artista),
# así que pedimos un margen amplio para no quedarnos cortos tras el capado.
# 200 candidatos del ANN: suficiente para rellenar `limit` tras el cap 1/artista +
# el filtro de portada, y ~2× más rápido que 400 (medido: KNN 1,6s→0,8s, mismos 12
# resultados) — clave para el presupuesto de <3s de /buscar/obra/artista.
_ANN_CANDIDATE_LIMIT = 200

# Factor de holgura del pool que se rerankea ANTES de filtrar por portada de
# Discogs (regla transversal + convergencia): se rerankea `limit * factor` para que,
# tras descartar los que aún no tienen portada (y encolarlos), queden suficientes
# CON portada hasta `limit`. Como ~83% de works con vinilo no tienen portada aún, el
# factor es amplio; los que faltan se van poblando por el worker de covers.
_COVER_POOL_FACTOR = 6

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


# Tamaño máximo del pool. Cada request puede abanicar varias conexiones (p.ej. /mi
# lanza 4 en paralelo), así que 10 se agota en el primer pico. Configurable por env,
# acotado al max_connections de Postgres. Default holgado para el arranque.
_POOL_MAX = int(os.environ.get("VINILOGY_DB_POOL_MAX", "24"))


def _get_pool():
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(minconn=1, maxconn=_POOL_MAX, dsn=DSN)
    return _pool


@contextmanager
def _cursor():
    pool = _get_pool()
    conn = pool.getconn()
    # Una conexión que Postgres/pgbouncer cerró por idle puede volver del pool ya
    # muerta → la descartamos y pedimos otra en vez de repartir una conexión rota.
    if getattr(conn, "closed", 0):
        pool.putconn(conn, close=True)
        conn = pool.getconn()
    broken = False
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        # Si el rollback también falla, la conexión está muerta → que no vuelva al pool.
        try:
            conn.rollback()
        except Exception:
            broken = True
        raise
    finally:
        pool.putconn(conn, close=broken)


def ping():
    """SELECT 1 contra el pool (para /health). Lanza si la BD no responde."""
    with _cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()


@atexit.register
def _close_pool():
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


# ---------------------------------------------------------------------------
# Mosaico decorativo (fondo del hero de la home)
# ---------------------------------------------------------------------------

def top_covers_by_playcount(style_names, min_playcount=3_000_000, limit=150):
    """Obras CONOCIDAS (más escuchadas en Last.fm) de unos estilos dados, con
    portada de Discogs, para la TIRA de discos reales de la home.

    A diferencia de un muestreo aleatorio, sesga hacia lo RECONOCIBLE: filtra por
    `has_vinyl` + álbum/EP + estilo en `style_names` + un umbral de `lastfm_playcount`
    (el umbral recorta el candidato a unos pocos miles ANTES del join de estilos —
    sin él habría que ordenar ~90K works, medido ~8s → ~0,8s). El estilo se comprueba
    con EXISTS (evita duplicar la fila por cada estilo casado). Ordena por playcount
    desc y capa a `limit`. La ruta luego les cuelga el precio ES
    (pricing.attach_cheapest) y descarta las que no tienen. Sin estilos → [].
    """
    style_names = [s for s in (style_names or []) if s]
    if not style_names:
        return []
    sql = """
        SELECT w.id, w.title, w.year, w.lastfm_playcount,
               {clean_name} AS artist_name,
               ci.url_thumb AS cover_thumb
        FROM works w
        JOIN cover_images ci ON ci.work_id = w.id
             AND ci.source = 'discogs' AND ci.url_thumb IS NOT NULL
        JOIN artists a ON a.id = w.primary_artist_id
        WHERE w.has_vinyl = true
          AND w.work_type = ANY(%(work_types)s::work_type[])
          AND w.lastfm_playcount > %(thr)s
          AND EXISTS (
              SELECT 1 FROM work_styles ws
              JOIN styles st ON st.id = ws.style_id
              WHERE ws.work_id = w.id AND st.name = ANY(%(styles)s))
        ORDER BY w.lastfm_playcount DESC
        LIMIT %(limit)s
    """.format(clean_name=_clean_artist_name_sql("a.name"))
    with _cursor() as cur:
        cur.execute(sql, {
            "styles": style_names,
            "thr": min_playcount,
            "work_types": list(_RECO_WORK_TYPES),
            "limit": limit,
        })
        return [dict(r) for r in cur.fetchall()]


def sample_cover_thumbs(limit=60):
    """Lista de URLs de miniaturas de portadas Discogs para el mosaico del hero.

    Decorativo y best-effort. Muestreo barato con TABLESAMPLE (evita el
    `ORDER BY random()` sobre las ~235K filas): coge un bloque aleatorio y capa a
    `limit`. Si el sample sale corto (poco frecuente), rellena con un fetch simple.
    """
    sql = """
        SELECT url_thumb FROM cover_images TABLESAMPLE SYSTEM (1)
        WHERE source = 'discogs' AND url_thumb IS NOT NULL
        LIMIT %(limit)s
    """
    with _cursor() as cur:
        cur.execute(sql, {"limit": limit})
        rows = [r["url_thumb"] for r in cur.fetchall()]
        if len(rows) < limit:
            cur.execute(
                "SELECT url_thumb FROM cover_images WHERE source='discogs'"
                " AND url_thumb IS NOT NULL LIMIT %(limit)s", {"limit": limit})
            rows = [r["url_thumb"] for r in cur.fetchall()]
    return rows


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

# Candidatos holgados de búsqueda antes del filtro de portada. Se pide MARGEN
# porque muchos candidatos aún no tienen portada de Discogs (se encolan y caen del
# resultado hasta que el worker las trae). Con margen amplio quedan suficientes CON
# portada tras el filtro.
_SEARCH_CAND_LIMIT = 120

# Umbral de similitud del trigram SOLO en la fase de fallback typo-tolerante. El
# fallback existe para RESCATAR errores de tecleo (`radiohed`→`radiohead`), que son
# de similitud alta (1-2 caracteres); subir el umbral del `%%` de 0.3 (default) a
# este valor recorta los falsos positivos flojos y acelera el barrido (medido
# `kid a` 4,3s→0,9s) sin perder los typos reales. Es transaccional (`SET LOCAL`),
# así que NO se filtra a otras queries de la conexión del pool.
_TRGM_FALLBACK_THRESHOLD = 0.4


def _prefix_tsquery(q):
    """Construye una tsquery de PREFIJO para el type-ahead: los tokens anteriores
    exactos y el ÚLTIMO como prefijo → `to_tsquery('simple', 'miles & dav:*')`.

    Motivo: el type-ahead manda PREFIJOS incompletos (`radioh`, `miles dav`) que
    `plainto_tsquery` NO casa (necesita tokens completos) → caían al trigram (lento).
    El `:*` casa por prefijo usando el índice FTS (medido: 0,6s → 0,05s). Se unaccenta
    en Python (para poder pasar el resultado a `to_tsquery` SIN envolverlo en
    `immutable_unaccent(param)` — ese wrapper impedía usar el índice GIN por prefijo,
    medido 1,3s) y se sanea a `[0-9a-z]` (to_tsquery es estricto con la sintaxis). El
    `search_doc` guarda lexemas ya unaccentados, así que casa. None si vacío.
    """
    import re, unicodedata
    q = unicodedata.normalize("NFKD", q or "").encode("ascii", "ignore").decode("ascii")
    toks = [re.sub(r"[^0-9a-zA-Z]", "", t)
            for t in re.split(r"\s+", q.strip())]
    toks = [t for t in toks if t]
    if not toks:
        return None
    return " & ".join(toks[:-1] + [toks[-1] + ":*"])


def search_works(q, limit=20, prefix=False):
    """Works que casan `q`, cumpliendo la regla TRANSVERSAL (vinilo + álbum/EP +
    anti-single + PORTADA de Discogs). Devuelve un dict:
        {"works": [filas a mostrar, con portada],
         "missing_cover_ids": [ids de candidatos SIN portada, para encolar]}

    Ranking (spec): exacto de título primero (CASE), luego `ts_rank` de FTS, luego
    popularidad (`lastfm_playcount DESC NULLS LAST, releases_count DESC NULLS LAST`).
    El TRIGRAM va SOLO en el WHERE (typos), NUNCA en el ORDER BY.

    CONVERGENCIA: `cand` calcula candidatos SIN el filtro de portada; se aplican
    los filtros de álbum/anti-single en `showable`; de esos, `missing_cover_ids`
    son los que aún NO tienen portada de Discogs (el router los encola) y `works`
    los que SÍ (se muestran hasta `limit`).

    RENDIMIENTO (crítico): las CTE van `MATERIALIZED` para que la fase de ranking
    corra UNA vez; y el filtro de portada se hace restringiendo `cover_images` a los
    ids candidatos (`work_id = ANY(...)`) — NO con un EXISTS que el planner
    convertiría en un barrido de las ~205K filas discogs re-ejecutando el candidato
    por cada una (medido: 27s → <1s).

    TYPO-TOLERANCIA EN DOS FASES (medido: `love` 2,3s → 0,2s): el TRIGRAM del WHERE
    (`title %% nq`) sobre un token común barre ~cientos de miles de filas aunque el
    FTS ya casara de sobra. Por eso primero se corre SOLO con FTS; únicamente si el
    FTS no casa NADA (typo real, p.ej. `radiohed`) se reintenta añadiendo el trigram
    (barato: un token que no casó por FTS es raro, casa pocas filas). Los tokens
    comunes y bien escritos nunca pagan el trigram → sin timeouts.
    """
    q = normalize_search_query(q)
    if not q or len(q) < _SEARCH_MIN_CHARS:
        return {"works": [], "missing_cover_ids": []}
    # PREFIJO (type-ahead): tsquery `tok & tok:*` que casa por prefijo con el índice
    # FTS. Si el saneado deja la query vacía, no hay match posible.
    prefix_ts = _prefix_tsquery(q) if prefix else None
    if prefix and not prefix_ts:
        return {"works": [], "missing_cover_ids": []}

    def _run(use_trgm):
        # tsquery: PREFIJO para type-ahead; `plainto` (tokens completos) si no.
        tsq = ("to_tsquery('simple', %(prefix_ts)s)"
               if prefix else "plainto_tsquery('simple', p.uq)")
        # El trigram va en el WHERE (typos), NUNCA en el ORDER BY (ranking).
        trgm_or = ("OR lower(immutable_unaccent(w.title)) %% p.nq"
                   if use_trgm else "")
        sql = """
            WITH params AS MATERIALIZED (
                SELECT immutable_unaccent(%(q)s)               AS uq,
                       lower(immutable_unaccent(%(q)s))        AS nq
            ),
            cand AS MATERIALIZED (
                -- Ranking + LIMIT holgado SIN filtro de portada (convergencia) y SIN
                -- el anti-single (corre sobre este puñado, no sobre todo lo que casa).
                SELECT w.id, w.title, w.work_type, w.year, w.releases_count,
                       w.primary_artist_id, w.lastfm_playcount, w.is_official,
                       ts_rank(w.search_doc, {tsq}) AS fts_rank
                FROM works w, params p
                WHERE w.has_vinyl = true
                  AND w.work_type = ANY(%(work_types)s::work_type[])
                  AND (
                      w.search_doc @@ {tsq}
                      {trgm_or}
                  )
                ORDER BY CASE WHEN lower(immutable_unaccent(w.title)) = p.nq
                              THEN 0 ELSE 1 END,
                         ts_rank(w.search_doc, {tsq}) DESC,
                         w.lastfm_playcount DESC NULLS LAST,
                         w.releases_count DESC NULLS LAST
                LIMIT %(cand_limit)s
            ),
            albumok AS MATERIALIZED (
                -- Candidatos que además son disco de verdad (anti-single disfrazado).
                SELECT c.* FROM cand c
                WHERE {album_track_ok_c}
            ),
            covers_c AS MATERIALIZED (
                -- Portadas discogs de los candidatos (acotado por work_id, índice)
                -- calculadas UNA vez: sirven para `has_cover` Y para las URLs. Evita
                -- el LEFT JOIN sobre las ~235K filas discogs, que el planner resuelve
                -- como nested-loop (235K por candidato) cuando el estimador de filas
                -- falla — p.ej. con la tsquery de PREFIJO del type-ahead (medido:
                -- 1,3s→0,1s). MATERIALIZED fija el conjunto pequeño antes del join.
                SELECT DISTINCT ON (work_id) work_id,
                       url AS preferred_url, url_thumb AS preferred_thumb
                FROM cover_images
                WHERE source = 'discogs'
                  AND work_id = ANY(ARRAY(SELECT id FROM albumok))
            )
            SELECT ao.id, ao.title, ao.work_type, ao.year, ao.releases_count,
                   ao.fts_rank,
                   (vc.work_id IS NOT NULL) AS has_cover,
                   a.id   AS artist_id,
                   a.name AS artist_name,
                   vc.preferred_thumb AS cover_thumb,
                   vc.preferred_url   AS cover_url
            FROM albumok ao
            CROSS JOIN params p
            JOIN artists a ON a.id = ao.primary_artist_id
            LEFT JOIN covers_c vc ON vc.work_id = ao.id
            ORDER BY CASE WHEN lower(immutable_unaccent(ao.title)) = p.nq
                          THEN 0 ELSE 1 END,
                     ao.fts_rank DESC,
                     ao.lastfm_playcount DESC NULLS LAST,
                     ao.releases_count DESC NULLS LAST
        """.format(album_track_ok_c=_album_track_ok_sql("c"), trgm_or=trgm_or,
                   tsq=tsq)
        with _cursor() as cur:
            if use_trgm:
                cur.execute("SET LOCAL pg_trgm.similarity_threshold = %s"
                            % _TRGM_FALLBACK_THRESHOLD)
            cur.execute(sql, {
                "q": q,
                "prefix_ts": prefix_ts,
                "work_types": list(_SEARCH_WORK_TYPES),
                "cand_limit": _SEARCH_CAND_LIMIT,
            })
            return cur.fetchall()

    def _split(rows):
        # `top_coverless`: el candidato MEJOR rankeado (rows[0], p.ej. el match exacto
        # de título) cuando NO tiene portada → estaría OCULTO por la regla transversal
        # y el disco buscado no aparecería (solo sus afines). El router recupera su
        # portada de Discogs en el momento (~0,25s) para mostrarlo en la 1ª búsqueda.
        works, missing, top_coverless = [], [], None
        for i, r in enumerate(rows):
            r = dict(r)
            has_cover = r.pop("has_cover", False)
            if has_cover:
                r["has_discogs"] = True  # señal para needs_reliable_cover
                if len(works) < limit:
                    works.append(r)
            else:
                if i == 0:
                    top_coverless = r
                missing.append(r["id"])
        return works, missing, top_coverless

    rows = _run(use_trgm=False)
    # Solo caemos al trigram si el FTS no casó NADA (typo real). Un token común y bien
    # escrito casa por FTS → nunca paga el barrido trigram (ver docstring). En modo
    # PREFIJO no hay fallback: el `:*` ya cubre lo incompleto y el type-ahead no debe
    # pagar el trigram en cada tecla.
    if not rows and not prefix:
        rows = _run(use_trgm=True)
    works, missing, top_coverless = _split(rows)
    return {"works": works, "missing_cover_ids": missing,
            "top_coverless": top_coverless}


def _clean_artist_name_sql(col="a.name"):
    """SQL: nombre de artista SIN el disambiguador numérico de Discogs "(N)".

    Discogs añade "(11)" a nombres homónimos ("Ace (11)"); NUNCA se muestra. Strip
    del sufijo `\\s*\\(\\d+\\)$`. Se usa dondequiera que se exponga el nombre."""
    return "regexp_replace({col}, '\\s*\\(\\d+\\)$', '')".format(col=col)


def _clean_disambiguation_sql(col="a.disambiguation"):
    """SQL: disambiguation SOLO si NO es numérica (la "(N)" de Discogs → NULL).

    Una disambiguation que casa `^\\d+$` es la (N) de Discogs → se oculta (NULL)."""
    return ("CASE WHEN {col} ~ '^[0-9]+$' THEN NULL ELSE {col} END").format(col=col)


def search_artists(q, limit=20, prefix=False):
    """Artistas que casan `q`, DEDUP de homónimos y SIN "(N)" de Discogs.

    Solo artistas con ≥1 work MOSTRABLE (vinilo + álbum/EP + anti-single + portada
    de Discogs) → los homónimos-basura sin discos caen. Dedup por nombre normalizado
    (`name_clean`) quedándose con el canónico (is_primary DESC, nº de works
    mostrables DESC, listeners DESC) → no salen dos "Geese".

    Ranking (spec): boost exacto por `name_clean`=normalize(q) primero, `is_primary`,
    luego `ts_rank` de FTS, luego `listeners DESC NULLS LAST`. Trigram SOLO en el
    WHERE (typos), NUNCA en el ORDER BY. `disambiguation` numérica → NULL; `name`
    sin la "(N)".

    RENDIMIENTO (dos fases, medido <1s): `cand` rankea/limita barato por FTS
    sobre `artists`; el filtro de work-mostrable y el dedup corren sobre ese puñado.

    TYPO-TOLERANCIA EN DOS FASES (medido: `love` 11,5s → 0,2s): igual que
    `search_works`, el TRIGRAM del WHERE (`name %% nq`) sobre un token común barre
    ~190K nombres aunque el FTS ya casara. Se corre primero SOLO con FTS; solo si el
    FTS no devuelve NINGÚN artista mostrable (typo real) se reintenta con trigram.

    PORTADA (acotada): el nº de works mostrables NO usa un EXISTS correlacionado
    (`cover_images WHERE source='discogs'` que el planner convierte en un barrido de
    las ~235K filas discogs, medido ~2,8s aun con pocos candidatos), sino el mismo
    truco de `search_works`: se junta a `cover_images` restringido a los work-ids
    candidatos (`work_id = ANY(...)`, índice por work_id).
    """
    q = normalize_search_query(q)
    if not q or len(q) < _SEARCH_MIN_CHARS:
        return []
    prefix_ts = _prefix_tsquery(q) if prefix else None
    if prefix and not prefix_ts:
        return []

    def _run(use_trgm):
        tsq = ("to_tsquery('simple', %(prefix_ts)s)"
               if prefix else "plainto_tsquery('simple', p.uq)")
        trgm_or = ("OR lower(immutable_unaccent(a.name)) %% p.nq"
                   if use_trgm else "")
        sql = """
            WITH params AS MATERIALIZED (
                SELECT immutable_unaccent(%(q)s)        AS uq,
                       lower(immutable_unaccent(%(q)s)) AS nq
            ),
            cand AS MATERIALIZED (
                SELECT a.id, a.name, a.name_clean, a.kind, a.disambiguation, a.country,
                       a.is_primary, a.listeners, a.image_url,
                       ts_rank(a.search_doc, {tsq}) AS fts_rank
                FROM artists a, params p
                WHERE a.search_doc @@ {tsq}
                   {trgm_or}
                ORDER BY CASE WHEN a.name_clean = p.nq THEN 0 ELSE 1 END,
                         a.is_primary DESC,
                         ts_rank(a.search_doc, {tsq}) DESC,
                         a.listeners DESC NULLS LAST
                LIMIT %(cand_limit)s
            ),
            cand_works AS MATERIALIZED (
                -- Works candidatos (vinilo + tipo-búsqueda) de los artistas candidatos.
                -- Se conduce por `primary_artist_id = ANY(cand_ids)` (índice de works).
                SELECT w.id, w.primary_artist_id AS aid
                FROM works w
                WHERE w.primary_artist_id = ANY(ARRAY(SELECT id FROM cand))
                  AND w.has_vinyl = true
                  AND w.work_type = ANY(%(work_types)s::work_type[])
                  AND {album_track_ok_w}
            ),
            show_counts AS MATERIALIZED (
                -- nº de works MOSTRABLES por artista. La portada se comprueba
                -- restringiendo cover_images a los work-ids candidatos (índice por
                -- work_id), NO con un EXISTS que barrería las ~235K filas discogs.
                -- Solo aparecen artistas con ≥1 work mostrable (homónimos-basura caen).
                SELECT cw.aid, count(*) AS n_works
                FROM cand_works cw
                WHERE cw.id IN (
                    SELECT work_id FROM cover_images
                    WHERE source = 'discogs'
                      AND work_id = ANY(ARRAY(SELECT id FROM cand_works))
                )
                GROUP BY cw.aid
            ),
            deduped AS (
                -- Dedup de homónimos por nombre normalizado: canónico = is_primary,
                -- luego nº de works mostrables, luego listeners (no salen dos "Geese").
                SELECT DISTINCT ON (c.name_clean) c.*, sc.n_works
                FROM cand c JOIN show_counts sc ON sc.aid = c.id
                ORDER BY c.name_clean, c.is_primary DESC, sc.n_works DESC,
                         c.listeners DESC NULLS LAST
            )
            SELECT d.id,
                   {clean_name}   AS name,
                   d.kind,
                   {clean_disamb} AS disambiguation,
                   d.country, d.is_primary, d.listeners, d.image_url
            FROM deduped d, params p
            ORDER BY CASE WHEN d.name_clean = p.nq THEN 0 ELSE 1 END,
                     d.is_primary DESC,
                     d.fts_rank DESC,
                     d.listeners DESC NULLS LAST
            LIMIT %(limit)s
        """.format(album_track_ok_w=_album_track_ok_sql("w"),
                   trgm_or=trgm_or, tsq=tsq,
                   clean_name=_clean_artist_name_sql("d.name"),
                   clean_disamb=_clean_disambiguation_sql("d.disambiguation"))
        with _cursor() as cur:
            if use_trgm:
                cur.execute("SET LOCAL pg_trgm.similarity_threshold = %s"
                            % _TRGM_FALLBACK_THRESHOLD)
            cur.execute(sql, {
                "q": q,
                "prefix_ts": prefix_ts,
                "work_types": list(_SEARCH_WORK_TYPES),
                "cand_limit": _SEARCH_CAND_LIMIT,
                "limit": limit,
            })
            return cur.fetchall()

    rows = _run(use_trgm=False)
    if not rows and not prefix:  # sin fallback trigram en type-ahead (prefijo)
        rows = _run(use_trgm=True)
    return rows


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
               w.discogs_master_id,
               a.id   AS artist_id,
               {clean_artist_name} AS artist_name,
               {clean_artist_disamb} AS artist_disambiguation,
               vc.preferred_url   AS cover_url,
               vc.preferred_thumb AS cover_thumb,
               COALESCE(g.genres, ARRAY[]::text[]) AS genres,
               COALESCE(s.styles, ARRAY[]::text[]) AS styles
        FROM works w
        JOIN artists a ON a.id = w.primary_artist_id
        LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = w.id
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
    """.format(clean_artist_name=_clean_artist_name_sql("a.name"),
               clean_artist_disamb=_clean_disambiguation_sql("a.disambiguation"))
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
    """Tracklist normalizada de la edición REPRESENTATIVA de la work.

    Estrategia en dos pasos:

    1) EDICIÓN DE REFERENCIA (main_release del master Discogs). `work_main_release`
       (migración 052 de core) mapea work → discogs_release_id de la edición que
       Discogs marca como representativa del disco. Es el tracklist canónico: el
       álbum tal cual, no una caja de tomas alternativas. Cubre el 100% de los
       works con vinilo (todos tienen master). Si esa release está en nuestra BD
       con tracklist, se usa tal cual (cualquier formato: la lista de canciones
       es la misma).

    2) FALLBACK POR MODA. Para los raros sin main_release resoluble (master sin
       <main_release> en el dump, o edición de referencia que no tenemos), se
       coge la edición de vinilo cuyo nº de pistas es el MÁS FRECUENTE entre
       todas las ediciones de vinilo — el consenso de cientos de prensados es el
       álbum; las cajas/rarezas son ediciones sueltas con nº de pistas atípico.
       (NO el MÁXIMO: eso cogía la caja de lujo.) Empate → la mejor rellenada
       (más duraciones presentes). Sin vinilo con tracklist → [].

    Forma real de `tracklist_cache` (verificada core): array de
    `{title, position, duration, extraartists?}`. Se normaliza a
    `[{position, title, duration}]` (se descartan extraartists y entradas sin
    título; posición/duración pueden faltar → None).
    """
    sql_main = """
        SELECT r.tracklist_cache
        FROM work_main_release wmr
        JOIN releases r ON r.discogs_release_id = wmr.main_release_id
        WHERE wmr.work_id = %(work_id)s
          AND jsonb_typeof(r.tracklist_cache) = 'array'
          AND jsonb_array_length(r.tracklist_cache) > 0
        LIMIT 1
    """
    sql_mode = """
        SELECT r.tracklist_cache
        FROM releases r
        JOIN (
            SELECT jsonb_array_length(tracklist_cache) AS n
            FROM releases
            WHERE work_id = %(work_id)s
              AND format = 'vinyl'
              AND jsonb_typeof(tracklist_cache) = 'array'
              AND jsonb_array_length(tracklist_cache) > 0
            GROUP BY 1
            ORDER BY count(*) DESC, n ASC
            LIMIT 1
        ) m ON jsonb_array_length(r.tracklist_cache) = m.n
        WHERE r.work_id = %(work_id)s
          AND r.format = 'vinyl'
          AND jsonb_typeof(r.tracklist_cache) = 'array'
        ORDER BY (
            SELECT count(*) FROM jsonb_array_elements(r.tracklist_cache) e
            WHERE COALESCE(e->>'duration', '') <> ''
        ) DESC
        LIMIT 1
    """
    with _cursor() as cur:
        cur.execute(sql_main, {"work_id": work_id})
        row = cur.fetchone()
        if not row or not row["tracklist_cache"]:
            cur.execute(sql_mode, {"work_id": work_id})
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
    """Artista por id. None si no existe.

    El nombre sale SIN la "(N)" de Discogs (`Ace (11)` → `Ace`) y la
    `disambiguation` NUMÉRICA (la (N) de Discogs) se oculta (NULL) — solo se
    devuelve si es texto real."""
    sql = ("""
        SELECT a.id,
               {clean_name}   AS name,
               a.kind,
               {clean_disamb} AS disambiguation,
               a.country,
               a.is_primary,
               a.listeners,
               a.bio,
               a.tags,""".format(
            clean_name=_clean_artist_name_sql("a.name"),
            clean_disamb=_clean_disambiguation_sql("a.disambiguation")) + """
               -- Last.fm quitó las fotos de artista: la estrella placeholder
               -- (hash 2a96cbd8…) está colada en image_url de ~38K artistas. La
               -- tratamos como SIN foto para que el front muestre el monograma.
               CASE WHEN a.image_url LIKE '%%2a96cbd8b46e442fc41c2b86b821562f%%'
                    THEN NULL ELSE a.image_url END AS image_url
        FROM artists a
        WHERE a.id = %(artist_id)s
    """)
    with _cursor() as cur:
        cur.execute(sql, {"artist_id": artist_id})
        return cur.fetchone()


def get_artist_discography(artist_id, limit=40):
    """Discografía en vinilo del artista, cumpliendo la regla TRANSVERSAL (vinilo +
    álbum/EP + anti-single + PORTADA de Discogs). Devuelve un dict:
        {"works": [filas a mostrar, con portada],
         "missing_cover_ids": [ids de candidatos SIN portada, para encolar]}

    Orden por escuchas: lastfm_playcount DESC NULLS LAST, releases_count DESC
    NULLS LAST (NUNCA cronológico — contrato del proyecto). El playcount crudo NO
    se devuelve al render (regla de números).

    CONVERGENCIA: se calculan los candidatos (vinilo+álbum+anti-single) SIN el
    filtro de portada; los que aún no tienen portada de Discogs van en
    `missing_cover_ids` (el router los encola) y los que sí, en `works`.
    """
    sql = """
        WITH cand AS MATERIALIZED (
            SELECT w.id, w.title, w.work_type, w.year, w.releases_count,
                   w.lastfm_playcount
            FROM works w
            WHERE w.primary_artist_id = %(artist_id)s
              AND w.has_vinyl = true
              AND w.work_type = ANY(%(work_types)s::work_type[])
              AND {album_track_ok}
            ORDER BY w.lastfm_playcount DESC NULLS LAST,
                     w.releases_count DESC NULLS LAST
            LIMIT %(cand_limit)s
        ),
        with_cover AS MATERIALIZED (
            SELECT DISTINCT work_id FROM cover_images
            WHERE source = 'discogs'
              AND work_id = ANY(ARRAY(SELECT id FROM cand))
        )
        SELECT c.id, c.title, c.work_type, c.year, c.releases_count,
               (c.id IN (SELECT work_id FROM with_cover)) AS has_cover,
               vc.preferred_thumb AS cover_thumb,
               vc.preferred_url   AS cover_url
        FROM cand c
        LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb
                   FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = c.id
        ORDER BY c.lastfm_playcount DESC NULLS LAST,
                 c.releases_count DESC NULLS LAST
    """.format(album_track_ok=_album_track_ok_sql("w"))
    with _cursor() as cur:
        cur.execute(sql, {
            "artist_id": artist_id,
            "work_types": list(_DISCOGRAPHY_WORK_TYPES),
            "cand_limit": max(limit * 3, _SEARCH_CAND_LIMIT),
        })
        rows = cur.fetchall()
    works, missing = [], []
    for r in rows:
        r = dict(r)
        has_cover = r.pop("has_cover", False)
        if has_cover:
            r["has_discogs"] = True
            if len(works) < limit:
                works.append(r)
        else:
            missing.append(r["id"])
    return {"works": works, "missing_cover_ids": missing}


# ---------------------------------------------------------------------------
# BÚSQUEDA POR SELECCIÓN (multi-select) — §6 del spec
# ---------------------------------------------------------------------------
#
# El buscador nuevo deja seleccionar artistas y discos como CHIPS y produce:
#   (1) por cada ARTISTA seleccionado, sus 3 mejores álbumes en vinilo NO poseídos;
#   (2) recomendaciones COMBINADAS de co-escucha desde las semillas (artistas + los
#       artistas de los works seleccionados), agregadas como recommend_for_user.
# Todo con la regla transversal (vinilo + álbum/EP + anti-single + portada +
# enqueue). La resolución de posesión solo aplica si el usuario tiene colección.


def top_works_for_artists(artist_ids, per_artist=3, exclude_user_id=None):
    """Los `per_artist` mejores álbumes en vinilo de cada artista seleccionado, NO
    poseídos (si `exclude_user_id`). Regla transversal + convergencia.

    Devuelve {"blocks": [{artist_id, artist_name, works:[...]}],
              "missing_cover_ids": [...]}. Orden de works por escuchas/ediciones.
    Los artistas se devuelven en el ORDEN de `artist_ids` recibido.
    """
    ids = [int(a) for a in (artist_ids or []) if a is not None]
    if not ids:
        return {"blocks": [], "missing_cover_ids": []}
    with _cursor() as cur:
        owned = _owned_work_ids(cur, exclude_user_id) if exclude_user_id else []
        cur.execute("""
            WITH sel AS (
                SELECT unnest(%(ids)s::bigint[]) AS artist_id
            ),
            ranked AS MATERIALIZED (
                SELECT w.id, w.title, w.work_type, w.year, w.releases_count,
                       w.primary_artist_id AS artist_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY w.primary_artist_id
                           ORDER BY w.lastfm_playcount DESC NULLS LAST,
                                    w.releases_count DESC NULLS LAST) AS rn
                FROM works w
                JOIN sel ON sel.artist_id = w.primary_artist_id
                WHERE w.has_vinyl = true
                  AND w.work_type = ANY(%(work_types)s::work_type[])
                  AND NOT (w.id = ANY(%(owned)s::bigint[]))
                  AND {album_track_ok_w}
            ),
            picked AS MATERIALIZED (
                SELECT * FROM ranked WHERE rn <= %(pool)s
            ),
            with_cover AS MATERIALIZED (
                SELECT DISTINCT work_id FROM cover_images
                WHERE source = 'discogs'
                  AND work_id = ANY(ARRAY(SELECT id FROM picked))
            )
            SELECT p.id, p.title, p.work_type, p.year, p.releases_count,
                   p.artist_id, a.name AS artist_name, p.rn,
                   (p.id IN (SELECT work_id FROM with_cover)) AS has_cover,
                   vc.preferred_thumb AS cover_thumb, vc.preferred_url AS cover_url
            FROM picked p
            JOIN artists a ON a.id = p.artist_id
            LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb
                       FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = p.id
            ORDER BY p.artist_id, p.rn
        """.format(album_track_ok_w=_album_track_ok_sql("w")),
            {"ids": ids, "work_types": list(_DISCOGRAPHY_WORK_TYPES),
             "owned": owned or [0],
             "pool": max(per_artist * _COVER_POOL_FACTOR, 12)})
        rows = cur.fetchall()

    by_artist, missing = {}, []
    for r in rows:
        r = dict(r)
        aid = r["artist_id"]
        if r.pop("has_cover", False):
            slot = by_artist.setdefault(aid, {
                "artist_id": aid, "artist_name": r["artist_name"], "works": []})
            if len(slot["works"]) < per_artist:
                r["has_discogs"] = True
                r.pop("rn", None)
                slot["works"].append(r)
        else:
            missing.append(r["id"])
    # Preservar el orden de selección; solo bloques con al menos un work mostrable.
    blocks = [by_artist[a] for a in ids if a in by_artist and by_artist[a]["works"]]
    return {"blocks": blocks, "missing_cover_ids": missing}


def coescucha_from_seed_artists(seed_artist_ids, limit=12, exclude_user_id=None):
    """Recomendación COMBINADA de co-escucha desde semillas EXPLÍCITAS de artistas.

    Espejo de `recommend_for_user` pero las semillas son los `seed_artist_ids`
    (artistas seleccionados + los artistas de los works seleccionados) en vez de la
    colección. Agrega afines del grafo `lastfm_similar_artists` (score = Σ match),
    excluye los propios seeds y — si `exclude_user_id` — los artistas ya poseídos,
    y por cada candidato su mejor obra en vinilo no poseída. Regla transversal +
    convergencia. Devuelve {"works", "missing_cover_ids"}. Funciona sin login.
    """
    seeds = [int(a) for a in (seed_artist_ids or []) if a is not None]
    if not seeds:
        return {"works": [], "missing_cover_ids": []}
    with _cursor() as cur:
        owned_works = _owned_work_ids(cur, exclude_user_id) if exclude_user_id else []
        owned_artists = _owned_artist_ids(cur, exclude_user_id) if exclude_user_id else []
        cur.execute("""
            WITH seeds AS (
                SELECT unnest(%(seeds)s::bigint[]) AS aid
            ),
            excluded_artists AS (
                SELECT aid FROM seeds
                UNION SELECT unnest(%(owned_artists)s::bigint[])
            ),
            cand AS (
                SELECT s.similar_artist_id AS aid,
                       sum(s.match) AS score,
                       (array_agg(sa.name ORDER BY s.match DESC))[1:2] AS anclas
                FROM lastfm_similar_artists s
                JOIN seeds sd ON sd.aid = s.artist_id
                JOIN artists sa ON sa.id = s.artist_id
                WHERE s.similar_artist_id IS NOT NULL
                  AND s.similar_artist_id NOT IN (SELECT aid FROM excluded_artists)
                GROUP BY s.similar_artist_id
            ),
            cand_top AS (
                SELECT * FROM cand ORDER BY score DESC LIMIT %(cand_lim)s
            ),
            best AS (
                SELECT c.aid, c.score, c.anclas, bw.id AS work_id
                FROM cand_top c
                CROSS JOIN LATERAL (
                    SELECT w.id
                    FROM works w
                    JOIN artists a ON a.id = w.primary_artist_id
                    WHERE w.primary_artist_id = c.aid
                      AND w.has_vinyl = true
                      AND w.work_type = ANY(%(work_types)s::work_type[])
                      AND NOT (w.id = ANY(%(owned_works)s::bigint[]))
                      AND (coalesce(w.lastfm_playcount, 0) > 0
                           OR coalesce(w.releases_count, 0) >= %(min_rc)s)
                      AND {album_track_ok}
                      AND {artist_ok}
                    ORDER BY w.lastfm_playcount DESC NULLS LAST, w.releases_count DESC
                    LIMIT 1
                ) bw
            )
            SELECT b.aid AS artist_id, a.name AS artist_name, b.score, b.anclas,
                   w.id, w.title, w.work_type, w.year, w.releases_count,
                   EXISTS (SELECT 1 FROM cover_images ci
                            WHERE ci.work_id = w.id AND ci.source='discogs') AS has_cover,
                   vc.preferred_thumb AS cover_thumb, vc.preferred_url AS cover_url
            FROM best b
            JOIN artists a ON a.id = b.aid
            JOIN works w ON w.id = b.work_id
            LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb
                       FROM cover_images WHERE source='discogs') vc ON vc.work_id = w.id
            ORDER BY b.score DESC
            LIMIT %(pool_limit)s
        """.format(album_track_ok=_album_track_ok_sql("w"),
                   artist_ok=_ARTIST_NOT_MORRALLA_SQL),
            {"seeds": seeds, "owned_works": owned_works or [0],
             "owned_artists": owned_artists or [0],
             "work_types": list(_RECO_WORK_TYPES),
             "cand_lim": _COESCUCHA_CAND_LIMIT, "min_rc": _COESCUCHA_MIN_RELEASES,
             "pool_limit": max(limit * _COVER_POOL_FACTOR, _COESCUCHA_CAND_LIMIT)})
        rows = cur.fetchall()

    works, missing = [], []
    for r in rows:
        item = dict(r)
        anclas = item.pop("anclas", None)
        item.pop("score", None)
        item["porque"] = _coescucha_porque(anclas) or "en la onda de tu selección"
        if item.pop("has_cover", False):
            if len(works) < limit:
                item["has_discogs"] = True
                works.append(item)
        else:
            missing.append(item["id"])
    return {"works": works, "missing_cover_ids": missing}


def works_primary_artists(work_ids):
    """Para works seleccionados, su primary_artist_id (para sembrar co-escucha).
    Devuelve lista de artist_ids (dedup, orden estable). Lista vacía → []."""
    ids = [int(w) for w in (work_ids or []) if w is not None]
    if not ids:
        return []
    with _cursor() as cur:
        cur.execute(
            "SELECT DISTINCT primary_artist_id AS aid FROM works "
            "WHERE id = ANY(%(ids)s) AND primary_artist_id IS NOT NULL",
            {"ids": ids})
        return [r["aid"] for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Precios (marketplace_listings)
# ---------------------------------------------------------------------------

def get_prices_for_work(work_id, max_age_days=None):
    """Listings de tienda para la obra, ordenados por precio ASC.

    Match por `marketplace_listings.work_id`, RESUELTO una vez en el port de core
    (`ingest/port_store_listings.resolve_work_ids`, migración 056): artist_text
    normalizado + título limpio → obra del MISMO artista (exacto OR trigram>0.55).
    Antes se casaba EN CALIENTE por artist_id + título difuso (trigram>0.35 OR
    substring) sobre título de la work y de sus releases como semillas: semillas
    contaminadas ("Abbey Road (3LP Anniversary Edition)") cruzaban álbumes del
    mismo artista (Abbey Road mostraba precios de With The Beatles / Sgt Pepper /
    White Album). Con el enlace pre-resuelto ese cruce desaparece y la consulta
    es un simple index-scan por work_id.

    Cada fila lleva `data_as_of` (fecha de last_seen) y `stale` (bool) según
    STORE_FRESHNESS_MAX_DAYS (o `max_age_days` si se pasa). Sin datos → [].
    Nunca inventa precio.
    """
    stale_days = max_age_days if max_age_days is not None else STORE_FRESHNESS_MAX_DAYS

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
        WHERE ml.work_id = %(work_id)s
          AND ml.price_cents > 0
        ORDER BY ml.price_cents ASC
    """
    with _cursor() as cur:
        cur.execute(sql, {
            "work_id": work_id,
            "stale_days": stale_days,
        })
        return cur.fetchall()


def cheapest_prices_for_works(work_ids, max_age_days=None):
    """Precio MÁS BARATO en tiendas ES por obra, EN LOTE (para las tarjetas).

    Match por `marketplace_listings.work_id` (pre-resuelto en el port de core,
    migración 056) — EXACTAMENTE el mismo enlace que `get_prices_for_work`, de modo
    que la tarjeta y la ficha NUNCA discrepan. (Antes casaba en caliente por
    artist_id + título difuso trigram>0.35/substring, lo que cruzaba álbumes del
    mismo artista: una tarjeta podía anunciar el precio de OTRO disco.)

    Elige el listing NO envejecido más barato; si todos están stale, cae al más
    barato y lo marca `stale=True` (para no anunciar como "el más barato" un
    listing fantasma cuando existe uno vivo más caro). Devuelve
    {work_id: {price_cents, currency, url, source, stale}} solo para las obras con
    algún listing con precio. Una sola query (evita el N+1). Lista vacía → {}.
    """
    ids = [int(i) for i in (work_ids or []) if i is not None]
    if not ids:
        return {}
    stale_days = max_age_days if max_age_days is not None else STORE_FRESHNESS_MAX_DAYS
    sql = """
        SELECT DISTINCT ON (ml.work_id)
               ml.work_id, ml.price_cents, ml.currency, ml.url, ml.source,
               (ml.last_seen_at < (now() - make_interval(days => %(stale_days)s))) AS stale
        FROM marketplace_listings ml
        WHERE ml.work_id = ANY(%(ids)s)
          AND ml.price_cents > 0
        ORDER BY ml.work_id,
                 (ml.last_seen_at < (now() - make_interval(days => %(stale_days)s))) ASC,
                 ml.price_cents ASC
    """
    with _cursor() as cur:
        cur.execute(sql, {"ids": ids, "stale_days": stale_days})
        return {r["work_id"]: dict(r) for r in cur.fetchall()}


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
    /artista tenga sentido). Sin match → el nombre no aparece (la vista lo pinta
    como texto plano).

    RENDIMIENTO (crítico): el match se hace contra `artists.name_clean` (columna
    normalizada CON índice btree `idx_artists_name_clean`), NO contra
    `lower(immutable_unaccent(a.name))` — esa expresión NO está indexada y forzaba
    un seq-scan de artists POR CADA nombre (medido: 8 nombres → ~3-11s, bloqueaba
    la ficha entera). `name_clean` además quita el prefijo "The" y la "(N)" de
    Discogs, así que se prueba `norm` y su variante sin "the " (ambas por índice) →
    superconjunto de lo que casaba antes (enlaza también homónimos con "(N)") en
    ~0s. La crítica escribe el nombre canónico; no hace falta trigram.
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
          ON a.name_clean IN (n.norm, regexp_replace(n.norm, '^the ', ''))
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


def _split_by_discogs_cover(cur, ranked, limit):
    """Aplica la regla TRANSVERSAL de PORTADA a filas YA rankeadas (reco/afines).

    Entrada: `ranked` = filas de obra ya ordenadas por relevancia (una lista más
    LARGA que `limit`, para que tras el filtro de portada queden suficientes).
    Consulta EN BATCH (una query) qué ids tienen portada de Discogs y devuelve:
        (works, missing_cover_ids)
    donde `works` son las primeras `limit` filas CON portada (marcadas
    `has_discogs=True` para el front) y `missing_cover_ids` los ids de las que aún
    NO la tienen (el router los encola → convergencia).
    """
    if not ranked:
        return [], []
    ids = [r["id"] for r in ranked]
    cur.execute(
        "SELECT DISTINCT work_id FROM cover_images "
        "WHERE source = 'discogs' AND work_id = ANY(%(ids)s)",
        {"ids": ids},
    )
    with_cover = {row["work_id"] for row in cur.fetchall()}
    works, missing = [], []
    for r in ranked:
        if r["id"] in with_cover:
            if len(works) < limit:
                r = dict(r)
                r["has_discogs"] = True
                works.append(r)
        else:
            missing.append(r["id"])
    return works, missing


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
    LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = w.id
    WHERE {album_track_ok}
    ORDER BY cand.dist
""".format(album_track_ok=_album_track_ok_sql("w"))


def recommend_similar_to_work(work_id, limit=12, exclude_user_id=None):
    """Vinilos afines a una OBRA por embedding precalculado.

    ANN sobre `works.embedding <=> (embedding del seed)`, filtrando a vinilo +
    obra de verdad (studio_album/ep), EXCLUYENDO el mismo primary_artist_id que la
    semilla (los vecinos crudos serían variantes del propio artista) y la propia
    semilla. Trae candidatos holgados por distancia, capa 1 por artista y re-rankea
    con distancia+popularidad (ver _rerank_candidates).

    `exclude_user_id` (M3a): si se pasa, EXCLUYE además los works de la colección
    de ese usuario — la reco anónima deja de recomendar lo que el logueado ya tiene.

    RENDIMIENTO (dos fases): el KNN corre sobre `works` PURO (sin joins) con el
    embedding del seed como literal `::vector` → usa el índice HNSW; la portada
    (cara) y `artists` solo se juntan DESPUÉS, sobre el puñado de candidatos ya
    capados por artista. Semántica idéntica a la versión de un solo pase.

    Regla TRANSVERSAL de PORTADA + CONVERGENCIA: se rerankea un pool MÁS AMPLIO que
    `limit`, se parte por portada de Discogs (`_split_by_discogs_cover`) → `works`
    (con portada) + `missing_cover_ids` (sin, para encolar). Devuelve un dict
    {"works", "missing_cover_ids"}. Seed sin embedding → dict vacío honesto.
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
              AND NOT (w.id = ANY(%(owned)s::bigint[]))
              AND {artist_ok}
            ORDER BY w.primary_artist_id, w.embedding <=> %(seed)s::vector
            LIMIT %(cand)s
        )
    """.format(artist_ok=_ARTIST_NOT_MORRALLA_SQL)
    sql = cand_sql + _RECO_PHASE2_SQL

    with _cursor() as cur:
        seed_emb, seed_artist, seed_title = _seed_embedding_for_work(cur, work_id)
        if seed_emb is None:
            return {"works": [], "missing_cover_ids": []}
        seed_title = seed_title or "esta obra"
        owned = _owned_work_ids(cur, exclude_user_id) if exclude_user_id else []

        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, {
            "work_id": work_id,
            "seed": seed_emb,
            "seed_artist": seed_artist,
            "work_types": list(_RECO_WORK_TYPES),
            "owned": owned or [0],
            "cand": _ANN_CANDIDATE_LIMIT,
        })
        rows = cur.fetchall()

        ranked = _rerank_candidates(rows, limit * _COVER_POOL_FACTOR)
        works, missing = _split_by_discogs_cover(cur, ranked, limit)
    for r in works:
        r["porque"] = "afín en género y estilo a {}".format(seed_title)
    return {"works": works, "missing_cover_ids": missing}


def recommend_similar_to_artist(artist_id, limit=12, exclude_user_id=None):
    """Vinilos afines a un ARTISTA por centroide de sus embeddings.

    Centroide = avg de los embeddings de sus works con vinilo/obra-de-verdad. Si
    el centroide falla (sin works embebidos) → DEGRADA a la semilla de su obra más
    popular con embedding. Vecinos con primary_artist_id <> artist_id, mismas reglas
    de filtro/cap. `porque` = "en la onda de {artista}". Sin semilla posible → [].

    `exclude_user_id` (M3a): si se pasa, EXCLUYE los works de la colección de ese
    usuario (la reco anónima no recomienda lo que el logueado ya tiene).
    """
    # Dos fases: el SEED (centroide o embedding de la obra más popular) se
    # calcula/trae a Python como LITERAL ::vector; luego KNN puro sobre works y
    # cap+portada sobre lo reducido (ver recommend_similar_to_work).
    with _cursor() as cur:
        cur.execute("SELECT name FROM artists WHERE id = %(id)s", {"id": artist_id})
        arow = cur.fetchone()
        if not arow:
            return {"works": [], "missing_cover_ids": []}
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
                return {"works": [], "missing_cover_ids": []}
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
                  AND NOT (w.id = ANY(%(owned)s::bigint[]))
                  AND {artist_ok}
                ORDER BY w.primary_artist_id, w.embedding <=> %(seed)s::vector
                LIMIT %(cand)s
            )
        """.format(artist_ok=_ARTIST_NOT_MORRALLA_SQL)
        sql = cand_sql + _RECO_PHASE2_SQL

        owned = _owned_work_ids(cur, exclude_user_id) if exclude_user_id else []
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, {
            "artist_id": artist_id,
            "seed": seed_emb,
            "owned": owned or [0],
            "work_types": list(_RECO_WORK_TYPES),
            "cand": _ANN_CANDIDATE_LIMIT,
        })
        rows = cur.fetchall()

        ranked = _rerank_candidates(rows, limit * _COVER_POOL_FACTOR)
        works, missing = _split_by_discogs_cover(cur, ranked, limit)
    for r in works:
        r["porque"] = "en la onda de {}".format(artist_name)
    return {"works": works, "missing_cover_ids": missing}


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
            return {"works": [], "missing_cover_ids": []}
        cur.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
        cur.execute(sql, {
            "work_id": work_id,
            "seed": seed_emb,
            "seed_artist": seed_artist,
            "work_types": list(_RECO_WORK_TYPES),
            "cand": _ANN_CANDIDATE_LIMIT,
        })
        rows = cur.fetchall()

        ranked = _rerank_candidates(rows, limit * _COVER_POOL_FACTOR)
        works, missing = _split_by_discogs_cover(cur, ranked, limit)
    for r in works:
        r["porque"] = "la crítica lo sitúa en una vibra afín"
    return {"works": works, "missing_cover_ids": missing}


# ---------------------------------------------------------------------------
# Recomendación por MOOD (léxico curado → styles + tags whitelisted)
# ---------------------------------------------------------------------------

def works_by_styles_and_tags(style_names, tag_whitelist, limit=20,
                             per_artist_cap=2, exclude_user_id=None):
    """Works con vinilo que casan un conjunto de STYLES (base) + tags whitelisted.

    Base fiable = `work_styles` con styles limpios. Los tags (folksonomía Last.fm,
    ruidosos) solo SUMAN señal si están en la whitelist del mood — nunca deciden
    solos. Cap por artista para diversidad. El número de styles/tags casados va en
    `match_count` (para el `porque`), pero NUNCA se expone playcount crudo.

    RANKING (score BALANCEADO): `(style_hits + tag_hits) + ln(1+playcount)/4`. Antes
    ordenaba SOLO por nº de styles/tags casados, y como las bandas OSCURAS están
    sobre-etiquetadas de género (casan los 4 styles del mood) y las conocidas suelen
    casar 1-2, salían discos rarísimos. El término log de popularidad (playcount)
    pesa ~como 1 style-hit por cada e⁴≈55× de escuchas, así que a igualdad de vibra
    gana el disco CONOCIDO, sin que un megahit fuera-de-vibra (style_hits=1) desplace
    a los realmente afines. Divisor 4 elegido por prueba (ver moods de referencia).

    `exclude_user_id` (M3a): excluye los works de la colección de ese usuario (mood
    para el logueado no repite lo que ya tiene).

    Regla TRANSVERSAL de PORTADA + CONVERGENCIA: los candidatos se calculan SIN el
    filtro de portada; se parten por portada de Discogs → `works` (con) +
    `missing_cover_ids` (sin, para encolar). Devuelve un dict {"works",
    "missing_cover_ids"}. Sin styles → dict vacío (el caller degrada honesto).
    """
    style_names = [s for s in (style_names or []) if s]
    tag_whitelist = [t.lower() for t in (tag_whitelist or []) if t]
    if not style_names:
        return {"works": [], "missing_cover_ids": []}

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
              -- RENDIMIENTO: solo works con playcount de Last.fm. Estilos comunes
              -- (garage/indie/punk…) casan ~87K works y se rankean TODOS para elegir
              -- ~20; como el ranking pesa por popularidad, los que no tienen
              -- playcount NUNCA llegan arriba. Prefiltrar aquí recorta el candidato
              -- ~20× (medido: top-12 IDÉNTICO en los 14 moods; query 0,9s→0,4s).
              AND w.lastfm_playcount IS NOT NULL
              AND NOT (w.id = ANY(%(owned)s::bigint[]))
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
                       ORDER BY ((s.style_hits + s.tag_hits)
                                 + ln(1 + COALESCE(s.lastfm_playcount, 0)) / 4.0) DESC,
                                s.releases_count DESC NULLS LAST
                   ) AS rn_artist
            FROM scored s
        ),
        picked AS (
            -- Se toma MARGEN (cand_limit = limit*3) porque el filtro de single
            -- disfrazado (album_track_ok) se aplica DESPUÉS, sobre este puñado ya
            -- rankeado/capado — NO sobre todo `scored` (ahí el EXISTS de tracklist
            -- corría sobre miles de filas y disparaba la latencia a ~21s).
            SELECT id, title, work_type, year, releases_count, lastfm_playcount,
                   primary_artist_id AS artist_id, artist_name,
                   style_hits, tag_hits, matched_styles
            FROM ranked
            WHERE rn_artist <= %(cap)s
            ORDER BY ((style_hits + tag_hits)
                      + ln(1 + COALESCE(lastfm_playcount, 0)) / 4.0) DESC,
                     releases_count DESC NULLS LAST
            LIMIT %(cand_limit)s
        ),
        albumok AS MATERIALIZED (
            -- Candidatos disco-de-verdad (anti-single), aún SIN filtro de portada.
            SELECT p.id, p.title, p.work_type, p.year, p.releases_count,
                   p.lastfm_playcount, p.artist_id, p.artist_name,
                   p.style_hits, p.tag_hits, p.matched_styles
            FROM picked p
            JOIN works w ON w.id = p.id
            WHERE {album_track_ok}
        ),
        covers_c AS MATERIALIZED (
            -- Portadas discogs de los candidatos (acotado por work_id), UNA vez:
            -- has_cover + URLs. Evita el LEFT JOIN nested-loop sobre las ~235K filas
            -- discogs (ver misma nota en search_works).
            SELECT DISTINCT ON (work_id) work_id,
                   url AS preferred_url, url_thumb AS preferred_thumb
            FROM cover_images
            WHERE source = 'discogs'
              AND work_id = ANY(ARRAY(SELECT id FROM albumok))
        )
        SELECT ao.id, ao.title, ao.work_type, ao.year, ao.releases_count,
               ao.artist_id, ao.artist_name,
               (vc.work_id IS NOT NULL) AS has_cover,
               vc.preferred_thumb AS cover_thumb,
               vc.preferred_url   AS cover_url,
               ao.style_hits, ao.tag_hits, ao.matched_styles
        FROM albumok ao
        LEFT JOIN covers_c vc ON vc.work_id = ao.id
        ORDER BY ((ao.style_hits + ao.tag_hits)
                  + ln(1 + COALESCE(ao.lastfm_playcount, 0)) / 4.0) DESC,
                 ao.releases_count DESC NULLS LAST
    """.format(artist_ok=_ARTIST_NOT_MORRALLA_SQL,
               album_track_ok=_album_track_ok_sql("w"))
    with _cursor() as cur:
        owned = _owned_work_ids(cur, exclude_user_id) if exclude_user_id else []
        cur.execute(sql, {
            "styles": style_names,
            "tags": tag_whitelist,
            "work_types": list(_RECO_WORK_TYPES),
            "cap": per_artist_cap,
            "limit": limit,
            "cand_limit": max(limit * _COVER_POOL_FACTOR, _SEARCH_CAND_LIMIT),
            "owned": owned or [0],
        })
        rows = cur.fetchall()
    works, missing = [], []
    for r in rows:
        r = dict(r)
        has_cover = r.pop("has_cover", False)
        if has_cover:
            r["has_discogs"] = True
            if len(works) < limit:
                works.append(r)
        else:
            missing.append(r["id"])
    return {"works": works, "missing_cover_ids": missing}


# ---------------------------------------------------------------------------
# CAPA DE USUARIO — sesiones + invitado (M3a)
# ---------------------------------------------------------------------------
#
# Esta es la ÚNICA parte de la app que ESCRIBE en core, y solo en las tablas de
# usuario (`app_users`, `user_sessions`) — es su función, NO es DDL (las tablas
# ya existen). El catálogo (works/releases/artists/…) sigue siendo SOLO LECTURA.
#
# OAuth de Discogs/Last.fm es M3b (necesita credenciales + navegador): aquí NO se
# escribe en `user_oauth_credentials`; solo se lee para saber si un usuario tiene
# identidad vinculada.

import secrets

# Vida de la sesión (días). El token es opaco y seguro (secrets.token_urlsafe).
SESSION_TTL_DAYS = int(os.environ.get("VINILOGY_SESSION_TTL_DAYS", "90"))


def create_guest_user():
    """Crea una cuenta LIGERA (invitado): fila `app_users` con email/display_name
    NULL. Devuelve el id nuevo. Sin identidad OAuth (eso vincula M3b)."""
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO app_users (email, display_name) VALUES (NULL, NULL) "
            "RETURNING id"
        )
        return cur.fetchone()["id"]


def create_session(user_id, ttl_days=None):
    """Abre una sesión server-side para `user_id`. Token aleatorio SEGURO
    (`secrets.token_urlsafe`, 32 bytes ≈ 43 chars). Guarda expiry a `ttl_days`
    (def. SESSION_TTL_DAYS). Devuelve el token."""
    ttl = ttl_days if ttl_days is not None else SESSION_TTL_DAYS
    token = secrets.token_urlsafe(32)
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO user_sessions (session_token, user_id, expires_at) "
            "VALUES (%(t)s, %(u)s, now() + make_interval(days => %(d)s))",
            {"t": token, "u": user_id, "d": ttl},
        )
    return token


def get_user_by_session(token):
    """Resuelve un token de sesión → app_user (dict) o None.

    Valida expiry (expires_at NULL = no expira; futuro = válida). Al validar,
    refresca `last_used_at`. Token inexistente/expirado → None (sin excepción).
    Adjunta `providers` = lista de proveedores OAuth vinculados (para saber si el
    usuario es invitado puro o ya tiene identidad; SOLO lectura).
    """
    if not token:
        return None
    with _cursor() as cur:
        cur.execute(
            """
            UPDATE user_sessions
               SET last_used_at = now()
             WHERE session_token = %(t)s
               AND (expires_at IS NULL OR expires_at > now())
            RETURNING user_id
            """,
            {"t": token},
        )
        row = cur.fetchone()
        if not row:
            return None
        user_id = row["user_id"]
        cur.execute(
            """
            SELECT u.id, u.email, u.display_name,
                   u.collection_value_min, u.collection_value_median,
                   u.collection_value_max, u.collection_value_currency,
                   u.collection_value_updated_at,
                   COALESCE(
                     (SELECT array_agg(oc.provider::text ORDER BY oc.provider::text)
                        FROM user_oauth_credentials oc WHERE oc.user_id = u.id),
                     ARRAY[]::text[]
                   ) AS providers
            FROM app_users u
            WHERE u.id = %(u)s
            """,
            {"u": user_id},
        )
        return cur.fetchone()


def get_app_user(user_id):
    """app_user (dict) por id, con `providers`. None si no existe."""
    with _cursor() as cur:
        cur.execute(
            """
            SELECT u.id, u.email, u.display_name,
                   u.collection_value_min, u.collection_value_median,
                   u.collection_value_max, u.collection_value_currency,
                   u.collection_value_updated_at,
                   COALESCE(
                     (SELECT array_agg(oc.provider::text ORDER BY oc.provider::text)
                        FROM user_oauth_credentials oc WHERE oc.user_id = u.id),
                     ARRAY[]::text[]
                   ) AS providers
            FROM app_users u
            WHERE u.id = %(u)s
            """,
            {"u": user_id},
        )
        return cur.fetchone()


def export_user_data(user_id):
    """Vuelca TODOS los datos personales de un usuario para la portabilidad GDPR
    (derecho de acceso, art. 15/20). Devuelve un dict serializable, o None si el
    usuario no existe.

    NO incluye los tokens OAuth secretos (oauth_token/oauth_token_secret/
    session_key/oauth2_*): son credenciales vivas de terceros, no datos del sujeto,
    y no deben viajar en un fichero descargable. Solo se exportan los metadatos de
    conexión (proveedor, usuario y cuenta en el proveedor, última actualización).
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, email, display_name, last_login_at, updated_at,
                   collection_value_min, collection_value_median,
                   collection_value_max, collection_value_currency,
                   collection_value_updated_at
            FROM app_users WHERE id = %(u)s
            """,
            {"u": user_id},
        )
        profile = cur.fetchone()
        if not profile:
            return None
        cur.execute(
            """
            SELECT provider::text AS provider, provider_username,
                   provider_account_id, updated_at
            FROM user_oauth_credentials WHERE user_id = %(u)s
            ORDER BY provider::text
            """,
            {"u": user_id},
        )
        connections = cur.fetchall()
        cur.execute(
            """
            SELECT wl.work_id, w.title, wl.created_at AS saved_at
            FROM user_wishlist wl
            LEFT JOIN works w ON w.id = wl.work_id
            WHERE wl.user_id = %(u)s
            ORDER BY wl.created_at DESC
            """,
            {"u": user_id},
        )
        wishlist = cur.fetchall()
    return {
        "profile": dict(profile),
        "connections": [dict(c) for c in connections],
        "wishlist": [dict(x) for x in wishlist],
    }


def delete_session(token):
    """Cierra una sesión (logout). No-op si no existe."""
    if not token:
        return
    with _cursor() as cur:
        cur.execute("DELETE FROM user_sessions WHERE session_token = %(t)s",
                    {"t": token})


def delete_user_and_sessions(user_id):
    """Borra un usuario y TODO lo suyo por CASCADE (sesiones, credenciales OAuth y
    wishlist). Lo usa "Borrar cuenta" en /cuenta y la limpieza de tests. Sin efecto
    si el id no existe."""
    with _cursor() as cur:
        cur.execute("DELETE FROM app_users WHERE id = %(u)s", {"u": user_id})


# ---------------------------------------------------------------------------
# CAPA DE USUARIO — wishlist (M3c · Fase 1)
# ---------------------------------------------------------------------------
#
# Escritura ACOTADA a `user_wishlist` (dato propiedad de v2; ver migración
# migrations/001_user_wishlist.sql). El catálogo sigue SOLO LECTURA: aquí solo se
# guardan pares (user_id, work_id). La hidratación a tarjetas (portada/precio) la
# hace la vista reutilizando catalog/covers/pricing, no estas funciones.


def wishlist_add(user_id, work_id):
    """Guarda un disco en la wishlist del usuario. Idempotente (ON CONFLICT)."""
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO user_wishlist (user_id, work_id) VALUES (%(u)s, %(w)s) "
            "ON CONFLICT (user_id, work_id) DO NOTHING",
            {"u": user_id, "w": work_id},
        )


def wishlist_remove(user_id, work_id):
    """Quita un disco de la wishlist. No-op si no estaba."""
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM user_wishlist WHERE user_id = %(u)s AND work_id = %(w)s",
            {"u": user_id, "w": work_id},
        )


def wishlist_work_ids(user_id):
    """IDs de la wishlist del usuario, lo más reciente primero. [] si vacía."""
    with _cursor() as cur:
        cur.execute(
            "SELECT work_id FROM user_wishlist WHERE user_id = %(u)s "
            "ORDER BY created_at DESC",
            {"u": user_id},
        )
        return [r["work_id"] for r in cur.fetchall()]


def wishlist_add_many(user_id, work_ids):
    """Fusiona una lista de work_ids en la wishlist (import tras conectar cuenta).

    Ignora ids que no existan en el catálogo (FK) o ya guardados. Devuelve cuántas
    filas se insertaron de verdad. [] / None → 0 sin tocar la BD.
    """
    ids = [int(w) for w in (work_ids or []) if str(w).isdigit()]
    if not ids:
        return 0
    with _cursor() as cur:
        # Solo ids que existan como work (evita romper la FK y descarta basura del
        # localStorage). El INSERT con SELECT resuelve todo en una query.
        cur.execute(
            """
            INSERT INTO user_wishlist (user_id, work_id)
            SELECT %(u)s, w.id FROM works w WHERE w.id = ANY(%(ids)s)
            ON CONFLICT (user_id, work_id) DO NOTHING
            """,
            {"u": user_id, "ids": ids},
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# CAPA DE USUARIO — credenciales OAuth + mapeo de identidad (M3b)
# ---------------------------------------------------------------------------
#
# Escritura ACOTADA a `user_oauth_credentials` (+ `app_users` para crear/tocar
# last_login) — es la función de la capa de usuario, NO es DDL (las tablas ya
# existen en core). El catálogo sigue SOLO LECTURA.
#
# El schema de core impone (verificado 8-jul-2026):
#   - UNIQUE (provider, provider_account_id)  → una identidad = un usuario.
#   - UNIQUE (user_id, provider)              → un usuario, una credencial/proveedor.
#   - CHECK user_oauth_creds_shape: discogs exige oauth_token+oauth_token_secret;
#     lastfm exige session_key. Los helpers de abajo respetan la forma por proveedor.


def find_oauth_credential(provider, provider_account_id):
    """Fila de credencial por (provider, provider_account_id) o None.

    Es el paso 2 de la regla de mapeo: si existe, su `user_id` es el dueño de la
    identidad (para Carlos: discogs 8383997 / lastfm 'aficcion' → user_id=1).
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, provider::text AS provider,
                   provider_account_id, provider_username
            FROM user_oauth_credentials
            WHERE provider = %(p)s::oauth_provider
              AND provider_account_id = %(acc)s
            """,
            {"p": provider, "acc": str(provider_account_id)},
        )
        return cur.fetchone()


def upsert_oauth_credential(user_id, provider, provider_account_id,
                            provider_username=None, oauth_token=None,
                            oauth_token_secret=None, session_key=None,
                            oauth2_access_token=None, oauth2_refresh_token=None,
                            oauth2_expires_at=None):
    """UPSERT de la credencial de un usuario para un proveedor (tokens frescos).

    Clave de conflicto = UNIQUE (user_id, provider): re-conectar el MISMO
    proveedor refresca los tokens en la fila existente en vez de duplicar. Los
    campos por proveedor respetan la CHECK del schema (discogs: token+secret;
    lastfm: session_key; google/OAuth2: oauth2_access_token). Devuelve el id de la
    credencial.
    """
    with _cursor() as cur:
        cur.execute(
            """
            INSERT INTO user_oauth_credentials
                (user_id, provider, provider_account_id, provider_username,
                 oauth_token, oauth_token_secret, session_key,
                 oauth2_access_token, oauth2_refresh_token, oauth2_expires_at,
                 updated_at)
            VALUES
                (%(uid)s, %(p)s::oauth_provider, %(acc)s, %(uname)s,
                 %(tok)s, %(sec)s, %(skey)s,
                 %(a2t)s, %(a2r)s, %(a2e)s, now())
            ON CONFLICT (user_id, provider) DO UPDATE
                SET provider_account_id  = EXCLUDED.provider_account_id,
                    provider_username    = EXCLUDED.provider_username,
                    oauth_token          = EXCLUDED.oauth_token,
                    oauth_token_secret   = EXCLUDED.oauth_token_secret,
                    session_key          = EXCLUDED.session_key,
                    oauth2_access_token  = EXCLUDED.oauth2_access_token,
                    oauth2_refresh_token = COALESCE(EXCLUDED.oauth2_refresh_token,
                                                    user_oauth_credentials.oauth2_refresh_token),
                    oauth2_expires_at    = EXCLUDED.oauth2_expires_at,
                    updated_at           = now()
            RETURNING id
            """,
            {"uid": user_id, "p": provider, "acc": str(provider_account_id),
             "uname": provider_username, "tok": oauth_token,
             "sec": oauth_token_secret, "skey": session_key,
             "a2t": oauth2_access_token, "a2r": oauth2_refresh_token,
             "a2e": oauth2_expires_at},
        )
        return cur.fetchone()["id"]


def delete_oauth_credential(user_id, provider):
    """Desvincula un proveedor de un usuario (desconectar en /cuenta). No-op si no
    existía. Devuelve cuántas filas se borraron (0/1)."""
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM user_oauth_credentials "
            "WHERE user_id = %(u)s AND provider = %(p)s::oauth_provider",
            {"u": user_id, "p": provider},
        )
        return cur.rowcount


def create_identified_user(display_name=None):
    """Crea un `app_users` NUEVO con identidad (display_name opcional). Devuelve el
    id. Es el paso 4 de la regla de mapeo (credencial nueva sin invitado)."""
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO app_users (email, display_name) VALUES (NULL, %(dn)s) "
            "RETURNING id",
            {"dn": display_name},
        )
        return cur.fetchone()["id"]


def set_display_name_if_empty(user_id, display_name):
    """Rellena `display_name` de un usuario SOLO si está vacío (no pisa lo que ya
    tenga). Usado al vincular identidad a un invitado. No-op si display_name None."""
    if not display_name:
        return
    with _cursor() as cur:
        cur.execute(
            "UPDATE app_users SET display_name = %(dn)s, updated_at = now() "
            "WHERE id = %(u)s AND (display_name IS NULL OR btrim(display_name) = '')",
            {"dn": display_name, "u": user_id},
        )


def touch_last_login(user_id):
    """Actualiza `app_users.last_login_at = now()` al abrir sesión por OAuth."""
    with _cursor() as cur:
        cur.execute(
            "UPDATE app_users SET last_login_at = now(), updated_at = now() "
            "WHERE id = %(u)s",
            {"u": user_id},
        )


def delete_oauth_credential(user_id, provider):
    """Borra la credencial (user_id, provider). Solo para LIMPIEZA de test."""
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM user_oauth_credentials "
            "WHERE user_id = %(u)s AND provider = %(p)s::oauth_provider",
            {"u": user_id, "p": provider},
        )


def user_collection_summary(user_id):
    """Resumen ligero de la colección de un usuario: nº ítems, nº resueltos a
    release, y desglose por formato físico real (release.format). Sin filas → 0s.
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS total,
                   count(uc.release_id) AS resolved,
                   count(*) FILTER (WHERE r.format = 'vinyl')    AS vinyl,
                   count(*) FILTER (WHERE r.format = 'cd')       AS cd,
                   count(*) FILTER (WHERE r.format NOT IN ('vinyl','cd')
                                      AND r.format IS NOT NULL)  AS other
            FROM user_collection uc
            LEFT JOIN releases r ON r.id = uc.release_id
            WHERE uc.user_id = %(u)s
            """,
            {"u": user_id},
        )
        return cur.fetchone()


def owned_formats_for_user(user_id):
    """work_id -> lista de formatos POSEÍDOS por el usuario ('vinyl'/'cd'), para
    marcar cualquier tarjeta/ficha con el flag "ya lo tienes".

    Misma base que la exclusión de colección (`_owned_work_ids`): posesión a nivel
    de OBRA por `release_id` resuelto, unido a `releases.work_id`; el formato sale de
    `releases.format` ('vinyl'/'cd'/…). Se agrega por work con bool_or para que una
    work con ediciones en dos formatos liste ambos. Sin filas → {}.

    La colección la puebla el pipeline de core desde Discogs (esta app no sincroniza),
    así que solo tiene sentido llamarlo para usuarios con Discogs conectado.
    """
    with _cursor() as cur:
        cur.execute(
            """
            SELECT r.work_id,
                   bool_or(r.format = 'vinyl') AS vinyl,
                   bool_or(r.format = 'cd')    AS cd
            FROM user_collection uc
            JOIN releases r ON r.id = uc.release_id
            WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL
            GROUP BY r.work_id
            """,
            {"u": user_id},
        )
        out = {}
        for row in cur.fetchall():
            fmts = []
            if row["vinyl"]:
                fmts.append("vinyl")
            if row["cd"]:
                fmts.append("cd")
            out[row["work_id"]] = fmts
        return out


# ---------------------------------------------------------------------------
# CAPA PERSONAL DE RECO — "Para ti" por GRAFO DE CO-ESCUCHA (Last.fm getSimilar)
# ---------------------------------------------------------------------------
#
# El "Para ti" ya NO es el centroide de gusto (promedio ciego de embeddings de la
# colección) — daba recomendaciones "puré" y rarunas. La señal buena es el GRAFO
# de co-escucha real `lastfm_similar_artists` (getSimilar, simétrico, de calidad
# demostrada) ya poblado en core:
#   The Strokes → garage/indie,  Idles → post-punk.
#
# Algoritmo (dos fases, medido ~130ms para user 1):
#   Fase 1 — AGREGACIÓN de co-escucha: por cada artista que el usuario POSEE, sus
#     afines del grafo; se agregan por artista candidato (score = Σ match, n_anclas
#     = cuántas de sus semillas lo apuntan, anclas = las 2 semillas de mayor match
#     para el `porque`). Se excluyen los artistas que ya posee. Orden por score.
#   Fase 2 — MEJOR OBRA por candidato sobre el conjunto YA REDUCIDO: por cada uno
#     de los top-N candidatos, su mejor vinilo NO poseído (LATERAL, cap natural 1
#     por artista); portada Discogs + artista solo sobre ese puñado.
#
# Requiere que el usuario tenga semillas EN el grafo (artistas de su colección con
# afines fetchados). Sin semillas → [] honesto (el caller explica "conecta/espera");
# NO cae al centroide viejo (retirado). Anónimo → [].
#
# NOTA — `taste_centroid_literal` (centroide de gusto de la colección) queda RETIRADO
# con esta reescritura: su ÚNICO caller era el viejo `recommend_for_user`. No se
# borra la referencia de embeddings de core (los OTROS caminos —afines de obra/
# artista, mood, `recommend_from_listening`— siguen usando embeddings); pero el
# "Para ti" ya no pasa por él.

# Cuántos candidatos del grafo (ordenados por score) llevamos a la fase 2. Margen
# amplio sobre `limit` para no quedarnos cortos si alguno no tiene obra válida en
# vinilo tras el filtro anti-single / suelo de popularidad. Subido a 150 para que el
# pool completo de "Para ti" (ver-más = 50) se pueda llenar en usuarios con grafo
# rico; usuarios con grafo escaso devuelven honestamente lo que haya (uno/artista).
_COESCUCHA_CAND_LIMIT = 150

# Suelo de popularidad LIGERO para la mejor obra del candidato: descarta fantasmas
# (obra sin escuchas Y sin ediciones decentes) pero NO por popularidad alta — el
# mainstream no es el objetivo, el score de co-escucha ya prioriza afinidad. Umbral
# de ediciones intencionadamente bajo: solo corta lo verdaderamente residual.
_COESCUCHA_MIN_RELEASES = 3

# Fase 2 del patrón de dos fases para la reco PERSONAL por ESCUCHA (Last.fm, KNN de
# centroide) — SIGUE viva (`recommend_from_listening`); es `_RECO_PHASE2_SQL`.
_PERSONAL_PHASE2_SQL = _RECO_PHASE2_SQL


def _owned_work_ids(cur, user_id):
    """Set de work_ids que el usuario POSEE (vía release_id resuelto). Es la base
    de la EXCLUSIÓN de colección: nunca recomendar lo que ya tiene."""
    cur.execute(
        """
        SELECT DISTINCT r.work_id
        FROM user_collection uc
        JOIN releases r ON r.id = uc.release_id
        WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL
        """,
        {"u": user_id},
    )
    return [row["work_id"] for row in cur.fetchall()]


def _coescucha_porque(anclas):
    """Frase-porqué CONCRETA desde las anclas de co-escucha: "porque tienes A y B".

    `anclas` = las 1-2 semillas de la colección del usuario que más apuntan al
    candidato (mayor match), ya ordenadas. Vacío → None (el caller lo omite)."""
    anclas = [a for a in (anclas or []) if a]
    if not anclas:
        return None
    if len(anclas) == 1:
        return "porque tienes {}".format(anclas[0])
    return "porque tienes {} y {}".format(anclas[0], anclas[1])


# Fase 1: AGREGA co-escucha por artista candidato. Por cada artista que el usuario
# POSEE (owned_artists), sus afines del grafo `lastfm_similar_artists`; se agrupan
# por candidato con score = Σ match, n_anclas = nº de semillas que lo apuntan, y
# `anclas` = las 2 semillas de mayor match (para el `porque`). Excluye artistas ya
# poseídos. Orden por score DESC; solo los top-N pasan a fase 2. Query VALIDADA.
_COESCUCHA_CAND_SQL = """
    WITH owned AS (
        SELECT DISTINCT r.work_id
        FROM user_collection uc
        JOIN releases r ON r.id = uc.release_id
        WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL
    ),
    owned_artists AS (
        SELECT DISTINCT w.primary_artist_id AS aid
        FROM owned o JOIN works w ON w.id = o.work_id
    ),
    cand AS (
        SELECT s.similar_artist_id AS aid,
               sum(s.match) AS score,
               count(DISTINCT s.artist_id) AS n_anclas,
               (array_agg(sa.name ORDER BY s.match DESC))[1:2] AS anclas
        FROM lastfm_similar_artists s
        JOIN owned_artists oa ON oa.aid = s.artist_id
        JOIN artists sa ON sa.id = s.artist_id
        WHERE s.similar_artist_id IS NOT NULL
          AND s.similar_artist_id NOT IN (SELECT aid FROM owned_artists)
        GROUP BY s.similar_artist_id
    ),
    cand_top AS (
        SELECT * FROM cand ORDER BY score DESC LIMIT %(cand_lim)s
    ),
    best AS (
        SELECT c.aid, c.score, c.n_anclas, c.anclas, bw.id AS work_id
        FROM cand_top c
        CROSS JOIN LATERAL (
            SELECT w.id
            FROM works w
            JOIN artists a ON a.id = w.primary_artist_id
            WHERE w.primary_artist_id = c.aid
              AND w.has_vinyl = true
              AND w.work_type = ANY(%(work_types)s::work_type[])
              AND w.id NOT IN (SELECT work_id FROM owned)
              AND (coalesce(w.lastfm_playcount, 0) > 0
                   OR coalesce(w.releases_count, 0) >= %(min_rc)s)
              AND {album_track_ok}
              AND {artist_ok}
            ORDER BY w.lastfm_playcount DESC NULLS LAST, w.releases_count DESC
            LIMIT 1
        ) bw
    )
    SELECT b.aid AS artist_id,
           a.name AS artist_name,
           b.score,
           b.n_anclas,
           b.anclas,
           w.id,
           w.title,
           w.work_type,
           w.year,
           w.releases_count,
           EXISTS (SELECT 1 FROM cover_images ci
                    WHERE ci.work_id = w.id AND ci.source = 'discogs') AS has_cover,
           vc.preferred_thumb AS cover_thumb,
           vc.preferred_url   AS cover_url
    FROM best b
    JOIN artists a ON a.id = b.aid
    JOIN works w   ON w.id = b.work_id
    LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb
               FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = w.id
    ORDER BY b.score DESC
    LIMIT %(pool_limit)s
""".format(album_track_ok=_album_track_ok_sql("w"), artist_ok=_ARTIST_NOT_MORRALLA_SQL)


def recommend_for_user(user_id, limit=12):
    """"Para ti": recomendación PERSONAL por GRAFO DE CO-ESCUCHA (Last.fm getSimilar).

    Dos fases (ver bloque de doc arriba): (1) agrega afines de los artistas de su
    colección desde `lastfm_similar_artists` (score = Σ match, anclas = semillas de
    mayor match), excluyendo artistas ya poseídos; (2) por cada top-candidato, su
    MEJOR obra en vinilo NO poseída (studio_album/ep de verdad — anti-single
    `_album_track_ok_sql`; suelo de popularidad ligero anti-fantasma), orden por
    escuchas y luego ediciones. Una obra por artista (cap natural del LATERAL).

    Cada fila lleva `porque` CONCRETO ("porque tienes A y B") con anclas REALES de
    su colección. Sin semillas en el grafo (usuario cuyos artistas aún no se han
    fetchado) → [] honesto: el caller explica "conecta/espera"; NO cae al centroide
    viejo (retirado). Anónimo → []."""
    if not user_id:
        return {"works": [], "missing_cover_ids": []}
    with _cursor() as cur:
        cur.execute(_COESCUCHA_CAND_SQL, {
            "u": user_id,
            "work_types": list(_RECO_WORK_TYPES),
            "cand_lim": _COESCUCHA_CAND_LIMIT,
            "min_rc": _COESCUCHA_MIN_RELEASES,
            "pool_limit": max(limit * _COVER_POOL_FACTOR, _COESCUCHA_CAND_LIMIT),
        })
        rows = cur.fetchall()

    # Regla TRANSVERSAL de PORTADA + CONVERGENCIA: el grafo de co-escucha NO se toca
    # (spec §4); solo partimos su resultado por portada de Discogs — works con
    # portada se muestran (hasta limit), los sin portada van a encolar.
    works, missing = [], []
    for r in rows:
        item = dict(r)
        item["porque"] = _coescucha_porque(item.get("anclas"))
        item.pop("anclas", None)
        item.pop("score", None)
        has_cover = item.pop("has_cover", False)
        if has_cover:
            item["has_discogs"] = True
            if len(works) < limit:
                works.append(item)
        else:
            missing.append(item["id"])
    return {"works": works, "missing_cover_ids": missing}


def _owned_artist_ids(cur, user_id):
    """Set de primary_artist_id de los works que el usuario posee. Se usa para NO
    recomendar (en la capa personal) discos de artistas que el usuario ya colecciona
    — el objetivo del centroide es DESCUBRIR, no devolver más del mismo artista."""
    cur.execute(
        """
        SELECT DISTINCT w.primary_artist_id AS artist_id
        FROM user_collection uc
        JOIN releases r ON r.id = uc.release_id
        JOIN works w ON w.id = r.work_id
        WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL
        """,
        {"u": user_id},
    )
    return [row["artist_id"] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# CAPA PERSONAL DE RECO — por ESCUCHA de Last.fm (M3b)
# ---------------------------------------------------------------------------
#
# Complementa a recommend_for_user (centroide de COLECCIÓN) con un centroide de
# ESCUCHA: la señal de Last.fm ya sincronizada en core (user_lastfm_albums /
# user_lastfm_artists, con work_id / artist_id RESUELTOS). CERO API externa, CERO
# embed en vivo — todo son embeddings YA calculados en core.
#
# Composición del centroide de escucha (media PONDERADA por log1p(playcount)):
#   (a) señal PRINCIPAL, álbum-nivel: embeddings de los works de
#       `user_lastfm_albums` con work_id resuelto y embedding. Peso pleno.
#   (b) señal COMPLEMENTARIA, artista-nivel: el CENTROIDE de los works con
#       vinilo/obra-de-verdad de cada top `user_lastfm_artists` resuelto (cubre a
#       los artistas escuchados sin un álbum concreto resuelto). Peso a la MITAD
#       (`_LISTEN_ARTIST_WEIGHT`) — el álbum concreto es señal más fina que el
#       agregado del artista.
# Se usa `period='overall'` (gusto ESTABLE) — simple y suficiente (26 works de
# álbum + 44 artistas resueltos con embedding para Carlos → 1.196 works afines).
# El centroide se calcula en SQL y viaja a Python como LITERAL ::vector para el
# KNN de dos fases (mismo patrón de rendimiento que recommend_for_user).

# Peso relativo de la señal artista-nivel frente a la de álbum-nivel en el
# centroide de escucha (la de álbum es más específica → manda).
_LISTEN_ARTIST_WEIGHT = 0.5

# Period de Last.fm usado para el gusto estable.
_LISTEN_PERIOD = "overall"


def listening_centroid_literal(cur, user_id, period=_LISTEN_PERIOD):
    """Centroide de ESCUCHA como LITERAL ::vector (texto '[x,y,…]') o None.

    Media ponderada por log1p(playcount) de:
      - embeddings de works de `user_lastfm_albums` (work_id resuelto, embedding),
        con peso log1p(playcount);
      - centroide de works vinilo/obra-de-verdad de cada `user_lastfm_artists`
        resuelto, con peso `_LISTEN_ARTIST_WEIGHT * log1p(playcount)`.
    None si no hay NINGUNA señal de escucha con embedding (el caller degrada []).
    """
    cur.execute(
        """
        WITH album_sig AS (
            -- señal álbum-nivel: embedding del work escuchado, peso log1p(pc).
            SELECT w.embedding AS emb,
                   ln(1 + ula.playcount) AS wgt
            FROM user_lastfm_albums ula
            JOIN works w ON w.id = ula.work_id
            WHERE ula.user_id = %(u)s AND ula.period = %(p)s
              AND ula.work_id IS NOT NULL
              AND w.embedding IS NOT NULL
        ),
        artist_sig AS (
            -- señal artista-nivel: centroide de sus works vinilo/obra-de-verdad,
            -- peso _LISTEN_ARTIST_WEIGHT * log1p(pc). Un artista aporta una fila.
            SELECT ac.centroid AS emb,
                   %(aw)s * ln(1 + ula.playcount) AS wgt
            FROM user_lastfm_artists ula
            JOIN LATERAL (
                SELECT avg(w.embedding)::vector(512) AS centroid, count(*) AS n
                FROM works w
                WHERE w.primary_artist_id = ula.artist_id
                  AND w.embedding IS NOT NULL
                  AND w.has_vinyl = true
                  AND w.work_type = ANY(%(work_types)s::work_type[])
            ) ac ON ac.n > 0
            WHERE ula.user_id = %(u)s AND ula.period = %(p)s
              AND ula.artist_id IS NOT NULL
        ),
        sig AS (
            SELECT emb, wgt FROM album_sig
            UNION ALL
            SELECT emb, wgt FROM artist_sig
        )
        -- Centroide ponderado como DIRECCIÓN: sum(emb * w). No dividimos por sum(w)
        -- porque el KNN es por coseno (`<=>`), invariante a la escala del vector — la
        -- normalización solo cambiaría la magnitud, no la dirección ni el orden ANN.
        -- pgvector 0.8 no tiene vector*escalar, así que el peso w se difunde a un
        -- vector constante (array_fill, 512d) y se usa el producto elementwise
        -- `vector * vector`; sum(vector) es agregado nativo.
        SELECT
            sum(emb * array_fill(wgt::float4, ARRAY[512])::vector)
                ::vector(512)::text AS centroid,
            count(*) AS n
        FROM sig
        WHERE wgt > 0
        """,
        {"u": user_id, "p": period, "aw": _LISTEN_ARTIST_WEIGHT,
         "work_types": list(_RECO_WORK_TYPES)},
    )
    row = cur.fetchone()
    if not row or not row["n"] or row["centroid"] is None:
        return None
    return row["centroid"]


def listening_top_artist_names(cur, user_id, limit=2, period=_LISTEN_PERIOD):
    """1-2 nombres de sus top artistas Last.fm resueltos (para el `porque`).

    Prioriza artistas con works vinilo (los que de verdad sostienen la señal).
    NO expone playcounts. Lista posiblemente vacía."""
    cur.execute(
        """
        SELECT ula.artist_name
        FROM user_lastfm_artists ula
        WHERE ula.user_id = %(u)s AND ula.period = %(p)s
          AND ula.artist_id IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM works w
              WHERE w.primary_artist_id = ula.artist_id
                AND w.has_vinyl = true AND w.embedding IS NOT NULL
          )
        ORDER BY ula.rank ASC
        LIMIT %(lim)s
        """,
        {"u": user_id, "p": period, "lim": limit},
    )
    return [r["artist_name"] for r in cur.fetchall()]


# Cap de obras por artista en el TIER 3 (otros discos de artistas que escuchas):
# variedad — no llenar la sección con la discografía de un solo artista.
_LISTEN_TIER3_ARTIST_CAP = 2


def recommend_from_listening(user_id, limit=12):
    """"Basado en lo que escuchas": la ESCUCHA REAL del usuario (Last.fm), en tres
    tiers por prioridad. NO centroide, NO co-escucha — discos concretos que escucha.

    Devuelve un dict {"works", "missing_cover_ids"} (regla TRANSVERSAL de portada +
    convergencia). Cada work lleva `porque` y un `tier`. Anónimo → dict vacío.

    Tiers (en orden; se rellena `limit` sin repetir work):
      1. Discos que ESCUCHAS y NO tienes en absoluto: works de `user_lastfm_albums`
         (work_id resuelto), sin NINGUNA release en su colección, `has_vinyl` →
         comprar el vinilo. Orden por su playcount de Last.fm.
      2. UPGRADE: works de `user_lastfm_albums` que posee en formato≠vinyl y SIN
         vinilo poseído, con `has_vinyl`. Orden por playcount.
      3. Otros discos de los ARTISTAS que escuchas (`user_lastfm_artists`), no
         poseídos: sus mejores works en vinilo (playcount/releases_count), cap
         `_LISTEN_TIER3_ARTIST_CAP` por artista.

    TODO con filtros transversales (vinilo + álbum/EP + anti-single + portada +
    enqueue de los sin). SIN Discogs conectado (usuario sin colección): tier 1 SIN
    el filtro de posesión (muestra todo lo escuchado), por playcount. Subtítulo
    honesto lo pone el caller según `tier`.
    """
    if not user_id:
        return {"works": [], "missing_cover_ids": []}
    period = _LISTEN_PERIOD
    with _cursor() as cur:
        # ¿Tiene colección resuelta? (define si aplicamos filtro de posesión).
        cur.execute(
            "SELECT count(*) AS n FROM user_collection "
            "WHERE user_id = %(u)s AND release_id IS NOT NULL", {"u": user_id})
        has_collection = (cur.fetchone()["n"] or 0) > 0

        # TIER 1 + 2: works escuchados (user_lastfm_albums, work_id resuelto). Se
        # clasifica cada uno por su relación con la colección: 'buy' (no poseído) o
        # 'upgrade' (poseído en no-vinilo, sin vinilo). Con filtros transversales +
        # portada (has_cover) y anti-single. Sin colección → todo es 'buy'.
        cur.execute("""
            WITH listened AS MATERIALIZED (
                SELECT DISTINCT ON (ula.work_id)
                       ula.work_id, ula.playcount
                FROM user_lastfm_albums ula
                WHERE ula.user_id = %(u)s AND ula.period = %(p)s
                  AND ula.work_id IS NOT NULL
                ORDER BY ula.work_id, ula.playcount DESC
            ),
            owned AS MATERIALIZED (
                SELECT r.work_id,
                       bool_or(r.format = 'vinyl')  AS owns_vinyl,
                       bool_or(r.format <> 'vinyl') AS owns_nonvinyl
                FROM user_collection uc
                JOIN releases r ON r.id = uc.release_id
                WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL
                GROUP BY r.work_id
            ),
            cand AS MATERIALIZED (
                SELECT w.id, w.title, w.work_type, w.year, w.releases_count,
                       w.primary_artist_id, l.playcount,
                       ow.owns_vinyl, ow.owns_nonvinyl
                FROM listened l
                JOIN works w ON w.id = l.work_id
                LEFT JOIN owned ow ON ow.work_id = w.id
                WHERE w.has_vinyl = true
                  AND w.work_type = ANY(%(work_types)s::work_type[])
                  AND {album_track_ok_w}
                  -- descartar lo que YA tiene en vinilo (nada que comprar/subir)
                  AND COALESCE(ow.owns_vinyl, false) = false
            ),
            with_cover AS MATERIALIZED (
                SELECT DISTINCT work_id FROM cover_images
                WHERE source = 'discogs'
                  AND work_id = ANY(ARRAY(SELECT id FROM cand))
            )
            SELECT c.id, c.title, c.work_type, c.year, c.releases_count,
                   c.primary_artist_id AS artist_id, a.name AS artist_name,
                   c.playcount, c.owns_nonvinyl,
                   (c.id IN (SELECT work_id FROM with_cover)) AS has_cover,
                   vc.preferred_thumb AS cover_thumb, vc.preferred_url AS cover_url
            FROM cand c
            JOIN artists a ON a.id = c.primary_artist_id
            LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb
                       FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = c.id
            ORDER BY c.playcount DESC NULLS LAST, c.releases_count DESC NULLS LAST
        """.format(album_track_ok_w=_album_track_ok_sql("w")),
            {"u": user_id, "p": period, "work_types": list(_RECO_WORK_TYPES)})
        album_rows = cur.fetchall()

        works, missing, seen = [], [], set()

        def _take(row, tier, porque):
            wid = row["id"]
            if wid in seen:
                return
            if row.get("has_cover"):
                if len(works) < limit:
                    seen.add(wid)
                    item = {k: row[k] for k in (
                        "id", "title", "work_type", "year", "releases_count",
                        "artist_id", "artist_name", "cover_thumb", "cover_url")}
                    item["has_discogs"] = True
                    item["tier"] = tier
                    item["porque"] = porque
                    works.append(item)
            else:
                if wid not in missing:
                    missing.append(wid)

        # Tier 1 (buy): no poseído en absoluto (owns_nonvinyl falso/NULL). Sin
        # colección, has_collection=False → TODOS caen aquí (owns_nonvinyl NULL).
        for r in album_rows:
            if not r.get("owns_nonvinyl"):
                _take(r, "buy", "lo escuchas y aún no lo tienes — pásalo a vinilo")
        # Tier 2 (upgrade): poseído en no-vinilo, sin vinilo.
        for r in album_rows:
            if r.get("owns_nonvinyl"):
                _take(r, "upgrade", "lo tienes en otro formato — súbelo a vinilo")

        # TIER 3: otros discos de los ARTISTAS que escuchas, no poseídos. Solo si
        # aún no hemos llenado `limit`. Cap por artista para variedad.
        if len(works) < limit:
            owned_work_ids = _owned_work_ids(cur, user_id) if has_collection else []
            cur.execute("""
                WITH listened_artists AS MATERIALIZED (
                    SELECT DISTINCT ON (ula.artist_id)
                           ula.artist_id, ula.artist_name, ula.playcount, ula.rank
                    FROM user_lastfm_artists ula
                    WHERE ula.user_id = %(u)s AND ula.period = %(p)s
                      AND ula.artist_id IS NOT NULL
                    ORDER BY ula.artist_id, ula.playcount DESC
                ),
                best AS MATERIALIZED (
                    -- `rn` = ranking de la obra DENTRO del artista: la mejor primero.
                    -- Orden de calidad: álbum de estudio antes que EP, no-directo antes
                    -- que directo, y luego escuchas/ediciones. Así rn=1 es la obra
                    -- "de verdad" del artista, no un EP suelto ni un disco en vivo.
                    -- El nombre mostrado es el CANÓNICO del artista de la obra
                    -- (artists.name vía primary_artist_id), NO el texto crudo de
                    -- Last.fm de `user_lastfm_artists` — ese puede venir mal resuelto
                    -- o corrupto ("Geese • Audio sin pérdida"), y dejaría la tarjeta
                    -- incoherente con la ficha a la que enlaza (obra/<id>).
                    SELECT la.artist_id, art.name AS artist_name, la.rank,
                           w.id, w.title, w.work_type, w.year, w.releases_count,
                           ROW_NUMBER() OVER (
                               PARTITION BY la.artist_id
                               ORDER BY (w.title ILIKE '%%live%%'
                                         OR w.title ILIKE '%%directo%%') ASC,
                                        (w.work_type = 'ep') ASC,
                                        w.lastfm_playcount DESC NULLS LAST,
                                        w.releases_count DESC NULLS LAST) AS rn
                    FROM listened_artists la
                    JOIN works w ON w.primary_artist_id = la.artist_id
                    JOIN artists art ON art.id = w.primary_artist_id
                    WHERE w.has_vinyl = true
                      AND w.work_type = ANY(%(work_types)s::work_type[])
                      AND NOT (w.id = ANY(%(owned)s::bigint[]))
                      AND {album_track_ok_w}
                ),
                picked AS MATERIALIZED (
                    SELECT * FROM best WHERE rn <= %(cap)s
                ),
                with_cover AS MATERIALIZED (
                    SELECT DISTINCT work_id FROM cover_images
                    WHERE source = 'discogs'
                      AND work_id = ANY(ARRAY(SELECT id FROM picked))
                )
                SELECT p.id, p.title, p.work_type, p.year, p.releases_count,
                       p.artist_id, p.artist_name,
                       (p.id IN (SELECT work_id FROM with_cover)) AS has_cover,
                       vc.preferred_thumb AS cover_thumb, vc.preferred_url AS cover_url
                FROM picked p
                LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb
                           FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = p.id
                -- Round-robin: PRIMERO la mejor obra de cada artista (por cuánto lo
                -- escuchas), y solo después las segundas. Evita 2 discos seguidos del
                -- mismo artista cuando el cap por artista es >1.
                ORDER BY p.rn ASC, p.rank ASC NULLS LAST, p.releases_count DESC NULLS LAST
            """.format(album_track_ok_w=_album_track_ok_sql("w")),
                {"u": user_id, "p": period, "work_types": list(_RECO_WORK_TYPES),
                 "owned": owned_work_ids or [0], "cap": _LISTEN_TIER3_ARTIST_CAP})
            for r in cur.fetchall():
                _take(r, "artist",
                      "de {}, que escuchas".format(r["artist_name"]))

    return {"works": works, "missing_cover_ids": missing}


# ---------------------------------------------------------------------------
# GAP DE VINILO — la feature estrella (§4.3.4 del DESIGN)
# ---------------------------------------------------------------------------
#
# Obras que el usuario tiene en formato ≠ vinilo, que EXISTEN en vinilo
# (works.has_vinyl), y de las que NO posee ya una release de vinilo. Devuelve la
# obra + sus ediciones de vinilo (para enlazar/comprar). El "no posee ya el
# vinilo" es DURO: se cruza contra las releases que el usuario tiene resueltas y su
# format real (release.format='vinyl'), no contra el texto de user_collection.


def vinyl_gap_count(user_id):
    """Conteo interno del gap de vinilo (sin paginar). Para el resumen honesto."""
    with _cursor() as cur:
        cur.execute("""
            WITH owned AS (
                SELECT DISTINCT r.work_id, r.format AS rel_format
                FROM user_collection uc
                JOIN releases r ON r.id = uc.release_id
                WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL
            ),
            owned_work AS (
                SELECT work_id,
                       bool_or(rel_format = 'vinyl')  AS owns_vinyl,
                       bool_or(rel_format <> 'vinyl') AS owns_nonvinyl
                FROM owned GROUP BY work_id
            )
            SELECT count(*) AS gap
            FROM owned_work ow
            JOIN works w ON w.id = ow.work_id
            WHERE w.has_vinyl = true
              AND ow.owns_nonvinyl = true
              AND ow.owns_vinyl = false
        """, {"u": user_id})
        return cur.fetchone()["gap"]


def vinyl_gap(user_id, limit=24, per_artist_cap=2):
    """Gap de vinilo: obras que el usuario tiene en NO-vinilo y existen en vinilo,
    y de las que NO posee ya un prensado de vinilo. Con las ediciones de vinilo de
    cada obra y el formato en que la tiene.

    Orden por relevancia (releases_count DESC, playcount DESC). Cap por artista
    para variedad. Cada fila trae:
      - work + cover + artista
      - owned_format: el/los formato(s) físico(s) en que la tiene (p.ej. 'cd')
      - editions: sus releases de vinilo (year/country/label/catno/cover)
      - porque: "lo tienes en {formato}, existe en vinilo"
    El precio lo añade la fachada del dominio (pricing), no la BD.

    "No posee ya el vinilo" es DURO: `owns_vinyl = false` sobre las releases
    resueltas del usuario con format real 'vinyl'.
    """
    with _cursor() as cur:
        # Fase 1: obras del gap (rank+cap+LIMIT) SIN tocar ediciones/portada.
        cur.execute("""
            WITH owned AS (
                SELECT DISTINCT r.work_id, r.format::text AS rel_format
                FROM user_collection uc
                JOIN releases r ON r.id = uc.release_id
                WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL
            ),
            owned_work AS (
                SELECT work_id,
                       bool_or(rel_format = 'vinyl')  AS owns_vinyl,
                       bool_or(rel_format <> 'vinyl') AS owns_nonvinyl,
                       array_agg(DISTINCT rel_format) FILTER (
                           WHERE rel_format <> 'vinyl') AS owned_formats
                FROM owned GROUP BY work_id
            ),
            gap AS (
                SELECT w.id,
                       w.title,
                       w.work_type,
                       w.year,
                       w.releases_count,
                       w.primary_artist_id,
                       ow.owned_formats,
                       ROW_NUMBER() OVER (
                           PARTITION BY w.primary_artist_id
                           ORDER BY w.releases_count DESC NULLS LAST,
                                    w.lastfm_playcount DESC NULLS LAST
                       ) AS rn_artist
                FROM owned_work ow
                JOIN works w ON w.id = ow.work_id
                WHERE w.has_vinyl = true
                  AND ow.owns_nonvinyl = true
                  AND ow.owns_vinyl = false
                  AND """ + _album_track_ok_sql("w") + """
            ),
            picked AS MATERIALIZED (
                SELECT id, title, work_type, year, releases_count,
                       primary_artist_id, owned_formats
                FROM gap
                WHERE rn_artist <= %(cap)s
                ORDER BY releases_count DESC NULLS LAST
                LIMIT %(pool_limit)s
            ),
            with_cover AS MATERIALIZED (
                SELECT DISTINCT work_id FROM cover_images
                WHERE source = 'discogs'
                  AND work_id = ANY(ARRAY(SELECT id FROM picked))
            )
            SELECT p.id, p.title, p.work_type, p.year, p.releases_count,
                   p.owned_formats,
                   (p.id IN (SELECT work_id FROM with_cover)) AS has_cover,
                   a.id   AS artist_id,
                   a.name AS artist_name,
                   vc.preferred_thumb AS cover_thumb,
                   vc.preferred_url   AS cover_url
            FROM picked p
            JOIN artists a ON a.id = p.primary_artist_id
            LEFT JOIN (SELECT work_id, url AS preferred_url, url_thumb AS preferred_thumb FROM cover_images WHERE source = 'discogs') vc ON vc.work_id = p.id
            ORDER BY p.releases_count DESC NULLS LAST
        """, {"u": user_id, "cap": per_artist_cap,
              "pool_limit": max(limit * _COVER_POOL_FACTOR, _SEARCH_CAND_LIMIT)})
        cand_rows = cur.fetchall()

        # CONVERGENCIA: partir por portada de Discogs. Los sin-portada se encolan
        # (missing_cover_ids); los con-portada se muestran hasta `limit`.
        rows, missing = [], []
        for r in cand_rows:
            r = dict(r)
            if r.pop("has_cover", False):
                if len(rows) < limit:
                    r["has_discogs"] = True
                    rows.append(r)
            else:
                missing.append(r["id"])

        if not rows:
            return {"works": [], "missing_cover_ids": missing}

        # Fase 2: ediciones de vinilo de las obras elegidas, en UNA query (sin N+1).
        work_ids = [r["id"] for r in rows]
        cur.execute("""
            SELECT r.work_id,
                   r.id, r.year, r.country, r.catno, r.cover_url,
                   l.name AS label_name
            FROM releases r
            LEFT JOIN labels l ON l.id = r.label_id
            WHERE r.work_id = ANY(%(ids)s)
              AND r.format = 'vinyl'
            ORDER BY r.work_id, r.year ASC NULLS LAST, r.country ASC NULLS LAST
        """, {"ids": work_ids})
        eds_by_work = {}
        for e in cur.fetchall():
            eds_by_work.setdefault(e["work_id"], []).append({
                "id": e["id"], "year": e["year"], "country": e["country"],
                "catno": e["catno"], "cover_url": e["cover_url"],
                "label_name": e["label_name"],
            })

    _FMT_LABEL = {"cd": "CD", "cassette": "cassette", "digital": "digital",
                  "other": "otro formato"}
    out = []
    for r in rows:
        r = dict(r)
        fmts = [f for f in (r.get("owned_formats") or []) if f and f != "vinyl"]
        labels = [_FMT_LABEL.get(f, f) for f in fmts]
        owned_label = " y ".join(labels) if labels else "otro formato"
        r["owned_format_label"] = owned_label
        r["editions"] = eds_by_work.get(r["id"], [])
        r["porque"] = "lo tienes en {}, existe en vinilo".format(owned_label)
        out.append(r)
    return {"works": out, "missing_cover_ids": missing}


# ---------------------------------------------------------------------------
# PORTADAS (cover-backfill on-demand desde Discogs)
# ---------------------------------------------------------------------------
# La app SOLO LEE el CATÁLOGO; `cover_images` es ENRIQUECIMIENTO (como sessions):
# guardar una portada de Discogs recuperada en vivo es una escritura acotada y
# legítima, JAMÁS DDL (la tabla ya existe). La vista `v_work_cover` ya prefiere
# 'discogs' sobre 'caa', así que en cuanto se guarda la de Discogs se usa sola.

def cover_sources_for_works(work_ids):
    """Para un conjunto de work_ids, qué FUENTE de portada tiene cada uno.

    Devuelve dict work_id -> {"has_discogs": bool, "has_caa": bool}. UNA query
    (agregación por work_id sobre `cover_images`, índice `cover_images_work_id_idx`),
    NO N+1. Los work_ids sin ninguna fila NO aparecen en el dict (el caller los
    trata como "sin portada"). Lista vacía → {} sin tocar la BD.
    """
    ids = [int(w) for w in (work_ids or []) if w is not None]
    if not ids:
        return {}
    with _cursor() as cur:
        cur.execute("""
            SELECT work_id,
                   bool_or(source = 'discogs') AS has_discogs,
                   bool_or(source = 'caa')     AS has_caa
            FROM cover_images
            WHERE work_id = ANY(%(ids)s)
            GROUP BY work_id
        """, {"ids": ids})
        return {
            r["work_id"]: {
                "has_discogs": bool(r["has_discogs"]),
                "has_caa": bool(r["has_caa"]),
            }
            for r in cur.fetchall()
        }


def work_discogs_ids(work_ids):
    """Para recuperar portada de Discogs: por work_id, su `discogs_master_id` y un
    `discogs_release_id` de VINILO (para el fallback master→release del cliente).

    Devuelve dict work_id -> {"master_id": int|None, "release_id": int|None}.
    Solo aparecen works que tengan AL MENOS uno de los dos (sin ninguno no se
    puede pedir a Discogs). UNA query. Lista vacía → {}.
    """
    ids = [int(w) for w in (work_ids or []) if w is not None]
    if not ids:
        return {}
    with _cursor() as cur:
        cur.execute("""
            SELECT w.id AS work_id,
                   w.discogs_master_id AS master_id,
                   (SELECT r.discogs_release_id
                      FROM releases r
                     WHERE r.work_id = w.id
                       AND r.format = 'vinyl'
                       AND r.discogs_release_id IS NOT NULL
                     ORDER BY r.year ASC NULLS LAST
                     LIMIT 1) AS release_id
            FROM works w
            WHERE w.id = ANY(%(ids)s)
        """, {"ids": ids})
        out = {}
        for r in cur.fetchall():
            if r["master_id"] is None and r["release_id"] is None:
                continue
            out[r["work_id"]] = {
                "master_id": r["master_id"],
                "release_id": r["release_id"],
            }
        return out


def store_cover_image(work_id, source, url, url_thumb):
    """UPSERT de una portada en `cover_images` (enriquecimiento, no DDL).

    Parametrizado. ON CONFLICT (work_id, source) refresca url/thumb/fetched_at.
    """
    with _cursor() as cur:
        cur.execute("""
            INSERT INTO cover_images (work_id, source, url, url_thumb, fetched_at)
            VALUES (%(w)s, %(s)s, %(u)s, %(t)s, now())
            ON CONFLICT (work_id, source) DO UPDATE
              SET url = EXCLUDED.url,
                  url_thumb = EXCLUDED.url_thumb,
                  fetched_at = now()
        """, {"w": int(work_id), "s": source, "u": url, "t": url_thumb})


def artist_discogs_ids(artist_ids):
    """Para recuperar foto de artista de Discogs: por artist_id, su
    `discogs_artist_id`.

    Devuelve dict artist_id -> discogs_artist_id (int). Solo aparecen los
    artistas que tengan `discogs_artist_id` (sin él no se puede pedir a Discogs →
    el worker se salta y sigue el monograma). UNA query. Lista vacía → {}.
    """
    ids = [int(a) for a in (artist_ids or []) if a is not None]
    if not ids:
        return {}
    with _cursor() as cur:
        cur.execute("""
            SELECT id AS artist_id, discogs_artist_id
            FROM artists
            WHERE id = ANY(%(ids)s)
              AND discogs_artist_id IS NOT NULL
        """, {"ids": ids})
        return {r["artist_id"]: r["discogs_artist_id"] for r in cur.fetchall()}


def store_artist_image(artist_id, url):
    """Guarda la foto de artista recuperada de Discogs en `artists.image_url`
    (enriquecimiento, no DDL). Solo esa columna + metadatos de fuente.

    Parametrizado. La BD es compartida (core); escribir en image_url es OK.
    """
    with _cursor() as cur:
        cur.execute("""
            UPDATE artists
               SET image_url = %(u)s,
                   image_source = 'discogs',
                   image_fetched_at = now(),
                   updated_at = now()
             WHERE id = %(a)s
        """, {"u": url, "a": int(artist_id)})