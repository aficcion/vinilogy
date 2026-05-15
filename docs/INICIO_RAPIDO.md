# 🚀 Inicio Rápido - Despliegue en 10 Minutos

Esta guía te lleva paso a paso para publicar tu app en **Railway** (la opción más fácil).

## ✅ Pre-requisitos

- [ ] Cuenta de GitHub
- [ ] Tu código subido a un repositorio de GitHub
- [ ] Tus API keys de Discogs, Last.fm y eBay

## 📝 Paso 1: Preparar el Repositorio

### 1.1 Asegúrate de que `.env` NO esté en Git

```bash
# Verificar que .env está en .gitignore
cat .gitignore | grep .env
```

Si no aparece, añádelo:

```bash
echo ".env" >> .gitignore
```

### 1.2 Commit los archivos de configuración

```bash
git add Procfile railway.toml requirements.txt Dockerfile docker-compose.yml
git commit -m "Add deployment configuration files"
git push origin main
```

## 🚂 Paso 2: Desplegar en Railway

### 2.1 Crear cuenta

1. Ve a [railway.app](https://railway.app)
2. Click en **"Start a New Project"**
3. Selecciona **"Deploy from GitHub repo"**
4. Autoriza Railway para acceder a tu GitHub
5. Selecciona el repositorio `Vinylbe`

### 2.2 Configurar Variables de Entorno

Railway detectará automáticamente que es un proyecto Python. Ahora configura las variables:

1. Click en tu proyecto
2. Ve a **"Variables"**
3. Añade las siguientes variables:

```
DISCOGS_API_KEY=tu_clave_aqui
DISCOGS_API_SECRET=tu_secreto_aqui
LASTFM_API_KEY=tu_clave_aqui
LASTFM_API_SECRET=tu_secreto_aqui
EBAY_APP_ID=tu_app_id_aqui
EBAY_CERT_ID=tu_cert_id_aqui
```

### 2.3 Configurar el Comando de Inicio

Railway debería detectar automáticamente el `Procfile`, pero si no:

1. Ve a **"Settings"**
2. En **"Deploy"** → **"Start Command"**, pon:
   ```
   python start_services.py
   ```

### 2.4 Desplegar

1. Click en **"Deploy"**
2. Espera 2-3 minutos mientras Railway construye y despliega
3. ¡Listo! Railway te dará una URL pública

## 🌐 Paso 3: Obtener tu URL

1. En el dashboard de Railway, click en **"Settings"**
2. En **"Domains"**, click en **"Generate Domain"**
3. Railway generará una URL como: `vinylbe-production.up.railway.app`

## ✅ Paso 4: Verificar que Funciona

Abre tu navegador y ve a:

```
https://tu-app.up.railway.app/health
```

Deberías ver algo como:

```json
{
  "gateway": "healthy",
  "services": {
    "discogs": {"status": "healthy"},
    "recommender": {"status": "healthy"},
    "pricing": {"status": "healthy"},
    "lastfm": {"status": "healthy"}
  },
  "overall_status": "healthy"
}
```

## 🎨 Paso 5: Acceder a tu App

Ahora puedes acceder a tu aplicación en:

```
https://tu-app.up.railway.app
```

## 🔧 Troubleshooting

### ❌ Error: "Application failed to start"

**Solución:**
1. Ve a **"Deployments"** en Railway
2. Click en el deployment fallido
3. Revisa los logs para ver el error específico
4. Usualmente es por:
   - Variables de entorno faltantes
   - Dependencias en `requirements.txt` incompletas

### ❌ Error: "Service unhealthy"

**Solución:**
1. Verifica que todas las API keys sean correctas
2. Revisa los logs del servicio específico
3. Asegúrate de que los puertos internos (3001-3004) no estén bloqueados

### ❌ Error: "Database locked"

**Solución:**
1. Railway usa un sistema de archivos efímero por defecto
2. Necesitas añadir un **Volume** para persistir SQLite:
   - En Railway, ve a **"Volumes"**
   - Click en **"New Volume"**
   - Mount path: `/app/data`
   - Actualiza tu código para usar `/app/data/vinylbe.db`

## 📊 Monitoreo

### Ver Logs en Tiempo Real

En Railway:
1. Click en tu servicio
2. Ve a **"Deployments"**
3. Click en **"View Logs"**

### Métricas de Uso

Railway te muestra:
- CPU usage
- Memory usage
- Network traffic
- Request count

## 💰 Costos

Railway te da **$5 de crédito gratis** cada mes, que equivale a:
- ~500 horas de ejecución
- Perfecto para proyectos personales

Si necesitas más:
- **Hobby Plan**: $5/mes
- **Pro Plan**: $20/mes (para apps con mucho tráfico)

## 🔄 Actualizaciones Automáticas

Railway se actualiza automáticamente cuando haces push a GitHub:

```bash
# Hacer cambios en tu código
git add .
git commit -m "Update feature X"
git push origin main

# Railway detectará el push y redesplegará automáticamente
```

## 🎯 Próximos Pasos

1. **Dominio Personalizado**: Conecta tu propio dominio en Railway → Settings → Domains
2. **SSL/HTTPS**: Railway lo configura automáticamente
3. **Monitoreo**: Considera añadir Sentry o LogRocket para tracking de errores
4. **Base de datos**: Si crece mucho, migra de SQLite a PostgreSQL

## 📚 Recursos

- [Railway Docs](https://docs.railway.app)
- [Railway Discord](https://discord.gg/railway) - Soporte de la comunidad
- [Railway Status](https://status.railway.app) - Ver si hay problemas

---

## 🆘 ¿Necesitas Ayuda?

Si tienes problemas:

1. Revisa los logs en Railway
2. Verifica que todas las variables de entorno estén configuradas
3. Prueba localmente primero con `python start_services.py`
4. Consulta la guía completa en `GUIA_DESPLIEGUE.md`

---

**¡Felicidades! Tu app está en producción** 🎉

Comparte tu URL: `https://tu-app.up.railway.app`
