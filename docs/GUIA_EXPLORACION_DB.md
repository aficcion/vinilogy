# 🎵 Guía de Exploración de Base de Datos - Vinylbe

## 📊 Resumen de tu Base de Datos

Tu base de datos SQLite (`vinylbe.db`) contiene:
- **359 artistas**
- **2,712 álbumes**
- **9 usuarios**
- **54 recomendaciones**

## 🛠️ Métodos de Exploración

### 1. Script Python Interactivo (Recomendado) ⭐

He creado un script llamado `explore_db.py` que te permite explorar la base de datos de forma fácil.

#### Modo Comando (Rápido)

```bash
# Ver resumen completo de la base de datos
python explore_db.py summary

# Ver esquema de todas las tablas
python explore_db.py schema

# Buscar artistas
python explore_db.py artist "Beatles"
python explore_db.py artist "Bowie"

# Buscar álbumes
python explore_db.py album "Dark Side"

# Ver todos los álbumes de un artista
python explore_db.py albums "Pink Floyd"

# Ejecutar consulta SQL personalizada
python explore_db.py query "SELECT * FROM artists LIMIT 5"
```

#### Modo Interactivo

```bash
python explore_db.py
```

Esto abrirá un menú interactivo con las siguientes opciones:
1. Mostrar resumen de la base de datos
2. Buscar artistas
3. Buscar álbumes
4. Mostrar álbumes de un artista
5. Mostrar recomendaciones de usuario
6. Ejecutar consulta SQL personalizada
7. Mostrar tablas y esquema

### 2. SQLite Command Line

```bash
# Abrir la base de datos en modo interactivo
sqlite3 vinylbe.db

# Una vez dentro, puedes usar estos comandos:
.tables                    # Ver todas las tablas
.schema                    # Ver esquema completo
.schema artists            # Ver esquema de una tabla específica
.mode column               # Formato de columnas
.headers on                # Mostrar encabezados

# Consultas de ejemplo:
SELECT * FROM artists LIMIT 10;
SELECT COUNT(*) FROM albums;
SELECT * FROM artists WHERE name LIKE '%Beatles%';
```

### 3. Consultas SQL Útiles

#### Ver artistas con más álbumes
```sql
SELECT a.name, COUNT(al.id) as album_count
FROM artists a
LEFT JOIN albums al ON a.id = al.artist_id
GROUP BY a.id
ORDER BY album_count DESC
LIMIT 10;
```

#### Ver álbumes mejor valorados
```sql
SELECT ar.name as artist, al.title, al.year, al.rating, al.votes
FROM albums al
JOIN artists ar ON al.artist_id = ar.id
WHERE al.rating IS NOT NULL
ORDER BY al.rating DESC, al.votes DESC
LIMIT 20;
```

#### Ver álbumes de un artista específico
```sql
SELECT title, year, rating, votes
FROM albums
WHERE artist_id = (SELECT id FROM artists WHERE name = 'The Beatles')
ORDER BY year;
```

#### Ver recomendaciones de un usuario
```sql
SELECT artist_name, album_title, source, status, created_at
FROM recommendation
WHERE user_id = 1
ORDER BY created_at DESC;
```

#### Ver estadísticas de usuarios
```sql
SELECT 
    u.display_name,
    COUNT(DISTINCT r.id) as total_recommendations,
    COUNT(DISTINCT CASE WHEN r.status = 'favorite' THEN r.id END) as favorites,
    COUNT(DISTINCT usa.artist_name) as selected_artists
FROM user u
LEFT JOIN recommendation r ON u.id = r.user_id
LEFT JOIN user_selected_artist usa ON u.id = usa.user_id
GROUP BY u.id;
```

#### Buscar álbumes por año
```sql
SELECT ar.name, al.title, al.year, al.rating
FROM albums al
JOIN artists ar ON al.artist_id = ar.id
WHERE al.year = '1977'
ORDER BY al.rating DESC;
```

### 4. Herramientas GUI (Opcionales)

Si prefieres una interfaz gráfica, puedes usar:

#### DB Browser for SQLite (Gratis)
```bash
# Instalar con Homebrew
brew install --cask db-browser-for-sqlite

# Luego abrir
open -a "DB Browser for SQLite" vinylbe.db
```

