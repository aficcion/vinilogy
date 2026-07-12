# Vinilogy — M0

Reconstrucción de Vinilogy sobre la BD canónica **`vinology_core`**. Web de
recomendación de vinilos guiada por búsqueda. **M0** entrega el esqueleto y el
contrato de datos: **buscar → ficha de obra con ediciones en vinilo y precios**,
end-to-end. Sin motor de recomendación, sin embeddings, sin auth (eso es M1+).

Diseño completo: `~/Vinilogy/docs/DESIGN-vinylbe-v2-core.md`.

## Fuente de datos
Única fuente: `vinology_core`. La app **solo lee** (jamás hace DDL). DSN por env:

```
VINILOGY_DB_DSN=postgresql://localhost/vinology_core   # default
```

## Arrancar

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # ajusta si hace falta

VINILOGY_DB_DSN=postgresql://localhost/vinology_core \
  uvicorn app.main:app --reload --port 7788
```

Abre http://localhost:7788 y busca un disco o un artista.

## Rutas (M0)
- `GET /` — home con buscador.
- `GET /buscar?q=` — resultados: obras con vinilo + artistas.
- `GET /obra/{work_id}` — ficha rica: ediciones en vinilo + precios en tiendas ES.
- `GET /artista/{artist_id}` — discografía en vinilo ordenada por relevancia.

## Selftest (red de seguridad)

```bash
python3 -m tests.selftest
```

Checks duros contra core (fixtures derivados por SQL, no hardcodeados). Sale con
código != 0 si algo falla.

## Estructura

```
app/
  main.py            FastAPI: rutas Jinja
  db.py              pool psycopg2 + queries canónicas contra vinology_core
  domains/
    catalog/         búsqueda de works/artists, ficha, discografía
    pricing/         lectura de marketplace_listings, orden por precio, frescura
    reco/ semantic/ users/ editorial/   (stubs — M1+)
  web/
    templates/       Jinja (base + páginas)
    static/          CSS
tests/
  selftest.py        checks duros contra core
```

## Fuera de M0 (llega en M1+)
- Motor de recomendación híbrido (contenido + señal personal). — M1
- Embeddings / búsqueda por vibra-mood / APIs externas (OpenAI). — M1
- Auth (Discogs / Last.fm / invitado), colección, gap de vinilo. — M3
- Cajones editoriales, navegación de catálogo, serendipia. — M4
