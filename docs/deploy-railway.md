# Deploy en Railway — Vinilogy v2

v2 es **una sola app FastAPI** (`app.main:app`), a diferencia del v1 (multi-servicio
con `start_services.py`, gateway, etc.). Por eso NO se reutiliza el arranque de v1;
aquí van `Dockerfile` + `railway.toml` propios.

Piezas en el repo:
- `Dockerfile` — python:3.11-slim, 1 worker, `--proxy-headers`, bind a `$PORT`.
- `railway.toml` — build por Dockerfile, `healthcheckPath=/health`, restart on-failure.
- `/health` — ping a la BD (ya implementado).

---

## Base de datos — `bigsur_core` en Railway Postgres (decidido)

`bigsur_core` vivirá en una **Postgres de Railway**. Implicaciones a resolver en el
setup (no en código):
- **Cargar el catálogo** en esa Postgres: es un volcado grande (millones de releases +
  las tablas de la capa usuario). Restaurar un `pg_dump` de `bigsur_core` en la
  instancia de Railway. Ese import lo hace el pipeline/proceso de core, no la app.
- **Conexión**: añade el plugin Postgres en el proyecto de Railway y pon
  `VINILOGY_DB_DSN` = la connection string interna (p.ej. referenciando
  `${{Postgres.DATABASE_URL}}` en las variables del servicio). Usa el host **privado**
  de Railway para no salir a internet.
- **Migraciones**: aplica `001/002/003` sobre esa Postgres (ver checklist).
- Vigila `max_connections` del plan de Railway vs `VINILOGY_DB_POOL_MAX` (def. 24).

---

## Variables de entorno (panel de Railway — NUNCA en el repo)

| Variable | Valor | Notas |
|---|---|---|
| `VINILOGY_DB_DSN` | DSN de la Postgres con `bigsur_core` (prod) | Bloqueante #1. Con `?sslmode=require` si aplica |
| `VINILOGY_BASE_URL` | `https://<tu-dominio>` | Debe casar EXACTO con los redirect URIs registrados |
| `VINILOGY_SECURE_COOKIES` | `1` | Cookies con flag Secure (estás sobre HTTPS) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | de Google Cloud Console | Redirect: `<BASE_URL>/auth/google/callback` |
| `DISCOGS_KEY` / `DISCOGS_SECRET` | de Discogs | Redirect: `<BASE_URL>/auth/discogs/callback`. **También** habilita el worker de covers |
| `LASTFM_API_KEY` / `LASTFM_API_SECRET` | de Last.fm | Callback: `<BASE_URL>/auth/lastfm/callback` |
| `VINILOGY_DB_POOL_MAX` | `24` (o según `max_connections`) | Opcional |
| `VINILOGY_LOG_LEVEL` | `INFO` | Opcional |
| `VINILOGY_DEV_LOGIN` | **NO DEFINIR** | `=1` sería bypass total de auth |

Railway inyecta `PORT` solo; el arranque ya lo usa.

---

## Checklist antes del primer deploy

- [ ] `VINILOGY_DB_DSN` de prod resuelto (bloqueante #1) y probado.
- [ ] **Migraciones aplicadas al core de prod**: `001`, `002` y **`003`** (esta última
      es imprescindible: si no, el login de Google falla con el código actual).
- [ ] Redirect URIs de Google/Discogs/Last.fm registrados con el dominio de prod.
- [ ] `VINILOGY_SECURE_COOKIES=1` y `VINILOGY_DEV_LOGIN` sin definir.
- [ ] `DISCOGS_KEY/SECRET` presentes (si no, secciones casi vacías por falta de covers).
- [ ] Tras deploy: `GET /health` → 200; probar los 3 logins OAuth.

---

## Pisar el repo de GitHub (v1 → v2) de forma segura

Estado: el repo local de v2 **no tiene remote**; el v1 vive en `aficcion/Vinilogy`
(público) con su historia. Quieres subir v2 como nueva versión sobre ese repo.

⚠️ Las historias de v1 y v2 son independientes → reemplazar `main` requiere
`--force`, que **descarta la historia de v1 en `main`**. Antes de nada, **preservar
v1**. Plan recomendado (a ejecutar TÚ, o yo con tu OK explícito — es destructivo):

```bash
# 1) Archivar v1 para no perderlo (rama + tag desde el estado actual del remoto)
cd /ruta/al/clon/de/v1     # o un clon fresco de aficcion/Vinilogy
git checkout main && git pull
git branch v1-archive && git push -u origin v1-archive
git tag v1-final && git push origin v1-final

# 2) Desde el repo de v2, apuntar al remoto y reemplazar main
cd /Users/carlos/vinylbe-v2
git remote add origin git@github.com:aficcion/Vinilogy.git
git push --force origin HEAD:main     # reemplaza main con la historia de v2
```

Alternativa menos agresiva: crear un **repo nuevo** (`vinilogy` / `vinylbe-v2`) y dejar
v1 intacto — Railway apunta al repo nuevo. Recomendado si no te urge reutilizar el
nombre/estrellas del repo v1.

**No haré ningún push sin tu confirmación explícita** del método (force sobre v1 vs
repo nuevo) y sin haber archivado v1 antes.
