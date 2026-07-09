"""Dominio covers — recuperación ON-DEMAND de portadas desde Discogs.

Problema (crítico): ~93% de las portadas de core cuelgan de Cover Art Archive
(`coverartarchive.org`), que responde 502/timeout o tarda 2-3s → en el navegador
salen SIN portada. Las de Discogs (`i.discogs.com`) cargan en ~0,07s y son fiables,
pero solo ~205K works las tienen. Además ~83% de works con vinilo no tienen NINGUNA.

Solución (decisión de Carlos): "Que se llame directamente a Discogs para recuperar
la URL y se guarde en BD; si no se puede recuperar el cover, no se muestra."
Implementado AUTO-REPARABLE y SIN BLOQUEAR la request:
  - al renderizar works sin portada FIABLE, la vista llama `request_missing(works)`,
    que filtra los `needs_reliable_cover` y hace `enqueue` (O(1), no bloquea).
  - un worker daemon procesa la cola respetando el RATE LIMIT de Discogs
    (~55 req/min, autenticado 60/min → ~1 cada 1,1s), pide la portada a la API,
    la guarda en core `cover_images(source='discogs')` (upsert) y la próxima carga
    ya la tiene (la vista `v_work_cover` prefiere 'discogs' sobre 'caa').
  - Discogs sin imagen → no se guarda nada → sigue el placeholder `♫` (91b87b8).

Rate-limit + cortesía (los tokens de Discogs se COMPARTEN con otros sistemas de la
máquina — Florent, el nightly de tiendas): respetar `Retry-After` en 429 con cap
corto y DEGRADAR; nunca martillear. Un set "ya intentado" con TTL evita re-pedir
works ya intentados (con o sin éxito) en cada render.

Flag `VINYLBE_COVER_BACKFILL` (default ON si hay credenciales; OFF si faltan →
no-op silencioso). El fetch es fire-and-forget: si el worker cae, la web sigue.
"""
import os
import time
import threading
import logging
from collections import OrderedDict

import requests

from app import db

log = logging.getLogger("vinylbe.covers")

# --- Configuración -----------------------------------------------------------

_UA = "Vinylbe/2.0"
_API = "https://api.discogs.com"
_TIMEOUT = 6.0            # s por request a Discogs (+1 retry)
_RATE_MIN_INTERVAL = 1.1  # s entre requests (~54/min < 55 objetivo < 60/min)
_RETRY_AFTER_CAP = 5.0    # s máximo que esperamos ante un 429 (si no, degradar)
_QUEUE_CAP = 5000         # cap de la cola (descarta excedente con log)
_TRIED_TTL = 6 * 3600     # s: no re-pedir un work ya intentado en 6h
_TRIED_MAX = 100_000      # cap del set "ya intentado" (LRU-ish por inserción)

_DISCOGS_HOST = "i.discogs.com"  # host de portada FIABLE


def _configured():
    return bool((os.environ.get("DISCOGS_KEY") or "").strip()
                and (os.environ.get("DISCOGS_SECRET") or "").strip())


def _enabled():
    """Flag: default ON si hay credenciales; OFF si el usuario lo apaga o faltan."""
    flag = (os.environ.get("VINYLBE_COVER_BACKFILL") or "").strip().lower()
    if flag in ("0", "false", "off", "no"):
        return False
    return _configured()


def _auth_header():
    return {
        "User-Agent": _UA,
        "Authorization": "Discogs key={}, secret={}".format(
            os.environ.get("DISCOGS_KEY") or "",
            os.environ.get("DISCOGS_SECRET") or ""),
    }


# --- ¿La portada actual es fiable? -------------------------------------------

def _url_is_reliable(url):
    """True si la URL de portada es de Discogs (`i.discogs.com`), la fuente rápida
    y fiable. CAA (`coverartarchive.org`) → NO fiable (502/timeout en el navegador).
    """
    if not url:
        return False
    return _DISCOGS_HOST in url


def needs_reliable_cover(work_row):
    """True si el work NO tiene portada fiable y merece intento de backfill.

    Un work_row es un dict de render que ya trae `cover_url` (y opcionalmente info
    de fuente `has_discogs`/`has_caa` si vino del helper de db). Reglas:
      - sin `cover_url` → True (no tiene nada, o solo CAA que no resolvió).
      - `cover_url` de CAA (host no fiable) → True (queremos la de Discogs).
      - `cover_url` de Discogs → False (ya está lo bueno).
    Si el dict trae `has_discogs=True` explícito, es False sin mirar la URL.
    """
    if not work_row:
        return False
    if work_row.get("has_discogs"):
        return False
    return not _url_is_reliable(work_row.get("cover_url"))


