-- Vinylbe v2 — M3c · Fase 1: wishlist de usuario.
--
-- Dato PROPIEDAD de v2 (no toca el catálogo). Misma frontera de escritura ACOTADA
-- que `app_users`/`user_sessions`: la app escribe aquí, pero nunca hace DDL en
-- runtime. Esta migración se aplica UNA vez, fuera de la app:
--
--     psql postgresql://localhost/vinology_core -f migrations/001_user_wishlist.sql
--
-- `work_id` referencia el catálogo (works) solo para integridad: si un disco
-- desaparece de core, su entrada de wishlist se limpia sola (CASCADE). Borrar un
-- usuario ("borrar cuenta") arrastra su wishlist igual (CASCADE sobre app_users).

CREATE TABLE IF NOT EXISTS user_wishlist (
  user_id    bigint      NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  work_id    bigint      NOT NULL REFERENCES works(id)     ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, work_id)
);

-- Orden de lectura de /wishlist: por usuario, lo más reciente primero.
CREATE INDEX IF NOT EXISTS idx_user_wishlist_user_created
  ON user_wishlist (user_id, created_at DESC);
