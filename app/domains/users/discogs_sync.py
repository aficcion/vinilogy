"""Sync + refresco de la colección de Discogs de un usuario, para prod.

Espejo de `lastfm_sync`. Vinilogy sólo LEÍA la colección (la poblaba Florent); ahora
también la importa y la refresca de forma perezosa al abrir /mi. Baja la colección
PÚBLICA directo de api.discogs.com con las credenciales de app (key+secret) — igual que
Florent, sin OAuth 1.0a del usuario. La escritura/resolución vive en `db`.

NO lanza: cualquier fallo se loguea y se traga (nunca rompe login ni /mi).
"""
from __future__ import annotations

import logging
import re
import threading

import httpx

from app import db
from app.domains.users import oauth

log = logging.getLogger(__name__)

_API = "https://api.discogs.com"
_HEADERS = {"User-Agent": "Vinilogy/1.0 (+https://www.vinilogy.com)"}
_PER_PAGE = 100
_MAX_PAGES = 40  # tope defensivo (40×100 = 4000 ítems)
_TTL_HOURS = 24

_syncing: set[int] = set()
_syncing_lock = threading.Lock()


def sync_discogs_collection(user_id, username):
    """Baja la colección de `username` y la upsertea+resuelve. Idempotente."""
    if not user_id or not username:
        return
    cfg = oauth.config()
    key, secret = cfg.get("discogs_key"), cfg.get("discogs_secret")
    if not key or not secret:
        return
    try:
        total = 0
        with httpx.Client(timeout=20.0, headers=_HEADERS) as client:
            for page in range(1, _MAX_PAGES + 1):
                r = client.get(
                    f"{_API}/users/{username}/collection/folders/0/releases",
                    params={"key": key, "secret": secret,
                            "page": page, "per_page": _PER_PAGE})
                if r.status_code != 200:
                    break
                data = r.json()
                releases = data.get("releases") or []
                if not releases:
                    break
                total += db.upsert_discogs_collection(
                    user_id, [_parse_release(rel) for rel in releases])
                if page >= (data.get("pagination") or {}).get("pages", 1):
                    break
        db.upsert_discogs_profile(user_id, username)  # sello de frescura
        log.info("Discogs collection sync OK user=%s (%s): %s ítems",
                 user_id, username, total)
    except Exception as e:  # noqa: BLE001 — nunca rompe la petición
        log.warning("Discogs sync falló user=%s (%s): %s", user_id, username, e)


def maybe_refresh_collection(user_id):
    """Refresco PEREZOSO: si el usuario tiene Discogs y su colección está vieja (>TTL)
    y no hay sync en curso, re-sincroniza en segundo plano. No bloquea. Como Florent."""
    if not user_id:
        return
    username = db.discogs_username(user_id)
    if not username:
        return
    if not db.discogs_collection_is_stale(user_id, _TTL_HOURS):
        return
    with _syncing_lock:
        if user_id in _syncing:
            return
        _syncing.add(user_id)
    threading.Thread(target=_bg_sync, args=(user_id, username), daemon=True).start()


def _bg_sync(user_id, username):
    try:
        sync_discogs_collection(user_id, username)
    finally:
        with _syncing_lock:
            _syncing.discard(user_id)


def _parse_release(rel):
    """Un release de la API de Discogs (`basic_information`) → ítem para el upsert.
    Portado tal cual de Florent (_parse_collection_release)."""
    basic = rel.get("basic_information", {})
    formats = basic.get("formats", [])
    fmt_descs = formats[0].get("descriptions", []) if formats else []
    fmt_name = formats[0].get("name", "").upper() if formats else ""

    if "VINYL" in fmt_name or "LP" in fmt_name:
        cat = "VINYL"
    elif "CD" in fmt_name:
        cat = "CD_FORMAT"
    else:
        cat = "OTHERS"

    if "Compilation" in fmt_descs:
        rtype = "Compilation"
    elif any(d in fmt_descs for d in ["Album", "LP", "Mini-Album"]):
        rtype = "Album"
    elif "EP" in fmt_descs:
        rtype = "EP"
    elif any(d in fmt_descs for d in ["Single", '7"', '12"']):
        rtype = "Single"
    else:
        rtype = "Other"

    labels = basic.get("labels", [])
    return {
        "release_id": rel.get("id"),
        "master_id": basic.get("master_id"),
        "title": basic.get("title"),
        "artist": re.sub(r" \(\d+\)$", "", (basic.get("artists") or [{}])[0].get("name", "")),
        "internal_category": cat,
        "release_type": rtype,
        "year": basic.get("year", 0),
        "label": labels[0].get("name") if labels else None,
        "cover_url": basic.get("thumb") or basic.get("cover_image"),
        "discogs_added_at": rel.get("date_added"),
    }