# --- Cliente Discogs de portada ----------------------------------------------

def _pick_primary_image(images):
    """De `images[]` de Discogs, la primaria (`type='primary'` si existe, si no la
    primera) → (uri, uri150) o None si no hay imagen usable."""
    if not images:
        return None
    primary = None
    for img in images:
        if isinstance(img, dict) and img.get("type") == "primary":
            primary = img
            break
    img = primary or (images[0] if isinstance(images[0], dict) else None)
    if not img:
        return None
    url = img.get("uri") or img.get("resource_url")
    thumb = img.get("uri150") or img.get("uri") or url
    if not url:
        return None
    return url, thumb


def _get_json(path):
    """GET autenticado a Discogs con timeout + 1 retry. Devuelve (json|None).

    429: respeta `Retry-After` SOLO si cabe en el cap corto (`_RETRY_AFTER_CAP`) y
    reintenta una vez; si no cabe → degrada (None). Nunca martillea en bucle.
    """
    url = _API + path
    headers = _auth_header()
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=headers, timeout=_TIMEOUT)
        except requests.RequestException as e:
            if attempt == 0:
                continue
            log.debug("covers: fallo de red en %s (%s)", path, e)
            return None
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                return None
        if resp.status_code == 429 and attempt == 0:
            wait = _parse_retry_after(resp.headers.get("Retry-After"))
            if wait is not None and wait <= _RETRY_AFTER_CAP:
                time.sleep(wait)
                continue
            log.info("covers: 429 de Discogs, degradando (Retry-After=%s)",
                     resp.headers.get("Retry-After"))
            return None
        # 404 (sin master/release), 5xx, etc. → degradar
        return None
    return None


def _parse_retry_after(raw):
    if not raw:
        return _RATE_MIN_INTERVAL
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def fetch_cover(discogs_master_id, discogs_release_id):
    """Portada de Discogs para un disco. (url, url_thumb) o None.

    Prefiere el MASTER (`/masters/{id}`, la portada canónica); si no hay master o
    no trae imagen, cae al RELEASE (`/releases/{id}`). Extrae de `images[]` la
    primaria → (`uri`, `uri150`). None si ninguno tiene imagen o hay error/429.
    """
    if discogs_master_id:
        data = _get_json("/masters/{}".format(int(discogs_master_id)))
        picked = _pick_primary_image((data or {}).get("images"))
        if picked:
            return picked
    if discogs_release_id:
        data = _get_json("/releases/{}".format(int(discogs_release_id)))
        picked = _pick_primary_image((data or {}).get("images"))
        if picked:
            return picked
    return None


def store_cover(work_id, url, url_thumb):
    """Guarda (upsert) la portada de Discogs recuperada en core `cover_images`."""
    db.store_cover_image(work_id, "discogs", url, url_thumb)


# --- Set "ya intentado" con TTL (evita re-pedir en cada render) --------------

class _TriedSet:
    """Set de work_ids ya intentados (con o sin éxito) con TTL, thread-safe.

    `add`/`__contains__` purgan expirados de forma perezosa. Cap por tamaño
    (descarta los más antiguos) para no crecer sin límite en un proceso largo.
    """

    def __init__(self, ttl, cap):
        self._ttl = ttl
        self._cap = cap
        self._d = OrderedDict()  # work_id -> expiry_ts
        self._lock = threading.Lock()

    def add(self, work_id):
        now = time.time()
        with self._lock:
            self._d.pop(work_id, None)
            self._d[work_id] = now + self._ttl
            self._purge(now)

    def __contains__(self, work_id):
        now = time.time()
        with self._lock:
            exp = self._d.get(work_id)
            if exp is None:
                return False
            if exp <= now:
                self._d.pop(work_id, None)
                return False
            return True

    def _purge(self, now):
        # Expirados por el frente (OrderedDict conserva orden de inserción; el TTL
        # es constante → los más antiguos caducan antes).
        while self._d:
            k = next(iter(self._d))
            if self._d[k] <= now:
                self._d.pop(k, None)
            else:
                break
        while len(self._d) > self._cap:
            self._d.popitem(last=False)


# --- Worker en segundo plano (cola dedup + rate limit) -----------------------

