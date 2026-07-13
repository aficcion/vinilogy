"""Sync de la capa de escucha de Last.fm de un usuario, para prod.

Baja los top artistas/álbumes del usuario desde la API de Last.fm (método público
user.getTop*, sólo api_key) y delega en `db` la persistencia + la resolución contra
el catálogo (por MusicBrainz id). En dev esto lo hacía el pipeline del core; aquí lo
hace Vinilogy al conectar Last.fm (igual que importa la colección de Discogs).

NO lanza: cualquier fallo (Last.fm caído, usuario sin scrobbles, red) se loguea y se
traga — nunca debe romper el login/OAuth.
"""
from __future__ import annotations

import logging
import threading

import httpx

from app import db
from app.domains.users import oauth

log = logging.getLogger(__name__)

_API_ROOT = "https://ws.audioscrobbler.com/2.0/"
# Last.fm resetea conexiones sin User-Agent propio (curl funciona, httpx por defecto no).
_HEADERS = {"User-Agent": "Vinilogy/1.0 (+https://www.vinilogy.com)"}
# 'overall' es el periodo que lee la reco por escucha (_LISTEN_PERIOD en db.py);
# poblamos los tres para cubrir cualquier vista.
_PERIODS = ("1month", "6month", "overall")
_LIMIT = 50

# Refresco perezoso: re-sincroniza si los datos son más viejos que esto. Como Florent.
_TTL_HOURS = 24
# Centinela en memoria para no lanzar dos syncs a la vez del mismo usuario (1 worker).
_syncing: set[int] = set()
_syncing_lock = threading.Lock()


def sync_lastfm_user(user_id, username):
    """Fetch + upsert + resolución de la capa Last.fm de `user_id`. Idempotente."""
    if not user_id or not username:
        return
    api_key = oauth.config().get("lastfm_key")
    if not api_key:
        return
    try:
        with httpx.Client(timeout=12.0, headers=_HEADERS) as client:
            info = _fetch_info(client, api_key, username)
            for period in _PERIODS:
                artists = _fetch(client, api_key, "user.getTopArtists",
                                 "topartists", "artist", username, period)
                db.upsert_lastfm_artists(user_id, period, artists)
                albums = _fetch(client, api_key, "user.getTopAlbums",
                                "topalbums", "album", username, period)
                db.upsert_lastfm_albums(user_id, period, albums)
        db.resolve_lastfm_user(user_id)
        # Sello de frescura (updated_at) para el refresco perezoso.
        db.upsert_lastfm_profile(user_id, username,
                                 info.get("playcount"), info.get("country"))
        log.info("Last.fm sync+resolve OK user=%s (%s)", user_id, username)
    except Exception as e:  # noqa: BLE001 — nunca rompe el login
        log.warning("Last.fm sync falló user=%s (%s): %s", user_id, username, e)


def maybe_refresh_lastfm(user_id):
    """Refresco PEREZOSO: si el usuario tiene Last.fm y sus datos están viejos (>TTL)
    y no hay ya un sync en curso, re-sincroniza en segundo plano. No bloquea la página
    (los datos frescos entran para la próxima carga). Mismo patrón que Florent."""
    if not user_id:
        return
    username = db.lastfm_username(user_id)
    if not username:
        return
    if not db.lastfm_is_stale(user_id, _TTL_HOURS):
        return
    with _syncing_lock:
        if user_id in _syncing:
            return
        _syncing.add(user_id)
    threading.Thread(target=_bg_sync, args=(user_id, username), daemon=True).start()


def _bg_sync(user_id, username):
    try:
        sync_lastfm_user(user_id, username)
    finally:
        with _syncing_lock:
            _syncing.discard(user_id)


def _fetch_info(client, api_key, username):
    r = client.get(_API_ROOT, params={
        "method": "user.getInfo", "user": username,
        "api_key": api_key, "format": "json",
    })
    r.raise_for_status()
    return r.json().get("user") or {}


def _fetch(client, api_key, method, root_key, item_key, username, period):
    r = client.get(_API_ROOT, params={
        "method": method, "user": username, "period": period,
        "limit": _LIMIT, "page": 1, "api_key": api_key, "format": "json",
    })
    r.raise_for_status()
    items = (r.json().get(root_key) or {}).get(item_key) or []
    if isinstance(items, dict):  # Last.fm devuelve dict si hay un único item
        items = [items]
    return items[:_LIMIT]
