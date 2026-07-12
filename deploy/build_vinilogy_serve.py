#!/usr/bin/env python3
"""
build_vinilogy_serve.py — construye la BD de SERVICIO (slim) de Vinilogy.

De las ~47 GB que ocupan las tablas de Vinilogy en el core, produce un esquema
`vserve` de ~4,4 GB con SOLO lo que sirve producción. Se materializa DENTRO del
core (todo el filtrado en-BD, sin trasiego por Python); el empaquetado a una BD
standalone `vinilogy_serve` es un paso posterior (ver --package, pendiente).

CÓMO ADELGAZA (47 GB → ~4,4 GB)
  - Poda de FILAS: solo works "servibles" = has_vinyl AND is_official AND
    work_type IN ('studio_album','ep')  (~914K works). Las demás tablas se
    derivan de ese conjunto (artists/releases/covers/junctions referenciados).
  - Poda de COLUMNAS/ediciones:
      · works    → fuera `embedding_press` (Vinilogy solo usa `embedding` p/ afines)
      · releases → solo la edición representativa (work_main_release) → el
                   monstruo `tracklist_cache` (10 GB) cae a migajas
  - CAA ya está fuera del core (cover_images es Discogs-only).

TRES CICLOS DE VIDA
  --catalog : works/releases/artists/covers/afines/lookups + índices + esqueleto
              de tablas de usuario. Se REEMPLAZA al reconstruir el catálogo.
  --prices  : SOLO marketplace_listings. Refresco nocturno.
  --full    : catalog + prices (por defecto).
  Las tablas de USUARIO (app_users, user_*, user_oauth_credentials) se crean
  VACÍAS aquí (esqueleto); en producción las escribe la web en vivo y un rebuild
  de catálogo NUNCA las pisa.

USO
  CORE_DSN=postgresql://localhost/vinology_core python deploy/build_vinilogy_serve.py --full
"""
import argparse
import os
import sys
import time

import psycopg2

CORE_DSN = os.environ.get("CORE_DSN", "postgresql://localhost/vinology_core")
SCHEMA = "vserve"

# --- Afines (embedding + HNSW): las palancas de tamaño ---
# El embedding a full precision (vector 512d) + su HNSW son ~4,2 GB (el 59% de la
# slim). halfvec (media precisión, 2 bytes/dim) + un HNSW más ligero (m=8) lo bajan
# a ~1,5 GB con pérdida de recall imperceptible para recomendar por contenido.
# Reversible: pon EMBEDDING_HALFVEC=False / HNSW_M=16 para volver a máxima calidad.
EMBED_DIM = 512
EMBEDDING_HALFVEC = True
HNSW_M = 8
HNSW_OPS = "halfvec_cosine_ops" if EMBEDDING_HALFVEC else "vector_cosine_ops"

# Predicado "servible" — idéntico al de app/db.py (_DISCOGRAPHY_WORK_TYPES +
# has_vinyl + is_official). El filtro de PORTADA es de query-time (no de
# almacenamiento): la slim guarda TODOS los servibles aunque aún no tengan
# portada, para que el backfill pueda pedírsela.
SERVIBLE = ("w.has_vinyl AND w.is_official "
            "AND w.work_type IN ('studio_album','ep')")

# Tablas de usuario: esqueleto VACÍO (schema + constraints + índices), nunca datos.
# (excluded_artists NO va aquí: es una CTE en app/db.py, no una tabla real.)
USER_TABLES = [
    "app_users", "user_sessions", "user_collection", "user_wishlist",
    "user_lastfm_albums", "user_lastfm_artists", "user_oauth_credentials",
]

