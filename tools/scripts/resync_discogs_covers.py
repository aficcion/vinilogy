#!/usr/bin/env python3
"""
Script para actualizar las cover_url de la colección de Discogs
consultando directamente la API de Discogs
"""
import sqlite3
import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()

DISCOGS_KEY = os.getenv('DISCOGS_KEY')
DISCOGS_SECRET = os.getenv('DISCOGS_SECRET')

if not DISCOGS_KEY or not DISCOGS_SECRET:
    print("❌ Error: DISCOGS_KEY y DISCOGS_SECRET deben estar configurados en .env")
    exit(1)

USER_ID = 1
DB_PATH = "vinylbe.db"

print("🔄 Actualizando cover URLs de Discogs...")
print(f"Usuario ID: {USER_ID}")

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Get all items without cover_url
cur.execute("""
    SELECT release_id, artist, title 
    FROM user_collection_discogs 
    WHERE user_id = ? AND (cover_url IS NULL OR cover_url = '')
""", (USER_ID,))

items = cur.fetchall()
total = len(items)

print(f"📊 Encontrados {total} items sin portada")

if total == 0:
    print("✅ Todos los items ya tienen portada!")
    conn.close()
    exit(0)

updated = 0
failed = 0

for i, item in enumerate(items, 1):
    release_id = item['release_id']
    artist = item['artist']
    title = item['title']
    
    print(f"[{i}/{total}] {artist} - {title}...", end=' ')
    
    try:
        # Query Discogs API for release info
        url = f"https://api.discogs.com/releases/{release_id}"
        headers = {
            'User-Agent': 'Vinylbe/1.0',
            'Authorization': f'Discogs key={DISCOGS_KEY}, secret={DISCOGS_SECRET}'
        }
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            cover_url = data.get('thumb') or data.get('cover_image')
            
            if cover_url:
                # Update database
                cur.execute("""
                    UPDATE user_collection_discogs 
                    SET cover_url = ? 
                    WHERE user_id = ? AND release_id = ?
                """, (cover_url, USER_ID, release_id))
                conn.commit()
                updated += 1
                print(f"✅")
            else:
                print(f"⚠️  Sin portada")
                failed += 1
        else:
            print(f"❌ Error {response.status_code}")
            failed += 1
        
        # Rate limiting - Discogs allows 60 requests per minute
        time.sleep(1.1)
        
    except Exception as e:
        print(f"❌ {e}")
        failed += 1

conn.close()

print(f"\n✨ Proceso completado:")
print(f"   ✅ Actualizados: {updated}")
print(f"   ❌ Fallidos: {failed}")
print(f"   📊 Total: {total}")
