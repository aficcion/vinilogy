"""Paquete `app`.

Carga `.env` de la raíz del repo en `os.environ` AL IMPORTAR el paquete, ANTES de
que cualquier submódulo lea variables de entorno (DSN de la BD en `db.py`,
credenciales de Discogs en `covers.py`). Sin esto, arrancar con
`uvicorn app.main:app` dejaba `DISCOGS_KEY`/`DISCOGS_SECRET` fuera de `os.environ`
→ `covers._configured()` = False → el backfill de portadas quedaba APAGADO en
silencio y los discos sin portada nunca se recuperaban (ni aparecían en búsqueda).

Ligero y sin dependencia externa. NO pisa lo ya definido en el entorno (una var
exportada a mano manda sobre `.env`).
"""
import os as _os


def _load_dotenv():
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    path = _os.path.join(root, ".env")
    if not _os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in _os.environ:
                _os.environ[key] = val


_load_dotenv()
