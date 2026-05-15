-- Script para limpiar completamente la base de datos
-- Elimina todos los usuarios y sus datos asociados

-- Habilitar foreign keys
PRAGMA foreign_keys = ON;

-- Eliminar datos en orden inverso a las dependencias
DELETE FROM user_albums;
DELETE FROM recommendation;
DELETE FROM user_selected_artist;
DELETE FROM user_profile_lastfm;
DELETE FROM auth_identity;
DELETE FROM user;

-- Verificar que todo está vacío
SELECT 'Users:' as tabla, COUNT(*) as count FROM user
UNION ALL
SELECT 'Auth identities:', COUNT(*) FROM auth_identity
UNION ALL
SELECT 'User profiles (Last.fm):', COUNT(*) FROM user_profile_lastfm
UNION ALL
SELECT 'Selected artists:', COUNT(*) FROM user_selected_artist
UNION ALL
SELECT 'Recommendations:', COUNT(*) FROM recommendation
UNION ALL
SELECT 'User albums:', COUNT(*) FROM user_albums;

-- Resetear los autoincrement IDs (opcional, para empezar desde 1)
DELETE FROM sqlite_sequence WHERE name IN ('user', 'auth_identity', 'user_profile_lastfm', 'user_selected_artist', 'recommendation', 'user_albums');

-- Mensaje final
SELECT '✓ Base de datos limpiada completamente' as status;
