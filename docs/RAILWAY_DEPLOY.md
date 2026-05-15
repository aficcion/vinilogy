# Guía de Despliegue en Railway

## Variables de Entorno Necesarias

Configura estas variables en Railway (Settings → Variables):

### APIs Externas (OBLIGATORIAS)
```
LASTFM_API_KEY=tu_lastfm_api_key
LASTFM_API_SECRET=tu_lastfm_api_secret
DISCOGS_KEY=tu_discogs_key
DISCOGS_SECRET=tu_discogs_secret
EBAY_CLIENT_ID=tu_ebay_client_id
EBAY_CLIENT_SECRET=tu_ebay_client_secret
```

### URLs de Servicios (Railway auto-configura el dominio)
```
# Railway te dará un dominio como: vinylbe-production.up.railway.app
# Usa ese dominio para configurar:
LASTFM_REDIRECT_URI=https://TU-DOMINIO-RAILWAY.up.railway.app/lastfm/callback

# Los servicios internos usan localhost porque están en el mismo contenedor
DISCOGS_SERVICE_URL=http://localhost:3001
RECOMMENDER_SERVICE_URL=http://localhost:3002
PRICING_SERVICE_URL=http://localhost:3003
LASTFM_SERVICE_URL=http://localhost:3004
```

### Puerto (Railway lo configura automáticamente)
```
PORT=5000
```

## Archivos de Configuración

### 1. `railway.toml` ✅ (Ya configurado)
```toml
[build]
  dockerfile = "Dockerfile"

[[services]]
name = "vinylbe"
startCommand = "python start_services.py"
healthcheckPath = "/health"
healthcheckTimeout = 100
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

[[services.environmentVariables]]
name = "PORT"
value = "5000"
```

### 2. `Dockerfile` ✅ (Ya configurado)
- Usa Python 3.11-slim
- Instala dependencias
- Expone puerto 5000
- Ejecuta `start_services.py`

### 3. `start_services.py` ✅ (Ya configurado)
- Inicia todos los microservicios en puertos internos
- El gateway usa el puerto configurado en `$PORT`

## Pasos para Desplegar

### 1. Conectar Repositorio
1. Ve a [Railway](https://railway.app)
2. Click en "New Project" → "Deploy from GitHub repo"
3. Selecciona tu repositorio `Vinylbe`

### 2. Configurar Variables de Entorno
1. Ve a tu proyecto en Railway
2. Click en "Variables"
3. Añade todas las variables listadas arriba
4. **IMPORTANTE**: Actualiza `LASTFM_REDIRECT_URI` con tu dominio de Railway

### 3. Configurar Last.fm Callback
1. Ve a [Last.fm API Settings](https://www.last.fm/api/account/create)
2. Añade tu dominio de Railway a las URLs permitidas:
   ```
   https://TU-DOMINIO-RAILWAY.up.railway.app/lastfm/callback
   ```

### 4. Deploy
Railway detectará automáticamente el `Dockerfile` y desplegará.

## Verificación Post-Despliegue

### 1. Health Check
```bash
curl https://TU-DOMINIO-RAILWAY.up.railway.app/health
```

Deberías ver:
```json
{
  "gateway": "healthy",
  "services": {
    "discogs": {"status": "healthy"},
    "recommender": {"status": "healthy"},
    "pricing": {"status": "healthy"},
    "lastfm": {"status": "healthy"}
  }
}
```

### 2. Probar Login con Last.fm
1. Abre `https://TU-DOMINIO-RAILWAY.up.railway.app`
2. Click en "Conectar con Last.fm"
3. Autoriza en Last.fm
4. Deberías ser redirigido de vuelta con recomendaciones

## Problemas Comunes

### 1. Error 500 en Login Last.fm
**Causa**: `LASTFM_REDIRECT_URI` no coincide con la configuración de Last.fm
**Solución**: Verifica que ambas URLs sean exactamente iguales

### 2. Servicios no responden
**Causa**: Los servicios internos no se iniciaron correctamente
**Solución**: Revisa los logs en Railway → Deployments → View Logs

### 3. Base de datos se borra al redesplegar
**Causa**: SQLite en contenedor efímero
**Solución**: 
- Opción A: Usa Railway Volumes para persistir `vinylbe.db`
- Opción B: Migra a PostgreSQL (Railway ofrece PostgreSQL gratis)

## Migración a PostgreSQL (Recomendado para Producción)

Si quieres persistencia real, deberías migrar de SQLite a PostgreSQL:

1. Añade PostgreSQL en Railway (New → Database → PostgreSQL)
2. Railway te dará una `DATABASE_URL`
3. Modifica `gateway/db.py` para usar PostgreSQL en lugar de SQLite
4. Actualiza las variables de entorno

¿Necesitas ayuda con la migración a PostgreSQL?

## Notas Importantes

- ✅ Todos los cambios de este chat están incluidos
- ✅ No hay URLs hardcodeadas (todo usa variables de entorno)
- ✅ El orden de scripts está corregido
- ✅ Los endpoints están corregidos
- ⚠️ SQLite no es ideal para producción (considera PostgreSQL)
