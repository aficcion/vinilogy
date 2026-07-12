-- Vinilogy — Fase 1 (minimización de datos): dejar de almacenar los tokens OAuth
-- de Google. Google es SOLO identidad (no hay colección/escucha que sincronizar: ver
-- 002_google_oauth.sql), así que su access/refresh token es peso muerto y un riesgo
-- innecesario at-rest. Relajamos el CHECK para que una credencial de Google sea
-- válida sin oauth2_access_token; la app deja de persistirlo (pasa None). El cifrado
-- de los tokens que core SÍ consume (Discogs, Last.fm) es la Fase 2.
--
-- Aplicar UNA vez, fuera de la app:
--     psql postgresql://localhost/vinology_core -f migrations/003_google_no_token.sql

ALTER TABLE user_oauth_credentials DROP CONSTRAINT user_oauth_creds_shape;

ALTER TABLE user_oauth_credentials ADD CONSTRAINT user_oauth_creds_shape CHECK (
      (provider = 'discogs' AND oauth_token IS NOT NULL AND oauth_token_secret IS NOT NULL)
   OR (provider = 'lastfm'  AND session_key IS NOT NULL)
   OR (provider = 'google')
);

-- Limpia los tokens de Google ya almacenados (peso muerto tras el login).
UPDATE user_oauth_credentials
   SET oauth2_access_token  = NULL,
       oauth2_refresh_token = NULL,
       oauth2_expires_at    = NULL
 WHERE provider = 'google';
