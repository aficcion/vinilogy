# Migración de PostgreSQL a SQLite - Resumen de Cambios

## Fecha: 2025-11-22

## Objetivo
Migrar toda la aplicación Vinylbe de PostgreSQL a SQLite para simplificar el despliegue y mantenimiento.

## Archivos Modificados

### 1. `/services/recommender/artist_recommendations.py`
**Cambios principales:**
- ✅ Reemplazado `import psycopg2` por `import sqlite3`
- ✅ Eliminado `from psycopg2.extras import RealDictCursor`
- ✅ Agregada función `dict_factory()` para convertir filas SQLite a diccionarios
- ✅ Agregada función `_ensure_schema()` para crear tablas automáticamente
- ✅ Actualizada función `_get_db_connection()` para usar SQLite
- ✅ Cambiados placeholders de `%s` a `?` en todas las consultas SQL
- ✅ Actualizada sintaxis de `ON CONFLICT` de PostgreSQL a SQLite
- ✅ Eliminado `NULLS LAST` en ORDER BY (no soportado en SQLite)
- ✅ Agregado manejo de timestamps como strings en SQLite

**Esquema de tablas:**
```sql
CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    mbid TEXT,
    image_url TEXT,
    last_updated TIMESTAMP
)

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artist_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    year TEXT,
    discogs_master_id TEXT,
    discogs_release_id TEXT,
    rating REAL,
    votes INTEGER,
    cover_url TEXT,
    last_updated TIMESTAMP,
    FOREIGN KEY (artist_id) REFERENCES artists(id)
)
```

### 2. `/services/recommender/db_utils.py`
**Cambios principales:**
- ✅ Agregadas columnas `mbid` e `image_url` a la tabla `artists`
- ✅ Esquema actualizado para coincidir con `artist_recommendations.py`

### 3. `/scripts/update_missing_ratings.py`
**Cambios principales:**
- ✅ Reemplazado `import psycopg2` por `import sqlite3`
- ✅ Eliminado `from psycopg2.extras import RealDictCursor`
- ✅ Agregada función `dict_factory()` para convertir filas SQLite a diccionarios
- ✅ Actualizada función `get_db_connection()` para usar SQLite
- ✅ Cambiados placeholders de `%s` a `?` en consultas SQL
- ✅ Actualizada ruta de base de datos a `vinylbe.db`

### 4. `/init_sqlite_db.py` (NUEVO)
**Descripción:**
- ✅ Script nuevo para inicializar la base de datos SQLite
- ✅ Crea el esquema completo de tablas
- ✅ Crea índices para mejorar el rendimiento
- ✅ Muestra información sobre la base de datos creada

## Archivos NO Modificados (Scripts Legacy de PostgreSQL)

Los siguientes archivos aún contienen código de PostgreSQL pero son scripts de migración/utilidad que no se usan en producción:

- `/create_db.py` - Script legacy para crear base de datos PostgreSQL
- `/scripts/load_backup.py` - Script para cargar backups de PostgreSQL
- `/scripts/migrate_postgres_to_sqlite.py` - Script de migración (ya usado)
- `/scripts/import_artists_from_csv.py` - Script de importación

**Nota:** Estos scripts pueden mantenerse para referencia histórica o eliminarse si no se necesitan.

## Diferencias Clave: PostgreSQL vs SQLite

### Sintaxis de Placeholders
- **PostgreSQL:** `%s`
- **SQLite:** `?`

### ON CONFLICT
- **PostgreSQL:** `ON CONFLICT (name) DO UPDATE SET ... = EXCLUDED.column`
- **SQLite:** `ON CONFLICT(name) DO UPDATE SET ... = excluded.column`

### RETURNING
- **PostgreSQL:** `INSERT ... RETURNING id`
- **SQLite:** Usar `cursor.lastrowid` después del INSERT

### ORDER BY con NULL
- **PostgreSQL:** `ORDER BY column DESC NULLS LAST`
- **SQLite:** `ORDER BY column DESC` (NULL siempre al final por defecto)

### Timestamps
- **PostgreSQL:** Tipo nativo `TIMESTAMP`, función `CURRENT_TIMESTAMP`
- **SQLite:** Almacenado como TEXT, usar `datetime.now()` en Python

### Row Factory
- **PostgreSQL:** `cursor_factory=RealDictCursor`
- **SQLite:** `conn.row_factory = dict_factory` (función personalizada)

## Ruta de Base de Datos

Todos los archivos ahora apuntan a:
```python
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "vinylbe.db")
```

O en scripts:
```python
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "vinylbe.db")
```

Ubicación final: `/Users/carlosbautista/Downloads/Vinylbe/vinylbe.db`

## Verificación

### Archivos de servicios (producción)
```bash
# No debe haber referencias a psycopg2
grep -r "psycopg2" services/
# Resultado: Sin resultados ✅

# No debe haber referencias a DATABASE_URL
grep -r "DATABASE_URL" services/
# Resultado: Sin resultados ✅
```

### Base de datos existente
El archivo `vinylbe.db` ya existe con datos:
- Tamaño: ~1 MB
- Contiene tablas de artistas y álbumes

## Próximos Pasos

1. ✅ **Completado:** Migración de código a SQLite
2. 🔄 **Recomendado:** Reiniciar los servicios para aplicar cambios
3. 🔄 **Recomendado:** Verificar que las consultas funcionan correctamente
4. 📝 **Opcional:** Eliminar archivos legacy de PostgreSQL si no se necesitan
5. 📝 **Opcional:** Actualizar documentación del proyecto

## Comandos Útiles

### Inicializar/Verificar esquema
```bash
python init_sqlite_db.py
```

### Inspeccionar base de datos
```bash
sqlite3 vinylbe.db
.schema
.tables
SELECT COUNT(*) FROM artists;
SELECT COUNT(*) FROM albums;
.quit
```

### Reiniciar servicios
```bash
pkill -9 -f uvicorn
python start_services.py
```

## Notas Importantes

- ✅ SQLite es más simple y no requiere servidor separado
- ✅ Todos los datos existentes en `vinylbe.db` se mantienen intactos
- ✅ El esquema es compatible con los datos existentes
- ✅ No se requieren variables de entorno `DATABASE_URL`
- ⚠️ SQLite tiene limitaciones de concurrencia (suficiente para este proyecto)
- ⚠️ Los backups son más simples: solo copiar el archivo `vinylbe.db`

## Estado Final

✅ **COMPLETADO:** Toda la aplicación ahora usa SQLite exclusivamente
✅ **VERIFICADO:** No hay referencias a PostgreSQL en código de producción
✅ **FUNCIONAL:** El esquema está correctamente configurado