#### TablePlus (Comercial, pero tiene versión gratuita)
```bash
brew install --cask tableplus
```

#### DBeaver (Gratis y Open Source)
```bash
brew install --cask dbeaver-community
```

## 📋 Estructura de Tablas

### `artists`
- `id`: ID único del artista
- `name`: Nombre del artista
- `mbid`: MusicBrainz ID
- `image_url`: URL de la imagen del artista
- `last_updated`: Última actualización

### `albums`
- `id`: ID único del álbum
- `artist_id`: ID del artista (FK)
- `title`: Título del álbum
- `year`: Año de lanzamiento
- `discogs_master_id`: ID de Discogs
- `rating`: Valoración (0-5)
- `votes`: Número de votos
- `cover_url`: URL de la portada
- `mbid`: MusicBrainz ID del álbum

### `user`
- `id`: ID único del usuario
- `email`: Email del usuario
- `display_name`: Nombre para mostrar
- `created_at`: Fecha de creación
- `last_login_at`: Último login

### `recommendation`
- `id`: ID único de la recomendación
- `user_id`: ID del usuario (FK)
- `artist_name`: Nombre del artista
- `album_title`: Título del álbum
- `source`: Origen ('lastfm', 'manual', 'mixed')
- `status`: Estado ('neutral', 'favorite', 'disliked', 'owned')
- `created_at`: Fecha de creación

### `user_selected_artist`
- `id`: ID único
- `user_id`: ID del usuario (FK)
- `artist_name`: Nombre del artista
- `mbid`: MusicBrainz ID
- `source`: Origen ('manual', 'lastfm_suggestion')

### `auth_identity`
- `id`: ID único
- `user_id`: ID del usuario (FK)
- `provider`: Proveedor ('google', 'lastfm')
- `provider_user_id`: ID del usuario en el proveedor
- `access_token`: Token de acceso
- `refresh_token`: Token de refresco

### `user_profile_lastfm`
- `id`: ID único
- `user_id`: ID del usuario (FK)
- `lastfm_username`: Nombre de usuario de Last.fm
- `top_artists_json`: JSON con artistas favoritos
- `generated_at`: Fecha de generación

### `user_albums`
- `id`: ID único
- `user_id`: ID del usuario
- `album_id`: ID del álbum (FK)
- `play_count`: Número de reproducciones
- `last_played`: Última reproducción
- `added_at`: Fecha de adición

## 🔍 Ejemplos de Búsquedas Comunes

### Encontrar un artista
```bash
python explore_db.py artist "Pink Floyd"
```

### Ver discografía completa
```bash
python explore_db.py albums "Pink Floyd"
```

### Buscar álbumes de un año específico
```bash
python explore_db.py query "SELECT ar.name, al.title FROM albums al JOIN artists ar ON al.artist_id = ar.id WHERE al.year = '1973'"
```

### Ver tus recomendaciones favoritas
```bash
python explore_db.py query "SELECT * FROM recommendation WHERE status = 'favorite'"
```

## 💡 Tips

1. **Backup**: Siempre haz backup antes de modificar la base de datos
   ```bash
   cp vinylbe.db vinylbe.db.backup
   ```

2. **Modo solo lectura**: Para explorar sin riesgo de modificar
   ```bash
   sqlite3 -readonly vinylbe.db
   ```

3. **Exportar datos**: Para exportar a CSV
   ```bash
   sqlite3 vinylbe.db <<EOF
   .mode csv
   .output artists.csv
   SELECT * FROM artists;
   .quit
   EOF
   ```

4. **Ver tamaño de la base de datos**
   ```bash
   ls -lh vinylbe.db
   ```

## 🚀 Próximos Pasos

Si quieres:
- **Modificar datos**: Puedo ayudarte a crear scripts de actualización
- **Exportar reportes**: Puedo crear scripts para generar reportes en HTML/PDF
- **Crear dashboards**: Podemos crear visualizaciones con los datos
- **Optimizar consultas**: Puedo ayudarte a crear índices para mejorar el rendimiento

¡Déjame saber qué necesitas! 🎵
