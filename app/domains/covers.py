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


# --- Cliente/almacenaje de FOTO DE ARTISTA -----------------------------------
#
# Mismo patrón que las portadas y — crítico — el MISMO worker/throttle (ver
# `_BackfillWorker`): portadas y fotos de artista pegan a la MISMA API de Discogs
# con el MISMO token (~55 req/min, compartido con Florent/nightly), así que NO
# puede haber un segundo hilo con su propio rate-limiter. La cola procesa items
# TIPADOS `(kind, id)` con kind ∈ {'cover','artist'}.

# Last.fm quitó las fotos de artista: la estrella placeholder (hash 2a96cbd8…)
# quedó colada en image_url de ~38K artistas. get_artist ya la mapea a NULL, pero
# needs_artist_photo la trata también aquí como "sin foto" (defensivo).
_STAR_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"


def fetch_artist_image(discogs_artist_id):
    """Foto de artista de Discogs. url|None.

    `GET /artists/{id}` (reusa `_get_json`), imagen primaria (reusa
    `_pick_primary_image`). Devuelve la `uri150` (150px, encaja en el avatar de
    140px); si no hay `uri150`, la `uri`. None si Discogs no tiene imagen/429/error.
    """
    if not discogs_artist_id:
        return None
    data = _get_json("/artists/{}".format(int(discogs_artist_id)))
    picked = _pick_primary_image((data or {}).get("images"))
    if not picked:
        return None
    url, thumb = picked  # (uri, uri150|uri|url)
    return thumb or url


def store_artist_image(artist_id, url):
    """Guarda la foto de artista recuperada en core `artists.image_url`."""
    db.store_artist_image(artist_id, url)


def needs_artist_photo(artist_row):
    """True si la ficha de artista mostraría el MONOGRAMA (sin foto real).

    `get_artist` ya devuelve `image_url` NULL para el placeholder-estrella; aquí,
    defensivo, tratamos también una URL con el hash de la estrella como sin-foto.
    """
    if not artist_row:
        return False
    url = artist_row.get("image_url")
    if not url:
        return True
    if _STAR_PLACEHOLDER_HASH in url:
        return True
    return False


# --- Set "ya intentado" con TTL (evita re-pedir en cada render) --------------

