#!/usr/bin/env bash
# package_vinilogy_serve.sh — empaqueta el esquema `vserve` (dentro del core) en una
# BD Postgres STANDALONE `vinilogy_serve`, lista para restaurar en Railway.
#
# Produce una BD donde TODO vive en `public` (Vinilogy conecta sin search_path):
#   1. Prelude: extensiones + enums + función immutable_unaccent (las dependencias que
#      las tablas de vserve referencian como public.*).
#   2. Catálogo + precios: se vuelca desde `vserve` y se mueve a `public`.
#   3. Tablas de usuario: esquema real desde core.public (VACÍO, con sus secuencias/PKs)
#      — el ciclo de usuario es aparte; en prod las escribe la web y NO las pisa un
#      rebuild de catálogo.
#
# Requisitos previos: haber corrido deploy/build_vinilogy_serve.py (crea el esquema
# vserve en el core). En prod: VINILOGY_EMBED_TYPE=halfvec.
#
# Uso:  CORE_DSN=postgresql://localhost/vinology_core \
#       SERVE_DB=vinilogy_serve  bash deploy/package_vinilogy_serve.sh
set -euo pipefail

CORE_DSN="${CORE_DSN:-postgresql://localhost/vinology_core}"
SERVE_DB="${SERVE_DB:-vinilogy_serve}"
SERVE_DSN="postgresql://localhost/${SERVE_DB}"
SCHEMA=vserve

CATALOG_TABLES="works artists releases cover_images work_genres work_styles \
work_main_release work_press_signals lastfm_similar_artists labels genres styles \
marketplace_listings"
USER_TABLES="app_users user_sessions user_collection user_wishlist \
user_lastfm_albums user_lastfm_artists user_oauth_credentials"

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

say "0 · recrear BD ${SERVE_DB} (destructivo)"
dropdb --if-exists "$SERVE_DB"
createdb "$SERVE_DB"

say "1 · prelude (extensiones + enums + immutable_unaccent)"
# memoria/paralelismo para que el rebuild del HNSW en el restore no use defaults lentos
psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q -c \
  "ALTER DATABASE \"${SERVE_DB}\" SET maintenance_work_mem='2GB';
   ALTER DATABASE \"${SERVE_DB}\" SET max_parallel_maintenance_workers=4;"
psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
SQL
# enums (recreados desde core, en public)
psql "$CORE_DSN" -tA -c "
  SELECT 'CREATE TYPE public.'||t.typname||' AS ENUM ('||
         string_agg(quote_literal(e.enumlabel), ', ' ORDER BY e.enumsortorder)||');'
  FROM pg_type t JOIN pg_enum e ON e.enumtypid=t.oid
  WHERE t.typname IN ('artist_kind','oauth_provider','release_format','work_type')
  GROUP BY t.typname;" | psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q
# función immutable_unaccent (usada por los índices trigram)
psql "$CORE_DSN" -tA -c "SELECT pg_get_functiondef('immutable_unaccent'::regproc)||';';" \
  | psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q

say "2 · catálogo + precios (vserve → public)"
psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q -c "CREATE SCHEMA IF NOT EXISTS ${SCHEMA};"
DUMP_T=""; for t in $CATALOG_TABLES; do DUMP_T="$DUMP_T -t ${SCHEMA}.${t}"; done
# shellcheck disable=SC2086
pg_dump "$CORE_DSN" --no-owner --no-privileges $DUMP_T \
  | psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q
for t in $CATALOG_TABLES; do
  psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q -c "ALTER TABLE ${SCHEMA}.${t} SET SCHEMA public;"
done
psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q -c "DROP SCHEMA IF EXISTS ${SCHEMA} CASCADE;"

say "3 · tablas de usuario (esquema real desde core, VACÍO)"
DUMP_U=""; for t in $USER_TABLES; do DUMP_U="$DUMP_U -t public.${t}"; done
# shellcheck disable=SC2086
pg_dump "$CORE_DSN" --schema-only --no-owner --no-privileges $DUMP_U \
  | psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q

say "4 · analyze + verificación"
psql "$SERVE_DSN" -v ON_ERROR_STOP=1 -q -c "ANALYZE;"
echo "tamaño BD: $(psql "$SERVE_DSN" -tA -c "SELECT pg_size_pretty(pg_database_size('${SERVE_DB}'));")"
echo "tablas en public:"
psql "$SERVE_DSN" -tA -F' | ' -c "
  SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid))
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='public' AND c.relkind='r'
  ORDER BY pg_total_relation_size(c.oid) DESC;"

say "OK — BD ${SERVE_DB} lista"
echo "Prod: VINILOGY_DB_DSN=${SERVE_DSN}  +  VINILOGY_EMBED_TYPE=halfvec"
