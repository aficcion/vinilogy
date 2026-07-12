# BigSur · Retirar `vinylbe_local` por completo (diseño)

`vinylbe_local` (27 GB) es el prototipo pre-M4. Hoy hace **dos trabajos**:
1. **Fósil** (~27 GB): `albums`/`artists`/`tracks`/cachés `lastfm_*` → catálogo viejo,
   superseded por `vinology_core`. Solo lo lee el modo "proto" de Florent (dormido).
2. **Staging vivo** (~25 MB): `store_listings` + `store_price_history` +
   `store_scrape_runs` + `ebay_price_cache` → precios de tienda que se portan a core
   cada noche.

- **Paso A** (fósil) → `bigsur-retire-vinylbe-local-stepA.sql`. Reclama ~27 GB ya.
- **Paso B** (este doc) → reubicar el staging vivo para poder `DROP DATABASE vinylbe_local`.

---

## Flujo actual (precios)

```
vinilogy-scrapers  →  SQLite (data/scrapers.db)
      │  [loader: vinology-core/ingest/stores/run.py]
      ▼
vinylbe_local.store_listings (+ store_scrape_runs, store_price_history)
      │  [vinology-core/ingest/port_store_listings.py]  SRC=vinylbe_local
      ▼
vinology_core.marketplace_listings
      │
      ▼
Vinilogy (web)  — JOIN por work_id
```

**Objetivo Paso B**: sacar `vinylbe_local` de esta cadena.

---

## Opciones

### B1 — Plegar el staging DENTRO de core, en un schema `staging` (RECOMENDADA)
Crear `staging.store_listings` (+ runs/price_history) en `vinology_core`. El loader
escribe ahí; el "port" deja de ser cross-DB y pasa a un `INSERT … SELECT` interno
(`staging.store_listings` → `public.marketplace_listings`), transaccional y más rápido.
- **Pros**: una sola Postgres; sin port cross-DB; staging aislado en su schema; conserva
  el histórico (`store_price_history`, `store_scrape_runs`); `vinylbe_local` muere entero.
- **Contras**: staging convive con producción (mitigado por el schema separado).

### B2 — DB dedicada `bigsur_staging` (mínima)
Mover las tablas `store_*` a una Postgres nueva y pequeña; el port sigue cross-DB pero
con SRC=`bigsur_staging`.
- **Pros**: staging separado de core. **Contras**: sigues con 2 DBs y un port cross-DB.

### B3 — El port lee directo del SQLite de los scrapers
`port_store_listings` lee `data/scrapers.db` (SQLite) → core. Elimina también el loader.
- **Pros**: mínimas piezas. **Contras**: acopla el port a la ruta/schema del SQLite;
  pierdes el histórico en Postgres salvo que lo repliques; SQLite como fuente de un job
  nocturno cross-repo es más frágil.

**Recomendación: B1.** Es la que mejor encaja con "core es la plataforma de BigSur":
un solo Postgres, staging ordenado en su schema, y el port se simplifica a in-DB.

---

## Plan B1 (tareas)

0. **Confirmar el target actual del loader.** `ingest/stores/db.py` hace
   `_core_db.connect()`; verificar si hoy escribe a `vinylbe_local` (vía `PGDATABASE`)
   o ya a core. Eso dice cuánto queda por mover.
1. **Schema `staging` en core**: `CREATE SCHEMA staging;` + crear ahí `store_listings`,
   `store_scrape_runs`, `store_price_history`, `ebay_price_cache` (mismo DDL que en
   vinylbe_local). Migración versionada en `~/vinology-core/schema/`.
2. **Redirigir el loader** (`ingest/stores/`) a `staging.store_listings` en core.
3. **Convertir el port** (`ingest/port_store_listings.py`) de cross-DB (SRC=vinylbe_local)
   a in-DB: `INSERT INTO public.marketplace_listings … SELECT … FROM staging.store_listings`
   (misma lógica de paridad/frescura/bajas que ya tiene).
4. **(Una vez) portar el histórico** `store_price_history` de vinylbe_local → core.staging,
   si quieres conservarlo.

## Prueba (imprescindible antes de cortar)
- Correr **un ciclo nocturno completo** por el camino nuevo.
- Comparar `vinology_core.marketplace_listings` **antes/después**: nº de filas,
  `max(last_seen_at)`, y una muestra de precios por tienda — deben cuadrar con el camino
  viejo. Verificar que Vinilogy sigue mostrando precios (`/obra/{id}` con tienda).
- Dejar correr 1–2 noches en verde en paralelo (camino viejo aún vivo) antes de cortar.

## Cutover + borrado
1. Cuando el camino nuevo lleve 1–2 noches en verde: desactivar el loader/port viejos
   (los que apuntan a `vinylbe_local`).
2. **`DROP DATABASE vinylbe_local;`** (recupera el ~25 MB restante + retira la DB).

---

## Limpieza de referencias colgantes (al tocar esos repos)
Tras retirar `vinylbe_local`, quedan menciones a limpiar (dormidas, no rompen nada hoy):
- **Florent** (`~/vinology`): fallback proto en `db.py` (`_detect_backend`), defaults en
  `backup_user_data.py` y `poc/editorial/link.py`, y los docstrings de
  `test_tools_integrity_live` / `test_spotify_*_live` que aún dicen "requiere vinylbe_local"
  (probablemente ya corren contra core por el default). *(Ojo: hay sesiones autónomas
  activas en este repo — coordinar.)*
- **core** (`~/vinology-core`): defaults `SRC_DSN=dbname=vinylbe_local` en
  `port_store_listings.py` / `port_user_data.py`, `VINYLBE_URL` en `load_collection.py`.
  `port_user_data.py` fue la migración one-time del prototipo → si ya está hecha, es
  retirable.

## Notas de coordinación
- El repo **core** tiene worktrees/sesiones activas: hacer B cuando esté despejado.
- B toca el **pipeline vivo de precios** (nightly) → siempre con ciclo de prueba en
  paralelo antes de cortar. No es cambio de 5 minutos.
