# Checklist P0 — antes de abrir Vinilogy al público

P0 = bloquea el lanzamiento público. Marca `[x]` según cierres. Referencias por
símbolo (robustas a cambios de línea).

Leyenda de esfuerzo/dueño:
- 🟢 **código, sin decisión** — se puede implementar ya, bajo riesgo.
- 🟡 **decisión** — depende del hosting o de producto; hay que elegir antes.

---

## ✅ Ya resueltos (P1 / Fase 1) — contexto

- [x] **Bug de precios en tarjetas**: `cheapest_prices_for_works` casa por `ml.work_id`
      (antes trigram/substring → cruzaba álbumes). Tarjeta y ficha coinciden.
- [x] **Disclaimer edición≠precio** en la ficha; **copy honesto** (fuera "cada tienda
      independiente" / "actualizado a diario"); **fugas de dev** ("v2", "M3a").
- [x] **Móvil**: tabla de precios con scroll; topbar/footer afinados.
- [x] **Privacidad + GDPR**: `/privacidad`, `/account/export`, borrado ya existía.
- [x] **Minimización Google** (Fase 1): no se persiste su token (migración 003).

---

## 🚩 Pendientes P0 (bloquean el lanzamiento)

### 1. 🟢 Cookies `Secure` + HTTPS/HSTS
- **Riesgo**: `_set_session_cookie` y `_set_oauth_state_cookie` (`app/main.py`) ponen
  `httponly` + `samesite="lax"` pero **no `secure`**. Sobre HTTPS público, la sesión
  (90 días) y la cookie CSRF de OAuth pueden viajar en claro → SameSite deja de proteger.
- **Qué hacer**: `secure=True` en ambas cookies y en sus `delete_cookie`, condicionado a
  entorno (p.ej. `VINILOGY_SECURE_COOKIES=1` en prod; en dev local sobre http queda off o
  no habría login). Terminar TLS + HSTS en el proxy.
- **Verificación**: en prod, la respuesta de login trae `Set-Cookie: ...; Secure`.

### 2. 🟢 Manejo de errores + logging + `/health`
- **Riesgo**: no hay `@app.exception_handler`, ni `logging.basicConfig`, ni `/health`.
  Cualquier hipo de DB en `/obra`, `/mi`, `/buscar`… sale como **500 de texto plano sin
  marca y sin log** — no te enteras. El deploy tampoco puede sondear readiness.
- **Qué hacer**: handler global → página 500 con marca; `logging.basicConfig` al arranque
  (los `log.warning` de `covers.py` hoy no salen a ningún sitio); ruta `/health` que
  haga `SELECT 1` contra el pool.
- **Verificación**: forzar un error → 500 con marca + línea de log; `GET /health` → 200.

### 3. 🟡 Modelo de proceso + estado OAuth (FlowStore)
- **Riesgo**: `FlowStore` es memoria en-proceso (`oauth.py:245`/`285`). Con
  `--workers >1` cada login OAuth falla aleatoriamente (state guardado en worker A,
  callback en worker B → "estado no encontrado").
- **Decisión**: (a) **1 worker fijado** (uvicorn 1 proc), documentado, o (b) mover el
  estado del flow a la DB / cookie firmada para escalar horizontal. Recomendado para
  empezar: (a) — simple y suficiente para el tráfico inicial.
- **Verificación**: login Google/Discogs/Last.fm completa en el modelo elegido.

### 4. 🟡 Configuración de producción
- **Riesgo**: no hay Dockerfile/Procfile/gunicorn; `.claude/launch.json` es
  `uvicorn --reload` (dev). Falta comando prod real.
- **Qué hacer** (según hosting): arranque sin `--reload`, con `--proxy-headers` (IP real
  tras proxy), workers según decisión #3; Dockerfile/Procfile o unidad systemd.
- **Checklist de entorno** (ver tabla abajo).
- **Verificación**: arranque prod levanta y sirve `/health`.

### 5. 🟢 Pool de conexiones (tamaño + conexión viva)
- **Riesgo**: `ThreadedConnectionPool(minconn=1, maxconn=10)` (`db.py:181`) mientras
  `/mi` abre **4 conexiones por request** (`ThreadPoolExecutor`). ~3 `/mi` simultáneos =
  12 > 10 → `getconn()` **lanza `PoolError`** (no bloquea) → 500s en el primer pico.
  Además `_cursor()` (`db.py:185`) no comprueba `conn.closed` → una conexión que
  Postgres/pgbouncer cerró por idle se reparte muerta → 500s intermitentes.
- **Qué hacer**: subir `maxconn` (p.ej. 20–30, acotado a `max_connections` de Postgres);
  chequear liveness (descartar/reemplazar si `conn.closed`).
- **Verificación**: N cargas concurrentes de `/mi` sin `PoolError`.

### 6. 🟡 Rate limiting
- **Riesgo**: `/api/suggest` y `/buscar` lanzan queries multi-CTE/KNN/trigram caras sin
  throttle; expuestas invitan a DoS por agotamiento de DB/pool. Los endpoints de OAuth
  tampoco tienen límite.
- **Decisión**: a nivel app (dependencia tipo `slowapi`) o a nivel proxy (nginx
  `limit_req`). Recomendado empezar en el proxy (sin tocar código).
- **Verificación**: ráfaga sobre `/api/suggest` recibe 429 pasado el umbral.

### 7. 🟡 Personalización `/mi` vacía (producto)
- **Riesgo**: la app es solo-lectura; **no ingiere** colección/escucha (lo hace el
  pipeline de core). Un usuario que conecta Discogs/Last.fm puede caer en `/mi` con
  "Para ti / Sube a vinilo / Basado en lo que escuchas" **vacíos**, y el copy dice
  *"Conecta Discogs/Last.fm en la próxima entrega"* (`mi.html:65`) a quien **acaba de
  conectar**.
- **Decisión**: (a) disparar una ingesta real al conectar con estado "importando… (≈Xh)",
  o (b) si la ingesta sigue fuera de banda, condicionar los CTA con copy honesto y no
  mostrar secciones vacías como si estuvieran rotas. En ambos casos: **quitar el
  "en la próxima entrega"**.
- **Verificación**: flujo de usuario nuevo que conecta → no ve un muro vacío sin explicar.

### 8. 🟡 Verificación de entorno en prod
- **Riesgo**: config mal puesta rompe en silencio.
- **Qué comprobar** antes de abrir:

| Variable | Por qué es P0 |
|---|---|
| `VINILOGY_DEV_LOGIN` **sin definir** | Si queda `=1`, `POST /dev/login/{id}` es **bypass total de auth** (`main.py`, entra como cualquier usuario) |
| `VINILOGY_BASE_URL` = dominio real https | Construye los `redirect_uri` de OAuth; si falta, **los 3 logins OAuth se rompen** |
| `VINILOGY_DB_DSN` = DSN de prod con credenciales | El default `localhost/bigsur_core` no vale en prod |
| `DISCOGS_KEY` / `DISCOGS_SECRET` presentes | Si faltan, el worker de covers no arranca (`covers._enabled()` False) → **secciones casi vacías** (83% de works sin portada dependen del backfill) |
| Migraciones **003** aplicadas al core de prod | Si no, el login de Google falla (CHECK viejo vs código que pasa `None`) |

---

## Orden sugerido

1. 🟢 Rápidas de código (#1 cookies, #2 errores/health, #5 pool) — bajo riesgo, alto valor.
2. 🟡 Decidir modelo de proceso (#3) → de ahí sale la config de prod (#4).
3. 🟡 Rate limiting en el proxy (#6) junto con TLS/HSTS.
4. 🟡 Cerrar la historia de `/mi` (#7) — decisión de producto, la de más impacto en
   percepción.
5. 🟡 Repasar el checklist de entorno (#8) en el deploy.

---

## Qué puedo implementar ya (sin decisiones)
`#1` cookies Secure (env-driven), `#2` exception handler + logging + `/health`, `#5`
pool (maxconn + liveness). Los demás esperan tu decisión de hosting/producto.
