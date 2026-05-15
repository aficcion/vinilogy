# 📦 Guía de Despliegue - Vinylbe App

Esta guía te explica las mejores opciones para publicar tu aplicación de recomendaciones de vinilos.

## 🏗️ Arquitectura Actual

Tu aplicación tiene:
- **5 microservicios** Python (FastAPI + Uvicorn)
- **Frontend estático** (HTML/CSS/JS)
- **Base de datos SQLite**
- **APIs externas**: Discogs, Last.fm, eBay

---

## 🚀 Opción 1: Railway (Recomendada - Más Fácil)

**✅ Ventajas:**
- Despliegue automático desde Git
- Soporte nativo para monorepos con múltiples servicios
- Base de datos SQLite persistente con volúmenes
- HTTPS automático
- Dominio gratuito incluido
- Plan gratuito: $5 de crédito/mes (~500 horas)

**📋 Pasos:**

### 1. Preparar el proyecto

Primero, necesitas crear archivos de configuración para cada servicio:

```bash
# Crear Procfile para Railway
echo "web: python -m uvicorn gateway.main:app --host 0.0.0.0 --port \$PORT" > Procfile
```

### 2. Crear railway.toml

```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "python start_services.py"
healthcheckPath = "/health"
healthcheckTimeout = 100
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

[[services]]
name = "vinylbe-gateway"
```

### 3. Actualizar requirements.txt

Asegúrate de que todas las dependencias estén listadas:

```txt
fastapi
uvicorn[standard]
httpx
streamlit
pandas
beautifulsoup4
python-multipart
python-dotenv
discogs-client
pylast
requests
```

### 4. Desplegar