# Índices que usan las queries de Vinilogy (CREATE TABLE AS SELECT no los copia).
# `immutable_unaccent` y los opclass (gin_trgm_ops, vector_cosine_ops) resuelven
# vía search_path=public porque construimos DENTRO del core.
INDEXES = [
    # works — búsqueda FTS, discografía por artista, afines (HNSW)
    "CREATE UNIQUE INDEX ON {s}.works (id)",
    "CREATE INDEX ON {s}.works USING gin (search_doc)",
    "CREATE INDEX ON {s}.works (primary_artist_id, work_type) WHERE is_official",
    "CREATE INDEX ON {s}.works (primary_artist_id)",
    "CREATE INDEX ON {s}.works USING gin (lower(immutable_unaccent(title)) gin_trgm_ops)",
    "CREATE INDEX ON {s}.works (primary_artist_id, releases_count DESC NULLS LAST) WHERE has_vinyl",
    "CREATE INDEX ON {s}.works USING hnsw (embedding {ops}) WITH (m = {m}) WHERE embedding IS NOT NULL",
    # artists
    "CREATE UNIQUE INDEX ON {s}.artists (id)",
    "CREATE INDEX ON {s}.artists USING gin (search_doc)",
    "CREATE INDEX ON {s}.artists USING gin (lower(immutable_unaccent(name)) gin_trgm_ops)",
    "CREATE INDEX ON {s}.artists USING gin (tags)",
    # covers
    "CREATE UNIQUE INDEX ON {s}.cover_images (work_id, source)",
    "CREATE INDEX ON {s}.cover_images (work_id)",
    # afines por artista (grafo Last.fm)
    "CREATE UNIQUE INDEX ON {s}.lastfm_similar_artists (artist_id, rank)",
    "CREATE INDEX ON {s}.lastfm_similar_artists (artist_id)",
    # junctions
    "CREATE UNIQUE INDEX ON {s}.work_genres (work_id, genre_id)",
    "CREATE INDEX ON {s}.work_genres (work_id)",
    "CREATE UNIQUE INDEX ON {s}.work_styles (work_id, style_id)",
    "CREATE INDEX ON {s}.work_styles (work_id)",
    "CREATE UNIQUE INDEX ON {s}.work_main_release (work_id)",
    "CREATE INDEX ON {s}.work_press_signals (work_id)",
    # releases / lookups
    "CREATE UNIQUE INDEX ON {s}.releases (id)",
    "CREATE INDEX ON {s}.releases (work_id)",
    "CREATE INDEX ON {s}.releases (discogs_release_id) WHERE discogs_release_id IS NOT NULL",
    "CREATE UNIQUE INDEX ON {s}.labels (id)",
    "CREATE UNIQUE INDEX ON {s}.genres (id)",
    "CREATE UNIQUE INDEX ON {s}.styles (id)",
]

PRICE_INDEXES = [
    "CREATE UNIQUE INDEX ON {s}.marketplace_listings (id)",
    "CREATE INDEX ON {s}.marketplace_listings (work_id) WHERE work_id IS NOT NULL",
]


def run(cur, sql, label):
    t0 = time.monotonic()
    cur.execute(sql)
    print(f"  · {label:<42} {time.monotonic()-t0:6.1f}s", flush=True)


def works_columns_except_embedding_press(cur):
    """Lista de columnas de works SIN embedding_press (para no copiarla siquiera).
    Si EMBEDDING_HALFVEC, castea `embedding` a halfvec(EMBED_DIM) en el mismo SELECT."""
    emb = (f"embedding::halfvec({EMBED_DIM}) AS embedding"
           if EMBEDDING_HALFVEC else "embedding")
    cur.execute("""
        SELECT string_agg(
                 CASE WHEN column_name='embedding' THEN %s ELSE quote_ident(column_name) END,
                 ', ' ORDER BY ordinal_position)
        FROM information_schema.columns
        WHERE table_schema='public' AND table_name='works'
          AND column_name <> 'embedding_press'
    """, (emb,))
    return cur.fetchone()[0]


