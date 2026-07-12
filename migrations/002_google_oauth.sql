-- Vinilogy — M3c · Fase 2: Google como proveedor de IDENTIDAD (OAuth2 / OIDC).
--
-- El esquema de core ya traía las columnas oauth2_* (pre-provisionadas). Falta:
--   1) añadir 'google' al enum `oauth_provider`.
--   2) ampliar el CHECK de forma para aceptar la credencial de Google (guardamos
--      el access token; a Google NO le pedimos nada más tras el login: solo da
--      identidad, no hay colección/escucha que sincronizar).
--
-- Aplicar UNA vez, fuera de la app:
--     psql postgresql://localhost/bigsur_core -f migrations/002_google_oauth.sql
--
-- Se aplica en autocommit (psql -f sin -1): el ADD VALUE queda comprometido antes
-- de que el ALTER TABLE use el literal 'google'. NO envolver en BEGIN/COMMIT.

ALTER TYPE oauth_provider ADD VALUE IF NOT EXISTS 'google';

ALTER TABLE user_oauth_credentials DROP CONSTRAINT user_oauth_creds_shape;

ALTER TABLE user_oauth_credentials ADD CONSTRAINT user_oauth_creds_shape CHECK (
      (provider = 'discogs' AND oauth_token IS NOT NULL AND oauth_token_secret IS NOT NULL)
   OR (provider = 'lastfm'  AND session_key IS NOT NULL)
   OR (provider = 'google'  AND oauth2_access_token IS NOT NULL)
);