1. Ve a [railway.app](https://railway.app)
2. Conecta tu repositorio de GitHub
3. Selecciona el proyecto Vinylbe
4. Configura las variables de entorno (`.env`)
5. Railway detectará automáticamente Python y desplegará

**💰 Costo:** Gratis para empezar, luego ~$5-10/mes

---

## 🚀 Opción 2: Render (Alternativa Gratuita)

**✅ Ventajas:**
- Plan gratuito permanente
- Despliegue desde Git
- HTTPS automático
- Fácil configuración

**⚠️ Limitaciones:**
- Los servicios gratuitos se "duermen" después de 15 min de inactividad
- Arranque lento (puede tardar 30-50 segundos en despertar)
- 750 horas/mes gratis

**📋 Pasos:**

### 1. Crear render.yaml

```yaml
services:
  # Gateway principal
  - type: web
    name: vinylbe-gateway
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: python -m uvicorn gateway.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /health
    envVars:
      - key: DISCOGS_SERVICE_URL
        value: http://localhost:3001
      - key: RECOMMENDER_SERVICE_URL
        value: http://localhost:3002
      - key: PRICING_SERVICE_URL
        value: http://localhost:3003
      - key: LASTFM_SERVICE_URL
        value: http://localhost:3004

  # Base de datos (disco persistente)
  - type: pserv
    name: vinylbe-db
    env: docker
    disk:
      name: vinylbe-data
      mountPath: /data
      sizeGB: 1
```

### 2. Desplegar

1. Ve a [render.com](https://render.com)
2. Conecta tu repositorio
3. Render detectará `render.yaml` automáticamente
4. Configura las variables de entorno secretas (API keys)
5. Despliega

**💰 Costo:** Gratis (con limitaciones), o $7/mes por servicio sin limitaciones

---

## 🚀 Opción 3: Fly.io (Mejor para Microservicios)

**✅ Ventajas:**
- Excelente para arquitecturas de microservicios
- Volúmenes persistentes para SQLite
- Red privada entre servicios
- Plan generoso gratuito
- Despliegue global (CDN)

**📋 Pasos:**

### 1. Instalar Fly CLI

```bash
# macOS
brew install flyctl

# Autenticarse
fly auth login
```

### 2. Crear fly.toml

```toml
app = "vinylbe"
primary_region = "mad" # Madrid

[build]
  builder = "paketobuildpacks/builder:base"

[env]
  PORT = "5000"

[http_service]
  internal_port = 5000
  force_https = true
  auto_stop_machines = true
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  cpu_kind = "shared"
  cpus = 1
  memory_mb = 512

[mounts]
  source = "vinylbe_data"
  destination = "/data"
```

### 3. Crear volumen para SQLite

```bash
fly volumes create vinylbe_data --size 1 --region mad
```

### 4. Desplegar

```bash
fly launch
fly deploy
```

**💰 Costo:** Gratis hasta 3 máquinas pequeñas, luego ~$5-10/mes

---

## 🚀 Opción 4: Docker + VPS (Máximo Control)

**✅ Ventajas:**
- Control total
- Más barato a largo plazo
- Sin limitaciones de tiempo de ejecución

**⚠️ Requiere:**
- Conocimientos de Linux/Docker
- Configuración manual de HTTPS (Let's Encrypt)
- Mantenimiento del servidor

**📋 Pasos:**

### 1. Crear Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "start_services.py"]
```

### 2. Crear docker-compose.yml

```yaml
version: '3.8'

services:
  vinylbe:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./vinylbe.db:/app/vinylbe.db
      - ./data:/app/data
    environment:
      - DISCOGS_API_KEY=${DISCOGS_API_KEY}
      - LASTFM_API_KEY=${LASTFM_API_KEY}
      - EBAY_APP_ID=${EBAY_APP_ID}
    restart: unless-stopped
```

### 3. Desplegar en VPS

Proveedores recomendados:
- **DigitalOcean** ($6/mes - droplet básico)
- **Hetzner** (€4/mes - muy barato)
- **Linode** ($5/mes)
- **Vultr** ($5/mes)

```bash
# En tu VPS
git clone <tu-repo>
cd vinylbe
docker-compose up -d
```

### 4. Configurar HTTPS con Nginx + Let's Encrypt

```bash
# Instalar Nginx
sudo apt install nginx certbot python3-certbot-nginx

# Obtener certificado SSL
sudo certbot --nginx -d tudominio.com
```

**💰 Costo:** $5-10/mes (VPS) + dominio (~$12/año)

---

## 🚀 Opción 5: Replit (Desarrollo/Prototipos)

**✅ Ventajas:**
- Despliegue instantáneo
- IDE en la nube
- Muy fácil de usar

**⚠️ Limitaciones:**
- No recomendado para producción
- Rendimiento limitado
- Se duerme si no hay actividad

Veo que ya tienes `.replit` configurado, así que solo necesitas:

1. Ir a [replit.com](https://replit.com)
2. Importar desde GitHub
3. Click en "Run"
4. Replit te dará una URL pública automáticamente

**💰 Costo:** Gratis (limitado), o $7/mes (Hacker plan)

---

## 📊 Comparación Rápida

| Opción | Dificultad | Costo/mes | Mejor para | Tiempo setup |
|--------|-----------|-----------|------------|--------------|
| **Railway** | ⭐ Fácil | $5-10 | Producción rápida | 10 min |
| **Render** | ⭐ Fácil | Gratis/$7 | Proyectos personales | 15 min |
| **Fly.io** | ⭐⭐ Media | Gratis/$5-10 | Microservicios | 20 min |
| **VPS + Docker** | ⭐⭐⭐ Difícil | $5-10 | Control total | 1-2 horas |
| **Replit** | ⭐ Muy fácil | Gratis/$7 | Demos/prototipos | 5 min |

---

## 🎯 Mi Recomendación

Para tu caso específico, te recomiendo **Railway** porque:

1. ✅ Soporta múltiples servicios fácilmente
2. ✅ SQLite funciona bien con volúmenes persistentes
3. ✅ Despliegue automático desde Git
4. ✅ HTTPS y dominio incluidos
5. ✅ Buen balance precio/facilidad

**Plan de acción:**
1. Sube tu código a GitHub (si no lo has hecho)
2. Crea cuenta en Railway
3. Conecta el repo
4. Configura variables de entorno
5. ¡Despliega en 10 minutos!

---

## 🔐 Checklist Antes de Desplegar

- [ ] Todas las API keys están en variables de entorno (no en el código)
- [ ] `.env` está en `.gitignore`
- [ ] `requirements.txt` está completo
- [ ] La base de datos SQLite se puede recrear o migrar
- [ ] Has probado la app localmente con `python start_services.py`
- [ ] Tienes un backup de `vinylbe.db`

---

## 🆘 Problemas Comunes

### SQLite en producción
- **Problema:** SQLite puede tener problemas con alta concurrencia
- **Solución:** Para producción seria, considera migrar a PostgreSQL

### Servicios múltiples
- **Problema:** Algunos hosts gratuitos solo permiten 1 servicio
- **Solución:** Combina todos los servicios en un solo proceso o usa Railway/Fly.io

### Variables de entorno
- **Problema:** Las API keys no funcionan
- **Solución:** Verifica que estén configuradas en el panel del hosting

---

## 📚 Recursos Adicionales

- [Railway Docs](https://docs.railway.app)
- [Render Docs](https://render.com/docs)
- [Fly.io Docs](https://fly.io/docs)
- [Docker Compose](https://docs.docker.com/compose)

---

¿Necesitas ayuda con alguna opción específica? ¡Avísame y te ayudo a configurarla! 🚀
