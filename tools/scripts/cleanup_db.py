#!/usr/bin/env python3
"""
Script para limpiar la base de datos:
- Eliminar todos los usuarios y sus datos relacionados
- Eliminar registros parciales (is_partial = 1) de artists y albums
"""
import sqlite3
import os

DB_PATH = "vinylbe.db"

def cleanup_database():
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        print("🧹 Starting database cleanup...")
        print()
        
        # 1. Contar registros antes de limpiar
        print("📊 Current state:")
        cursor.execute("SELECT COUNT(*) FROM user")
        user_count = cursor.fetchone()[0]
        print(f"   Users: {user_count}")
        
        cursor.execute("SELECT COUNT(*) FROM auth_identity")
        auth_count = cursor.fetchone()[0]
        print(f"   Auth identities: {auth_count}")
        
        cursor.execute("SELECT COUNT(*) FROM user_profile_lastfm")
        profile_count = cursor.fetchone()[0]
        print(f"   Last.fm profiles: {profile_count}")
        
        cursor.execute("SELECT COUNT(*) FROM user_selected_artist")
        selected_count = cursor.fetchone()[0]
        print(f"   Selected artists: {selected_count}")
        
        cursor.execute("SELECT COUNT(*) FROM recommendation")
        rec_count = cursor.fetchone()[0]
        print(f"   Recommendations: {rec_count}")
        
        cursor.execute("SELECT COUNT(*) FROM user_albums")
        user_albums_count = cursor.fetchone()[0]
        print(f"   User albums: {user_albums_count}")
        
        cursor.execute("SELECT COUNT(*) FROM artists WHERE is_partial = 1")
        partial_artists = cursor.fetchone()[0]
        print(f"   Partial artists: {partial_artists}")
        
        cursor.execute("SELECT COUNT(*) FROM albums WHERE is_partial = 1")
        partial_albums = cursor.fetchone()[0]
        print(f"   Partial albums: {partial_albums}")
        print()
        
        # 2. Eliminar todos los usuarios (CASCADE eliminará datos relacionados)
        print("🗑️  Deleting all users and related data...")
        cursor.execute("DELETE FROM user")
        deleted_users = cursor.rowcount
        print(f"   ✅ Deleted {deleted_users} users")
        
        # Las tablas relacionadas se limpiarán automáticamente por CASCADE
        # Pero vamos a verificar y limpiar manualmente por si acaso
        cursor.execute("DELETE FROM auth_identity")
        cursor.execute("DELETE FROM user_profile_lastfm")
        cursor.execute("DELETE FROM user_selected_artist")
        cursor.execute("DELETE FROM recommendation")
        cursor.execute("DELETE FROM user_albums")
        print("   ✅ Cleaned all user-related tables")
        print()
        
        # 3. Eliminar registros parciales de albums
        print("🗑️  Deleting partial albums...")
        cursor.execute("DELETE FROM albums WHERE is_partial = 1")
        deleted_albums = cursor.rowcount
        print(f"   ✅ Deleted {deleted_albums} partial albums")
        print()
        
        # 4. Eliminar registros parciales de artists
        print("🗑️  Deleting partial artists...")
        cursor.execute("DELETE FROM artists WHERE is_partial = 1")
        deleted_artists = cursor.rowcount
        print(f"   ✅ Deleted {deleted_artists} partial artists")
        print()
        
        # 5. Commit changes
        conn.commit()
        print("💾 Changes committed to database")
        print()
        
        # 6. Mostrar estado final
        print("📊 Final state:")
        cursor.execute("SELECT COUNT(*) FROM user")
        print(f"   Users: {cursor.fetchone()[0]}")
        
        cursor.execute("SELECT COUNT(*) FROM artists")
        total_artists = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM artists WHERE is_partial = 1")
        partial_artists_final = cursor.fetchone()[0]
        print(f"   Artists: {total_artists} (partial: {partial_artists_final})")
        
        cursor.execute("SELECT COUNT(*) FROM albums")
        total_albums = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM albums WHERE is_partial = 1")
        partial_albums_final = cursor.fetchone()[0]
        print(f"   Albums: {total_albums} (partial: {partial_albums_final})")
        print()
        
        print("✅ Database cleanup completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {str(e)}")
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    print("=" * 60)
    print("DATABASE CLEANUP SCRIPT")
    print("=" * 60)
    print()
    print("⚠️  WARNING: This will delete:")
    print("   - All users and their data")
    print("   - All partial artists (is_partial = 1)")
    print("   - All partial albums (is_partial = 1)")
    print()
    
    response = input("Are you sure you want to continue? (yes/no): ")
    if response.lower() in ['yes', 'y']:
        cleanup_database()
    else:
        print("❌ Cleanup cancelled")