class _CoverWorker:
    """Cola dedup + hilo daemon que recupera portadas de Discogs sin bloquear la
    request HTTP. `enqueue` es O(1) y no bloquea; el hilo arranca perezosamente en
    el primer enqueue."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._queue = OrderedDict()   # work_id -> True (dedup, orden FIFO)
        self._queued = set()          # espejo para dedup O(1)
        self._tried = _TriedSet(_TRIED_TTL, _TRIED_MAX)
        self._thread = None
        self._last_req = 0.0
        self._dropped = 0

    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            t = threading.Thread(target=self._run, name="cover-backfill",
                                 daemon=True)
            self._thread = t
            t.start()

    def enqueue(self, work_ids):
        """Encola work_ids que necesiten portada. Dedup (mismo id 2x → 1 sola vez),
        salta los ya-intentados (TTL) y respeta el cap de cola. NO bloquea."""
        if not work_ids:
            return
        with self._cv:
            for w in work_ids:
                if w is None:
                    continue
                w = int(w)
                if w in self._queued or w in self._tried:
                    continue
                if len(self._queue) >= _QUEUE_CAP:
                    self._dropped += 1
                    if self._dropped % 200 == 1:
                        log.info("covers: cola llena (%d), descartando "
                                 "(total descartados=%d)", _QUEUE_CAP,
                                 self._dropped)
                    continue
                self._queue[w] = True
                self._queued.add(w)
            self._cv.notify()
        self._ensure_thread()

    def _next(self, timeout=30.0):
        with self._cv:
            if not self._queue:
                self._cv.wait(timeout)
            if not self._queue:
                return None
            w, _ = self._queue.popitem(last=False)
            self._queued.discard(w)
            return w

    def _throttle(self):
        now = time.time()
        delta = now - self._last_req
        if delta < _RATE_MIN_INTERVAL:
            time.sleep(_RATE_MIN_INTERVAL - delta)
        self._last_req = time.time()

    def _process_one(self, work_id):
        # Marcar como intentado ANTES de pedir: con o sin éxito no se re-pide en el
        # TTL (ni se martillea Discogs por los que no tiene).
        self._tried.add(work_id)
        ids = db.work_discogs_ids([work_id]).get(work_id)
        if not ids:
            return  # sin discogs_master_id ni release → placeholder, nada que hacer
        self._throttle()
        picked = fetch_cover(ids.get("master_id"), ids.get("release_id"))
        if not picked:
            return  # Discogs no tiene imagen o 429/error → sigue el placeholder
        url, thumb = picked
        try:
            store_cover(work_id, url, thumb)
            log.debug("covers: guardada portada discogs work=%s", work_id)
        except Exception as e:  # noqa: BLE001 — el worker no debe morir por una fila
            log.warning("covers: fallo al guardar work=%s (%s)", work_id, e)

    def _run(self):
        while True:
            try:
                work_id = self._next()
                if work_id is None:
                    continue
                self._process_one(work_id)
            except Exception as e:  # noqa: BLE001 — nunca dejar morir el daemon
                log.warning("covers: error en worker (%s)", e)
                time.sleep(1.0)

    # -- Introspección (para selftest/diagnóstico; no toca red) --
    def _snapshot(self):
        with self._lock:
            return {"queued": len(self._queue), "dropped": self._dropped}


_WORKER = _CoverWorker()


def enqueue(work_ids):
    """Encola work_ids para backfill de portada (no bloquea). No-op si el flag/
    credenciales están off."""
    if not _enabled():
        return
    _WORKER.enqueue(work_ids)


# --- Enganche de las vistas --------------------------------------------------

def request_missing(works):
    """Desde una vista: filtra los works SIN portada fiable y los encola.

    Acepta los dicts de work que ya manejan las vistas (con `id` + info de cover).
    NO bloquea (encolar es O(1)). No-op si el flag/credenciales están off.

    Para los dicts que NO traen fuente explícita (`has_discogs`/`has_caa`) se usa
    la URL de render como señal (`i.discogs.com` = fiable). No re-consulta la BD:
    el filtro es en memoria; el worker resuelve master/release al procesar.
    """
    if not _enabled() or not works:
        return
    if isinstance(works, dict):
        works = [works]
    ids = []
    for w in works:
        if not isinstance(w, dict):
            continue
        wid = w.get("id")
        if wid is None:
            continue
        if needs_reliable_cover(w):
            ids.append(wid)
    if ids:
        enqueue(ids)