class _TriedSet:
    """Set de items ya intentados (con o sin éxito) con TTL, thread-safe.

    Las claves son items TIPADOS `(kind, id)` (kind ∈ {'cover','artist'}) — el
    tipo separa un artist_id que coincida numéricamente con un work_id. `add`/
    `__contains__` purgan expirados de forma perezosa. Cap por tamaño (descarta
    los más antiguos) para no crecer sin límite en un proceso largo.
    """

    def __init__(self, ttl, cap):
        self._ttl = ttl
        self._cap = cap
        self._d = OrderedDict()  # (kind, id) -> expiry_ts
        self._lock = threading.Lock()

    def add(self, key):
        now = time.time()
        with self._lock:
            self._d.pop(key, None)
            self._d[key] = now + self._ttl
            self._purge(now)

    def __contains__(self, key):
        now = time.time()
        with self._lock:
            exp = self._d.get(key)
            if exp is None:
                return False
            if exp <= now:
                self._d.pop(key, None)
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
    """Cola dedup + hilo daemon ÚNICO que recupera de Discogs, sin bloquear la
    request HTTP, items TIPADOS `(kind, id)` con kind ∈ {'cover','artist'}.

    CRÍTICO: portadas y fotos de artista comparten esta MISMA cola, este MISMO
    hilo y — sobre todo — el MISMO throttle (`_last_req`/`_RATE_MIN_INTERVAL`),
    para no exceder el rate limit de Discogs (~55/min, compartido con otros
    sistemas de la máquina). NO hay un segundo rate-limiter.

    `enqueue`/`enqueue_artists` son O(1) y no bloquean; el hilo arranca
    perezosamente en el primer enqueue. El tipo separa un artist_id que coincida
    numéricamente con un work_id."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._queue = OrderedDict()   # (kind, id) -> True (dedup, orden FIFO)
        self._queued = set()          # espejo para dedup O(1)
        self._tried = _TriedSet(_TRIED_TTL, _TRIED_MAX)
        self._thread = None
        self._last_req = 0.0          # ÚNICO throttle, compartido por kinds
        self._dropped = 0

    def _ensure_thread(self):
        if self._thread is None or not self._thread.is_alive():
            t = threading.Thread(target=self._run, name="discogs-backfill",
                                 daemon=True)
            self._thread = t
            t.start()

    def _enqueue_keys(self, kind, ids):
        """Encola items `(kind, id)`. Dedup (mismo item 2x → 1 sola vez), salta
        ya-intentados (TTL) y respeta el cap de cola. NO bloquea."""
        if not ids:
            return
        with self._cv:
            for i in ids:
                if i is None:
                    continue
                key = (kind, int(i))
                if key in self._queued or key in self._tried:
                    continue
                if len(self._queue) >= _QUEUE_CAP:
                    self._dropped += 1
                    if self._dropped % 200 == 1:
                        log.info("covers: cola llena (%d), descartando "
                                 "(total descartados=%d)", _QUEUE_CAP,
                                 self._dropped)
                    continue
                self._queue[key] = True
                self._queued.add(key)
            self._cv.notify()
        self._ensure_thread()

    def enqueue(self, work_ids):
        """Encola work_ids para backfill de PORTADA (kind='cover')."""
        self._enqueue_keys("cover", work_ids)

    def enqueue_artists(self, artist_ids):
        """Encola artist_ids para backfill de FOTO DE ARTISTA (kind='artist')."""
        self._enqueue_keys("artist", artist_ids)

    def _next(self, timeout=30.0):
        with self._cv:
            if not self._queue:
                self._cv.wait(timeout)
            if not self._queue:
                return None
            key, _ = self._queue.popitem(last=False)
            self._queued.discard(key)
            return key

    def _throttle(self):
        now = time.time()
        delta = now - self._last_req
        if delta < _RATE_MIN_INTERVAL:
            time.sleep(_RATE_MIN_INTERVAL - delta)
        self._last_req = time.time()

    def _process_one(self, key):
        # Marcar como intentado ANTES de pedir: con o sin éxito no se re-pide en el
        # TTL (ni se martillea Discogs por los que no tiene). El throttle es ÚNICO
        # (mismo `_last_req`) para ambos kinds → nunca dos rate-limiters.
        kind, item_id = key
        self._tried.add(key)
        if kind == "artist":
            self._process_artist(item_id)
        else:
            self._process_cover(item_id)

    def _process_cover(self, work_id):
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

    def _process_artist(self, artist_id):
        dg_id = db.artist_discogs_ids([artist_id]).get(artist_id)
        if not dg_id:
            return  # sin discogs_artist_id → sigue el monograma, nada que hacer
        self._throttle()
        url = fetch_artist_image(dg_id)
        if not url:
            return  # Discogs no tiene foto o 429/error → sigue el monograma
        try:
            store_artist_image(artist_id, url)
            log.debug("covers: guardada foto de artista discogs artist=%s", artist_id)
        except Exception as e:  # noqa: BLE001 — el worker no debe morir por una fila
            log.warning("covers: fallo al guardar foto artist=%s (%s)", artist_id, e)

    def _run(self):
        while True:
            try:
                key = self._next()
                if key is None:
                    continue
                self._process_one(key)
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


def enqueue_artists(artist_ids):
    """Encola artist_ids para backfill de foto de artista (no bloquea). No-op si el
    flag/credenciales están off. MISMO worker/throttle que las portadas."""
    if not _enabled():
        return
    _WORKER.enqueue_artists(artist_ids)


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


def recover_cover_now(work_id):
    """Recupera la portada de Discogs de UN work de forma SÍNCRONA (bloquea ~0,25s).

    Para el camino de búsqueda: si el mejor match no tiene portada, se recupera en el
    momento para que el disco buscado aparezca en la PRIMERA búsqueda (no solo sus
    afines). Devuelve (url, url_thumb) y la guarda en core, o None si el flag/
    credenciales están off, el work no tiene ids de Discogs, o Discogs no da imagen.
    Degrada silenciosamente (nunca lanza): si falla, el disco sigue oculto como antes.
    """
    if not _enabled():
        return None
    try:
        ids = db.work_discogs_ids([work_id]).get(work_id)
        if not ids:
            return None
        # UNA sola llamada a Discogs para ACOTAR la latencia del camino síncrono
        # (master si lo hay — la portada canónica —, si no el release). El worker
        # asíncrono ya intenta master+release a fondo, así que si esta falla el disco
        # puede converger en la siguiente carga.
        master, release = ids.get("master_id"), ids.get("release_id")
        picked = fetch_cover(master, None) if master else fetch_cover(None, release)
        if not picked:
            return None
        url, thumb = picked
        store_cover(work_id, url, thumb)
        return url, thumb
    except Exception as e:  # noqa: BLE001 — jamás romper la búsqueda por esto
        log.debug("covers: recover_cover_now falló work=%s (%s)", work_id, e)
        return None


def request_missing_ids(work_ids):
    """Encola una lista de work_ids que YA se sabe que NO tienen portada de Discogs.

    Es el enganche de CONVERGENCIA de la regla transversal: los caminos de
    búsqueda/reco calculan sus candidatos SIN el filtro de portada, devuelven en
    `missing_cover_ids` los que aún no la tienen, y el router los pasa aquí para que
    el worker las pida a Discogs. La PRÓXIMA carga ya las trae. No bloquea; no-op si
    el flag/credenciales están off.
    """
    if not _enabled() or not work_ids:
        return
    enqueue([w for w in work_ids if w is not None])


def request_missing_artists(artists):
    """Desde una vista: encola los artistas que mostrarían MONOGRAMA (sin foto).

    Acepta un dict de artista o una lista de ellos (los que maneja la vista, con
    `id` + `image_url`). NO bloquea (encolar es O(1)). No-op si el flag/
    credenciales están off. MISMO worker/throttle que las portadas.
    """
    if not _enabled() or not artists:
        return
    if isinstance(artists, dict):
        artists = [artists]
    ids = []
    for a in artists:
        if not isinstance(a, dict):
            continue
        aid = a.get("id")
        if aid is None:
            continue
        if needs_artist_photo(a):
            ids.append(aid)
    if ids:
        enqueue_artists(ids)
