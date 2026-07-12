-- ============================================================================
-- BigSur · Retirada de vinylbe_local — PASO A: soltar el catálogo FÓSIL
-- ============================================================================
-- Reclama ~27 GB dejando vinylbe_local como una DB de staging de precios de ~25 MB.
-- Ejecutar contra:  psql postgresql://localhost/vinylbe_local -f <este fichero>
--
-- QUÉ SE TIRA (fósil del prototipo pre-M4, superseded por vinology_core; solo lo
-- lee el modo "proto" de Florent, que está DORMIDO — congelado desde 23-may-2026):
--   albums (25GB), artists (2GB), tracks, discogs_release_cache,
--   lastfm_artist_albums / lastfm_top_albums / lastfm_geo_albums /
--   lastfm_tag_artists / lastfm_top_artists / lastfm_geo_artists
--
-- QUÉ SE MANTIENE (vivo o barato-e-inofensivo):
--   store_listings, store_price_history, store_scrape_runs, ebay_price_cache
--     → staging de precios que se porta a core cada noche (Paso B lo reubica).
--   tablas de usuario del prototipo (messages, user_collection, conversations,
--     users, sessions, …) → tinys (~5 MB total); se van con el DROP DATABASE del
--     Paso B. No hay ganancia en tocarlas ahora y son más sensibles.
--
-- ANTES DE EJECUTAR:
--   1) Que NO haya una sesión autónoma corriendo tests de Florent (usa core, pero
--      por si acaso). Florent en marcha en modo core no toca estas tablas.
--   2) Confirmar que ya no usas el modo PROTO de paridad (FLORENT_DB_DSN=…/vinylbe_local).
--   3) Es DESTRUCTIVO e irreversible (albums no se regenera trivialmente). Es
--      "prototipo desechable" por tu propia definición (nightly_audit.py:334).
-- ============================================================================

-- (0) PRE-CHECK: dependencias sobre las tablas fósiles (FKs desde tablas que
--     conservamos, o vistas). Revisa la salida ANTES de dropear. Si solo salen
--     constraints FK desde tablas-proto de usuario, es inofensivo.
SELECT con.conname, rel.relname AS tabla_que_depende,
       confrel.relname AS tabla_fosil_referenciada
FROM pg_constraint con
JOIN pg_class rel     ON rel.oid = con.conrelid
JOIN pg_class confrel ON confrel.oid = con.confrelid
WHERE con.contype = 'f'
  AND confrel.relname IN ('albums','artists','tracks','discogs_release_cache',
      'lastfm_artist_albums','lastfm_top_albums','lastfm_geo_albums',
      'lastfm_tag_artists','lastfm_top_artists','lastfm_geo_artists')
  AND rel.relname NOT IN ('albums','artists','tracks','discogs_release_cache',
      'lastfm_artist_albums','lastfm_top_albums','lastfm_geo_albums',
      'lastfm_tag_artists','lastfm_top_artists','lastfm_geo_artists');

-- (1) EL DROP. En transacción para poder ROLLBACK si el pre-check te sorprende.
--     Sin CASCADE: si una tabla que conservamos tuviera FK a un fósil, esto FALLA
--     con un error claro (entonces revisa el pre-check y decide). El espacio en
--     disco se libera al COMMIT (DROP TABLE desenlaza los ficheros; no hace falta
--     VACUUM).
BEGIN;

DROP TABLE
    albums,
    artists,
    tracks,
    discogs_release_cache,
    lastfm_artist_albums,
    lastfm_top_albums,
    lastfm_geo_albums,
    lastfm_tag_artists,
    lastfm_top_artists,
    lastfm_geo_artists;

-- (2) Comprobación antes de confirmar: tamaño de la DB tras soltar los fósiles.
SELECT pg_size_pretty(pg_database_size('vinylbe_local')) AS tamano_tras_drop;

-- Si todo cuadra:
COMMIT;
-- Si algo no te convence:
-- ROLLBACK;

-- ============================================================================
-- Si el pre-check (0) mostró SOLO constraints FK desde tablas-proto de usuario y
-- prefieres dropear igualmente sin quitarlas a mano, sustituye el DROP de (1) por
-- la versión CASCADE (quita esas constraints FK, NO las tablas que conservas):
--
--   DROP TABLE albums, artists, tracks, discogs_release_cache,
--     lastfm_artist_albums, lastfm_top_albums, lastfm_geo_albums,
--     lastfm_tag_artists, lastfm_top_artists, lastfm_geo_artists CASCADE;
-- ============================================================================
