# Gestión de Base de Datos en Railway

## 🔧 Opciones para Gestionar la BD de Producción

### Opción 1: Railway CLI + SQLite (Más Directo)

```bash
# 1. Instalar Railway CLI
brew install railway

# 2. Login
railway login

# 3. Conectar al proyecto Vinylbe
cd /Users/carlosbautista/Downloads/Vinylbe
railway link

# 4. Abrir shell en el contenedor de producción
railway run bash

# 5. Una vez dentro, usar sqlite3
sqlite3 vinylbe.db

# Comandos útiles de SQLite:
.tables                          # Ver todas las tablas
.schema user                     # Ver esquema de tabla
SELECT COUNT(*) FROM user;       # Contar usuarios
SELECT * FROM user LIMIT 5;      # Ver primeros 5 usuarios
.quit                            # Salir
```

---

### Opción 2: Descargar BD de Producción

```bash
# Descargar la base de datos completa
railway run cat vinylbe.db > vinylbe_prod_backup.db

# Ahora puedes usar tu db_explorer localmente
python -m streamlit run db_explorer/app.py
# Y abrir vinylbe_prod_backup.db desde la interfaz
```

---

### Opción 3: Ejecutar Scripts en Producción

```bash
# Ejecutar el script de limpieza en producción
railway run python cleanup_db.py

# Ejecutar cualquier script Python
railway run python check_user_data.py
```

---

### Opción 4: Ver Logs de Base de Datos

```bash
# Ver logs en tiempo real
railway logs --follow

# Buscar errores específicos de BD
railway logs | grep -i "database\|sqlite"
```

---

### Opción 5: Exponer DB Explorer en Producción (Temporal)

Si quieres acceder al DB Explorer desde el navegador en producción:

1. **Añadir endpoint temporal al gateway:**

```python
# En gateway/main.py, añadir:
import subprocess

@app.get("/admin/db-explorer")
async def launch_db_explorer():
    """Launch DB explorer (ONLY FOR DEBUGGING - REMOVE IN PRODUCTION)"""
    subprocess.Popen(["streamlit", "run", "db_explorer/app.py", "--server.port", "8501"])
    return {"message": "DB Explorer launched on port 8501"}
```

2. **Exponer puerto 8501 en Railway**
3. **Acceder a:** `https://TU-DOMINIO.up.railway.app:8501`

⚠️ **IMPORTANTE:** Esto es solo para debugging temporal. Elimínalo después.

---

## 🔍 Comandos Útiles de SQLite

### Ver Estadísticas

```sql
-- Contar usuarios
SELECT COUNT(*) FROM user;

-- Contar artistas
SELECT COUNT(*) FROM artists;
SELECT COUNT(*) FROM artists WHERE is_partial = 1;

-- Contar álbumes
SELECT COUNT(*) FROM albums;
SELECT COUNT(*) FROM albums WHERE is_partial = 1;

-- Ver últimos usuarios creados
SELECT id, username, created_at FROM user ORDER BY created_at DESC LIMIT 10;

-- Ver recomendaciones por usuario
SELECT u.username, COUNT(r.id) as rec_count
FROM user u
LEFT JOIN recommendation r ON u.id = r.user_id
GROUP BY u.id;
```

### Limpieza Manual

```sql
-- Eliminar todos los usuarios
DELETE FROM user;

-- Eliminar registros parciales
DELETE FROM artists WHERE is_partial = 1;
DELETE FROM albums WHERE is_partial = 1;

-- Vacuum para liberar espacio
VACUUM;
```

---

## 📊 Monitoreo de la BD

### Ver Tamaño de la Base de Datos

```bash
# En el contenedor de Railway
railway run ls -lh vinylbe.db

# O con du
railway run du -h vinylbe.db
```

### Backup Automático

```bash
# Crear backup con timestamp
railway run sqlite3 vinylbe.db ".backup /tmp/backup_$(date +%Y%m%d_%H%M%S).db"

# Descargar el backup
railway run cat /tmp/backup_*.db > backup_prod.db
```

---

## 🚨 Troubleshooting

### Base de Datos Bloqueada

```bash
# Ver procesos que usan la BD
railway run lsof vinylbe.db

# Si está bloqueada, reiniciar el servicio
railway restart
```

### Corrupción de BD

```bash
# Verificar integridad
railway run sqlite3 vinylbe.db "PRAGMA integrity_check;"

# Si hay problemas, hacer dump y restore
railway run sqlite3 vinylbe.db ".dump" > dump.sql
railway run sqlite3 vinylbe_new.db < dump.sql
```

---

## 🔐 Seguridad

### Proteger Acceso a la BD

1. **Nunca expongas SQLite directamente a internet**
2. **Usa variables de entorno para credenciales**
3. **Limita acceso solo a IPs autorizadas**
4. **Considera migrar a PostgreSQL para producción seria**

---

## 📝 Migración a PostgreSQL (Recomendado para Producción)

Si tu app crece, considera migrar a PostgreSQL:

```bash
# 1. Añadir PostgreSQL en Railway
railway add postgresql

# 2. Railway te dará DATABASE_URL automáticamente

# 3. Actualizar gateway/db.py para usar PostgreSQL
# (puedo ayudarte con esto si lo necesitas)
```

**Ventajas de PostgreSQL:**
- ✅ Mejor concurrencia
- ✅ Backups automáticos
- ✅ Mejor rendimiento con muchos usuarios
- ✅ Herramientas de gestión (pgAdmin, DBeaver)

---

## 🎯 Recomendación

Para gestión rápida y fácil:
1. **Usa Railway CLI** para acceso directo
2. **Descarga backups regularmente** con `railway run cat`
3. **Usa tu db_explorer localmente** con los backups
4. **Considera PostgreSQL** si la app crece

¿Necesitas ayuda configurando alguna de estas opciones?