def build_catalog(cur):
    print("== CATÁLOGO ==", flush=True)
    run(cur, f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE", "drop schema")
    run(cur, f"CREATE SCHEMA {SCHEMA}", "create schema")

    # works — servibles, sin embedding_press
    cols = works_columns_except_embedding_press(cur)
    run(cur, f"CREATE TABLE {SCHEMA}.works AS "
             f"SELECT {cols} FROM public.works w WHERE {SERVIBLE}", "works (servibles)")

    # derivadas del conjunto works ya materializado
    run(cur, f"CREATE TABLE {SCHEMA}.artists AS SELECT * FROM public.artists "
             f"WHERE id IN (SELECT DISTINCT primary_artist_id FROM {SCHEMA}.works "
             f"             WHERE primary_artist_id IS NOT NULL)", "artists")

    run(cur, f"CREATE TABLE {SCHEMA}.work_main_release AS SELECT * FROM public.work_main_release "
             f"WHERE work_id IN (SELECT id FROM {SCHEMA}.works)", "work_main_release")

    # 'main-path': la edición representativa (work_main_release.main_release_id ES
    # un discogs_release_id) que usa get_work_tracklist. Cubre ~100% de los works;
    # el fallback-por-moda (raros, ~0,02%) no se materializa aquí.
    run(cur, f"CREATE TABLE {SCHEMA}.releases AS SELECT * FROM public.releases "
             f"WHERE discogs_release_id IN (SELECT main_release_id FROM {SCHEMA}.work_main_release "
             f"                             WHERE main_release_id IS NOT NULL)", "releases (main-path)")

    run(cur, f"CREATE TABLE {SCHEMA}.cover_images AS SELECT * FROM public.cover_images "
             f"WHERE source='discogs' AND work_id IN (SELECT id FROM {SCHEMA}.works)", "cover_images (discogs)")

    run(cur, f"CREATE TABLE {SCHEMA}.work_genres AS SELECT * FROM public.work_genres "
             f"WHERE work_id IN (SELECT id FROM {SCHEMA}.works)", "work_genres")
    run(cur, f"CREATE TABLE {SCHEMA}.work_styles AS SELECT * FROM public.work_styles "
             f"WHERE work_id IN (SELECT id FROM {SCHEMA}.works)", "work_styles")
    run(cur, f"CREATE TABLE {SCHEMA}.work_press_signals AS SELECT * FROM public.work_press_signals "
             f"WHERE work_id IN (SELECT id FROM {SCHEMA}.works)", "work_press_signals")

    # afines: grafo cerrado sobre los artistas servidos (sin refs colgando)
    run(cur, f"CREATE TABLE {SCHEMA}.lastfm_similar_artists AS "
             f"SELECT * FROM public.lastfm_similar_artists "
             f"WHERE artist_id IN (SELECT id FROM {SCHEMA}.artists) "
             f"  AND (similar_artist_id IS NULL "
             f"       OR similar_artist_id IN (SELECT id FROM {SCHEMA}.artists))", "lastfm_similar_artists")

    # labels referenciados por las releases servidas
    run(cur, f"CREATE TABLE {SCHEMA}.labels AS SELECT * FROM public.labels "
             f"WHERE id IN (SELECT label_id FROM {SCHEMA}.releases WHERE label_id IS NOT NULL)", "labels")

    # lookups pequeños enteros
    run(cur, f"CREATE TABLE {SCHEMA}.genres AS SELECT * FROM public.genres", "genres")
    run(cur, f"CREATE TABLE {SCHEMA}.styles AS SELECT * FROM public.styles", "styles")

    # tablas de usuario: esqueleto VACÍO (schema+constraints+índices), nunca datos
    for t in USER_TABLES:
        run(cur, f"CREATE TABLE {SCHEMA}.{t} (LIKE public.{t} INCLUDING ALL)", f"user skel · {t}")

    print("== ÍNDICES ==", flush=True)
    # El HNSW de embedding es el índice más lento; con más memoria y paralelismo
    # baja de ~25 min a unos pocos. Son settings de sesión (aplican a los CREATE
    # INDEX siguientes).
    run(cur, "SET maintenance_work_mem = '2GB'", "set maintenance_work_mem")
    run(cur, "SET max_parallel_maintenance_workers = 4", "set parallel workers")
    for i, tmpl in enumerate(INDEXES, 1):
        run(cur, tmpl.format(s=SCHEMA, ops=HNSW_OPS, m=HNSW_M), f"index {i}/{len(INDEXES)}")


def build_prices(cur):
    print("== PRECIOS (nightly) ==", flush=True)
    run(cur, f"DROP TABLE IF EXISTS {SCHEMA}.marketplace_listings CASCADE", "drop prices")
    run(cur, f"CREATE TABLE {SCHEMA}.marketplace_listings AS SELECT * FROM public.marketplace_listings "
             f"WHERE work_id IN (SELECT id FROM {SCHEMA}.works)", "marketplace_listings")
    for tmpl in PRICE_INDEXES:
        run(cur, tmpl.format(s=SCHEMA), "price index")


def report_size(cur):
    cur.execute(f"""
        SELECT sum(pg_total_relation_size(c.oid)),
               sum(pg_total_relation_size(c.oid))
                 - sum(pg_relation_size(c.oid) + coalesce(pg_relation_size(c.reltoastrelid),0))
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='{SCHEMA}' AND c.relkind='r'
    """)
    total, idx = cur.fetchone()
    total = float(total or 0)
    idx = float(idx or 0)
    print(f"\n== TAMAÑO {SCHEMA} ==")
    print(f"  total: {total/1e9:5.2f} GB   (índices ~{idx/1e9:.2f} GB)")
    cur.execute(f"""
        SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid))
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='{SCHEMA}' AND c.relkind='r'
        ORDER BY pg_total_relation_size(c.oid) DESC LIMIT 12
    """)
    for name, sz in cur.fetchall():
        print(f"    {name:<26} {sz}")


def main():
    ap = argparse.ArgumentParser(description="Construye la BD de servicio (slim) de Vinilogy")
    ap.add_argument("--catalog", action="store_true", help="solo catálogo + índices + esqueleto usuario")
    ap.add_argument("--prices", action="store_true", help="solo refresco de precios (nightly)")
    ap.add_argument("--full", action="store_true", help="catálogo + precios (por defecto)")
    args = ap.parse_args()
    do_catalog = args.catalog or args.full or not (args.catalog or args.prices)
    do_prices = args.prices or args.full or not (args.catalog or args.prices)

    print(f"CORE_DSN = {CORE_DSN}\nesquema  = {SCHEMA}\n", flush=True)
    t0 = time.monotonic()
    conn = psycopg2.connect(CORE_DSN)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        if do_catalog:
            build_catalog(cur)
        if do_prices:
            build_prices(cur)
        run(cur, f"ANALYZE {SCHEMA}.works", "analyze works")
        report_size(cur)
    finally:
        conn.close()
    print(f"\nOK en {time.monotonic()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    sys.exit(main())
