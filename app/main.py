"""Vinylbe v2 — M3c: capa personal completa (identidad OAuth + wishlist + cuenta).

FastAPI + Jinja server-rendered. Sobre M0/M1/M2 (buscar → ficha → reco anónima)
añade la capa de usuario:
  - IDENTIDAD por OAuth (cookie de sesión `vb_session`): Google (OAuth2/OIDC, cuenta
    persistente cross-device), Discogs (colección → gap) y Last.fm (escucha → reco).
    Cada conexión tiene un propósito distinto; conectar un 2º proveedor estando
    dentro lo VINCULA a tu cuenta (ver oauth.map_identity), no crea otra. Más un
    LOGIN-DEV (`VINYLBE_DEV_LOGIN=1`) para probar la capa personal sin OAuth real.
  - WISHLIST: anónima en el navegador (localStorage), sin cuenta; con sesión, en
    `user_wishlist` (BD) y cross-device. El "invitado" se retiró (la wishlist
    anónima cubre ese hueco).
  - `/mi`: feed personal — "Para ti" (grafo de co-escucha) + "Sube a vinilo" (gap de
    vinilo con precio) + resumen de colección.
  - `/cuenta`: hub de identidad — conexiones (conectar/desconectar con salvaguarda),
    valor de colección, cerrar sesión, borrar cuenta.
  - la reco anónima (`/buscar`, `/obra`, `/artista`, `/vibra`) EXCLUYE la
    colección cuando hay usuario logueado.

Arranque:
    VINYLBE_DB_DSN=postgresql://localhost/vinology_core VINYLBE_DEV_LOGIN=1 \
        uvicorn app.main:app --port 7788 --reload
"""
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.domains import catalog, pricing, reco, editorial, press, users, covers
from app.domains.users import oauth

_HERE = os.path.dirname(__file__)
_TEMPLATES_DIR = os.path.join(_HERE, "web", "templates")
_STATIC_DIR = os.path.join(_HERE, "web", "static")

app = FastAPI(title="Vinylbe v2", version="0.0.3-m3a")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

# Vida de la cookie de sesión (segundos), espejo de db.SESSION_TTL_DAYS.
from app import db  # noqa: E402
_COOKIE_MAX_AGE = db.SESSION_TTL_DAYS * 24 * 3600


def _owned_formats_map(user):
    """work_id -> formatos que el usuario POSEE ('vinyl'/'cd'), para el flag "ya lo
    tienes" en cualquier tarjeta/ficha. Solo con Discogs conectado (la colección
    viene de ahí); sin conexión → {} y no tocamos la BD."""
    if not user or "discogs" not in (user.get("providers") or []):
        return {}
    return catalog.owned_formats_for_user(user["id"])


def _render(request, name, status_code=200, **ctx):
    ctx["request"] = request
    # `user` disponible en TODAS las plantillas (cabecera): la resuelve el router
    # y lo pasa; si no, lo inferimos de la cookie para no romper vistas simples.
    if "user" not in ctx:
        ctx["user"] = users.current_user(request)
    ctx["display_label"] = users.display_label(ctx.get("user"))
    # `owned` disponible en TODAS las plantillas: mapa work_id -> formatos poseídos,
    # para pintar el flag "ya lo tienes" donde salga un work. {} para anónimos / sin
    # Discogs. El router puede pasarlo ya calculado para no repetir la query.
    if "owned" not in ctx:
        ctx["owned"] = _owned_formats_map(ctx.get("user"))
    return templates.TemplateResponse(name, ctx, status_code=status_code)


def _set_session_cookie(response, token):
    response.set_cookie(
        users.SESSION_COOKIE, token,
        max_age=_COOKIE_MAX_AGE, httponly=True, samesite="lax",
    )


# TTL corto para la cookie de estado del flow OAuth (segundos). El secreto real
# (request-token-secret de Discogs) vive en el proceso; aquí solo viaja el `state`
# opaco single-use que lo indexa (ver oauth.FlowStore).
_OAUTH_STATE_MAX_AGE = 600


def _set_oauth_state_cookie(response, state):
    response.set_cookie(
        oauth.OAUTH_STATE_COOKIE, state,
        max_age=_OAUTH_STATE_MAX_AGE, httponly=True, samesite="lax",
    )


def _clear_oauth_state_cookie(response):
    response.delete_cookie(oauth.OAUTH_STATE_COOKIE)


def _login_after_oauth(user_id, return_to="/mi"):
    """Abre sesión para user_id, redirige a `return_to` (por defecto /mi; /cuenta
    cuando se estaba VINCULANDO un proveedor a una cuenta ya dentro) con set-cookie
    de sesión y limpia la cookie de estado del flow."""
    token = users.open_session(user_id)
    resp = RedirectResponse(url=return_to or "/mi", status_code=303)
    _set_session_cookie(resp, token)
    _clear_oauth_state_cookie(resp)
    return resp


def _oauth_error(request, provider, detail, status_code=400):
    """Error suave de OAuth (no 500): renderiza una página de aviso amable."""
    user = users.current_user(request)
    return _render(
        request, "oauth_error.html", status_code=status_code,
        provider=provider, detail=detail, user=user,
    )


# ---------------------------------------------------------------------------
# Páginas (anónimas; excluyen colección cuando hay user)
# ---------------------------------------------------------------------------

# Tira de discos reales de la home: obras CONOCIDAS de vibra indie/alt con portada
# Y precio ES real. Estilos curados (editorial) sesgados a ese rollo. El match
# obra→precio no es gratis (trigram sobre marketplace_listings), y la tira es la
# misma para todos → se cachea en proceso unos minutos. De la cabeza por popularidad
# se toma una MUESTRA aleatoria (todas conocidas, pero rota entre recargas). Se
# conserva la última tanda buena si una recarga falla, para no dejar la home sin tira.
_STRIP_STYLES = [
    "Alternative Rock", "Indie Rock", "Indie Pop", "Post-Punk", "New Wave",
    "Shoegaze", "Dream Pop", "Post Rock", "Grunge", "Garage Rock",
    "Art Rock", "Britpop", "Emo", "Math Rock", "Post-Hardcore",
]
_FEATURED = {"at": 0.0, "works": []}
_FEATURED_TTL = 600  # 10 min


def _featured_priced_works(limit=14):
    now = time.time()
    if _FEATURED["works"] and (now - _FEATURED["at"] < _FEATURED_TTL):
        return _FEATURED["works"]
    try:
        cands = db.top_covers_by_playcount(_STRIP_STYLES, limit=150)
        pricing.attach_cheapest(cands)
        priced = [w for w in cands if w.get("cheapest_price")]
        # De las ~más conocidas con precio, muestrea `limit` para que rote entre
        # recargas (todas siguen siendo discos reconocibles).
        pool = priced[: max(limit * 4, limit)]
        priced = random.sample(pool, min(limit, len(pool)))
    except Exception:
        priced = []
    if priced:
        _FEATURED["at"] = now
        _FEATURED["works"] = priced
    return priced or _FEATURED["works"]


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = users.current_user(request)
    # Tira de discos reales con precio ES (cacheada; best-effort).
    try:
        featured = _featured_priced_works()
    except Exception:
        featured = []
    return _render(request, "home.html", user=user, featured=featured)


def _parse_id_csv(raw):
    """"1,2,3" (o repetido) → [1,2,3] (ints, dedup, orden estable). Robusto a
    basura (ignora lo no numérico)."""
    out, seen = [], set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        v = int(part)
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _spotify_search_link(query):
    """Link "escuchar en Spotify" a partir de una `query` de búsqueda ya formada.

    SIN OAuth ni API key (patrón de degradación honesta del diseño; core NO tiene los
    IDs de Spotify — columnas vacías). Para clavar el disco exacto, el caller usa los
    filtros de Spotify (`album:"…" artist:"…"`) en `query`. Devuelve {"web", "app"}:
    `app` es la URI `spotify:` que abre la APP si está instalada; `web` es el fallback
    (lo maneja el JS: intenta la app y cae a la web). None si `query` vacía."""
    import urllib.parse
    q = (query or "").strip()
    if not q:
        return None
    quoted = urllib.parse.quote(q)
    return {"web": "https://open.spotify.com/search/" + quoted,
            "app": "spotify:search:" + quoted}


def _discogs_market_url(work):
    """Link al MARKETPLACE de Discogs de la obra (mismo patrón que v1): listado de
    venta filtrado por el master de Discogs, en EUR y formato Vinyl. Core tiene
    `discogs_master_id` al 100% en works con vinilo. None si falta."""
    master = work.get("discogs_master_id")
    if not master:
        return None
    return ("https://www.discogs.com/sell/list?master_id={}"
            "&currency=EUR&format=Vinyl").format(master)


def _spotify_work_query(work):
    """Query de Spotify que clava un ÁLBUM: `album:"título" artist:"artista"`."""
    title = (work.get("title") or "").strip()
    if not title:
        return None
    artist = (work.get("artist_name") or "").strip()
    q = 'album:"{}"'.format(title)
    if artist:
        q += ' artist:"{}"'.format(artist)
    return q


@app.get("/buscar", response_class=HTMLResponse)
def buscar(request: Request, q: str = "", artists: str = "", works: str = ""):
    """Buscador §6: con SELECCIÓN (`artists=1,2&works=3,4`) → bloques "mejores de
    {artista}" + "en la onda de tu selección"; con solo TEXTO (`q`) → búsqueda
    normal §1 (artistas + works en bloques). Sin nada → invitación a buscar."""
    user = users.current_user(request)
    uid = user["id"] if user else None
    q = (q or "").strip()
    sel_artist_ids = _parse_id_csv(artists)
    sel_work_ids = _parse_id_csv(works)

    # --- Modo SELECCIÓN (chips): tiene prioridad sobre el texto libre ---
    if sel_artist_ids or sel_work_ids:
        sel = reco.search_by_selection(
            sel_artist_ids, sel_work_ids, exclude_user_id=uid)
        # Los DISCOS que el usuario eligió: se MUESTRAN (antes solo se usaban de
        # semilla para los afines y no aparecían → "elijo Hot Fuss y no sale").
        selected_works = [w for w in (catalog.get_work(wid) for wid in sel_work_ids)
                          if w]
        # Backfill de portadas + precio ES más barato de cada disco (en lote).
        covers.request_missing(selected_works)
        pricing.attach_cheapest(selected_works)
        for blk in sel["artist_blocks"]:
            covers.request_missing(blk["works"])
            pricing.attach_cheapest(blk["works"])
        covers.request_missing(sel["combined"]["results"])
        pricing.attach_cheapest(sel["combined"]["results"])
        return _render(
            request, "search.html",
            q="", mode="selection",
            selected_works=selected_works,
            artist_blocks=sel["artist_blocks"],
            combined=sel["combined"],
            user=user,
        )

    # --- Modo TEXTO (§1) ---
    if not q:
        return _render(request, "search.html", q="", mode="text",
                       works=[], artists=[], affines=None, user=user)

    # LATENCIA: los AFINES (KNN por embedding, ~0,8s) NO se calculan aquí; se cargan
    # aparte vía /buscar/afines (fetch en search.html), igual que en la ficha. La
    # página muestra works + artistas al instante (~0,2s).
    works_res = catalog.search_works_only(q)
    # Si el MEJOR match está OCULTO por falta de portada, recupérala de Discogs en el
    # acto (~0,25s) y muéstralo el PRIMERO: así el disco que buscas aparece ya en la
    # primera búsqueda (antes solo salían sus afines hasta que el worker la traía).
    top = works_res.get("top_coverless")
    if top:
        got = covers.recover_cover_now(top["id"])
        if got:
            top["cover_url"], top["cover_thumb"] = got
            top["has_discogs"] = True
            works_res["works"].insert(0, top)
    artists = catalog.search_artists_only(q)
    covers.request_missing(works_res["works"])
    covers.request_missing_ids(works_res.get("missing_cover_ids"))
    pricing.attach_cheapest(works_res["works"])
    # Semilla de los afines (fragmento async): la 1ª obra; si no hay obras, el 1er
    # artista. affine_for_search prefiere obra > artista → misma semántica.
    afines_src = None
    if works_res["works"]:
        afines_src = "/buscar/afines?work={}".format(works_res["works"][0]["id"])
    elif artists:
        afines_src = "/buscar/afines?artist={}".format(artists[0]["id"])
    return _render(
        request, "search.html",
        q=q, mode="text",
        works=works_res["works"],
        artists=artists,
        afines_src=afines_src,
        user=user,
    )


@app.get("/buscar/afines", response_class=HTMLResponse)
def buscar_afines(request: Request, work: int = 0, artist: int = 0):
    """Fragmento HTML con el bloque "Vinilos afines" de /buscar (KNN por embedding,
    ~0,8s). Se pide por fetch para no bloquear el render de la búsqueda. La semilla
    es un work (preferido) o un artista, resuelta en el router de /buscar."""
    user = users.current_user(request)
    uid = user["id"] if user else None
    affines = None
    if work:
        seed = catalog.get_work(work)
        if seed:
            affines = reco.affine_for_search([seed], [], exclude_user_id=uid)
    elif artist:
        seed = catalog.get_artist(artist)
        if seed:
            affines = reco.affine_for_search([], [seed], exclude_user_id=uid)
    if affines and affines.get("results"):
        covers.request_missing(affines["results"])
        pricing.attach_cheapest(affines["results"])
    return _render(request, "_search_afines.html", affines=affines, user=user)


@app.get("/api/suggest")
def api_suggest(q: str = ""):
    """Type-ahead JSON: {artists:[{id,name}], works:[{id,title,artist_name,year}]}.
    Mismo ranking/filtros que §1/§2 (portada-obligatoria en works). Min 3 chars →
    listas vacías (lo controla la capa de BD)."""
    return JSONResponse(catalog.suggest((q or "").strip()))


@app.get("/obra/{work_id}", response_class=HTMLResponse)
def obra(request: Request, work_id: int):
    user = users.current_user(request)
    uid = user["id"] if user else None
    work = catalog.get_work(work_id)
    if not work:
        return _render(request, "404.html", what="obra", ident=work_id,
                       status_code=404, user=user)
    # Regla de portada OBLIGATORIA en TODAS partes (incluida la ficha): un disco sin
    # portada de Discogs no se muestra. Se pide a Discogs (para la próxima); si no se
    # puede recuperar, se queda en 404.
    if not (work.get("cover_thumb") or work.get("cover_url")):
        covers.request_missing(work)
        return _render(request, "404.html", what="obra", ident=work_id,
                       status_code=404, user=user)
    tracklist = catalog.get_work_tracklist(work_id)
    prices = pricing.get_prices_for_work(work_id)
    press_signals = press.get_signals(work_id)
    artist = catalog.get_artist(work["artist_id"])
    artist_bio = catalog.artist_bio_excerpt(artist)
    # LATENCIA: los afines (KNN por embedding, ~2,3s) NO se calculan aquí; la ficha
    # se sirve al instante y el bloque "Vinilos afines" se carga aparte vía
    # /obra/{id}/afines (fetch en work.html). Todo lo de arriba es ~0,05s.
    covers.request_missing(work)
    return _render(
        request, "work.html",
        work=work,
        tracklist=tracklist,
        prices=prices,
        press=press_signals,
        artist_bio=artist_bio,
        spotify_url=_spotify_search_link(_spotify_work_query(work)),
        discogs_url=_discogs_market_url(work),
        user=user,
    )


@app.get("/obra/{work_id}/afines", response_class=HTMLResponse)
def obra_afines(request: Request, work_id: int):
    """Fragmento HTML con los bloques de afines de la ficha (KNN por embedding,
    ~2,3s). Se pide por fetch desde work.html para no bloquear el render de la
    ficha. Devuelve HTML parcial (sin base.html)."""
    user = users.current_user(request)
    uid = user["id"] if user else None
    similar = reco.similar_to_work(work_id, exclude_user_id=uid)
    similar_press = reco.similar_by_press_to_work(work_id)
    covers.request_missing(similar)
    covers.request_missing(similar_press)
    pricing.attach_cheapest(similar)
    pricing.attach_cheapest(similar_press)
    return _render(
        request, "_work_afines.html",
        similar=similar, similar_press=similar_press, user=user,
    )


@app.get("/artista/{artist_id}", response_class=HTMLResponse)
def artista(request: Request, artist_id: int):
    user = users.current_user(request)
    uid = user["id"] if user else None
    artist = catalog.get_artist(artist_id)
    if not artist:
        return _render(request, "404.html", what="artista", ident=artist_id,
                       status_code=404, user=user)
    disc = catalog.get_artist_discography(artist_id)
    discography = disc["works"]
    # LATENCIA: los afines (KNN por centroide, ~0,9s) se cargan aparte vía
    # /artista/{id}/afines. La ficha (foto + discografía) se sirve al instante.
    covers.request_missing(discography)
    covers.request_missing_ids(disc.get("missing_cover_ids"))
    pricing.attach_cheapest(discography)
    # FOTO DE ARTISTA: si la ficha mostraría el monograma (image_url NULL), recupera
    # la foto de Discogs EN EL ACTO (~0,3s, una llamada) para que salga en la PRIMERA
    # carga — antes solo aparecía tras un refresco (la traía el worker async). Si la
    # recuperación síncrona falla (429/sin foto), cae al worker async para converger
    # en la siguiente carga (mismo patrón que recover_cover_now en /buscar).
    if covers.needs_artist_photo(artist):
        got = covers.recover_artist_image_now(artist_id)
        if got:
            artist["image_url"] = got
        else:
            covers.request_missing_artists(artist)
    return _render(
        request, "artist.html",
        artist=artist,
        discography=discography,
        spotify_url=_spotify_search_link(
            'artist:"{}"'.format(artist["name"]) if artist.get("name") else None),
        user=user,
    )


@app.get("/artista/{artist_id}/afines", response_class=HTMLResponse)
def artista_afines(request: Request, artist_id: int):
    """Fragmento HTML con los afines de un artista (KNN por centroide de embeddings,
    ~0,9s). Se pide por fetch desde artist.html para no bloquear el render."""
    user = users.current_user(request)
    uid = user["id"] if user else None
    similar = reco.similar_to_artist(artist_id, exclude_user_id=uid)
    covers.request_missing(similar)
    pricing.attach_cheapest(similar)
    return _render(request, "_artist_afines.html", similar=similar, user=user)


@app.get("/vibra", response_class=HTMLResponse)
def vibra(request: Request, mood: str = "", q: str = ""):
    user = users.current_user(request)
    uid = user["id"] if user else None
    entry = (q or mood or "").strip()
    chips = editorial.list_mood_chips()
    result = (editorial.recommend_by_mood(entry, exclude_user_id=uid)
              if entry else None)
    if result:
        covers.request_missing(result.get("results"))
        pricing.attach_cheapest(result.get("results"))
    return _render(
        request, "vibra.html",
        entry=entry,
        chips=chips,
        result=result,
        user=user,
    )


# ---------------------------------------------------------------------------
# Página personal /mi (requiere sesión)
# ---------------------------------------------------------------------------

@app.get("/mi", response_class=HTMLResponse)
def mi(request: Request):
    user = users.current_user(request)
    if not user:
        # Anónimo: NO 500 — invita a entrar/crear invitado.
        return _render(request, "mi.html", user=None, anon=True)
    summary = users.collection_summary(user)
    uid = user["id"]
    # Las tres recomendaciones de /mi son independientes y cada una ronda ~1s
    # (KNN de dos fases + join de precios en el gap). En serie sumaban ~2,6s, muy
    # cerca del presupuesto de 3s; se lanzan en PARALELO (el pool es
    # ThreadedConnectionPool, cada hilo saca su conexión) — mismo patrón que
    # catalog.search. gap_total es una query trivial, va con ellas.
    with ThreadPoolExecutor(max_workers=4) as ex:
        f_for_you = ex.submit(users.recommend_for_user, uid, 50)
        f_listening = ex.submit(users.recommend_from_listening, uid, 50)
        f_gap = ex.submit(users.vinyl_gap, uid, 24)
        f_gap_total = ex.submit(users.vinyl_gap_count, uid)
        for_you = f_for_you.result()
        listening = f_listening.result()
        gap = f_gap.result()
        gap_total = f_gap_total.result()
    # Backfill de portadas sin bloquear: las 3 secciones de /mi.
    covers.request_missing(for_you)
    covers.request_missing(listening)
    covers.request_missing(gap)
    # Precio ES más barato en las recos (el gap ya trae su propio precio).
    pricing.attach_cheapest(for_you)
    pricing.attach_cheapest(listening)
    return _render(
        request, "mi.html",
        user=user,
        anon=False,
        summary=summary,
        for_you=for_you,
        listening=listening,
        gap=gap,
        gap_total=gap_total,
    )


# ---------------------------------------------------------------------------
# Wishlist (M3c · Fase 1) — anónimo en localStorage; con sesión, en BD
# ---------------------------------------------------------------------------
# El usuario ANÓNIMO guarda en el navegador (localStorage) sin cuenta: el JS es la
# fuente de verdad y pide /wishlist/cards para pintar portada+precio (server). El
# usuario con SESIÓN guarda en `user_wishlist` (POST/DELETE) y se sirve server-side.
# Al iniciar sesión, el JS sube lo que hubiera en el navegador vía /wishlist/import.


def _hydrate_works(ids):
    """[work_id,...] → [work,...] en el MISMO orden, con portada+precio. Descarta
    ids que ya no existen en el catálogo. Mismo patrón que el modo selección."""
    works = [w for w in (catalog.get_work(i) for i in ids) if w]
    covers.request_missing(works)
    pricing.attach_cheapest(works)
    return works


@app.get("/wishlist", response_class=HTMLResponse)
def wishlist(request: Request):
    """Página de la wishlist. Con sesión: se sirve desde BD. Anónima: shell que el
    JS hidrata desde localStorage vía /wishlist/cards."""
    user = users.current_user(request)
    if user:
        works = _hydrate_works(users.wishlist_ids(user))
        return _render(request, "wishlist.html", user=user, mode="user", works=works)
    return _render(request, "wishlist.html", user=None, mode="anon", works=[])


@app.get("/wishlist/cards", response_class=HTMLResponse)
def wishlist_cards(request: Request, works: str = ""):
    """Fragmento HTML: ids (CSV) → grid de tarjetas hidratadas. Lo pide el JS de la
    wishlist ANÓNIMA con los ids del localStorage (clon de /buscar/afines)."""
    user = users.current_user(request)
    hydrated = _hydrate_works(_parse_id_csv(works))
    return _render(request, "_wishlist_cards.html", user=user, works=hydrated)


@app.get("/wishlist/ids")
def wishlist_ids_json(request: Request):
    """IDs guardados por el usuario con sesión (JSON). Anónimo → [] (el JS usa
    localStorage). Lo pide wishlist.js para marcar los ♥ de la página."""
    user = users.current_user(request)
    return JSONResponse({"ids": users.wishlist_ids(user)})


@app.post("/wishlist/import")
def wishlist_import(request: Request, works: str = ""):
    """Fusiona los ids del navegador (localStorage) en la BD tras iniciar sesión.
    Devuelve cuántos se guardaron. Anónimo → 401.

    NOTA: se declara ANTES de /wishlist/{work_id} — si no, la ruta con parámetro
    int captura 'import' y devuelve 422 (FastAPI casa por orden de declaración)."""
    user = users.current_user(request)
    if not user:
        return JSONResponse({"ok": False, "anon": True}, status_code=401)
    added = users.wishlist_import(user, _parse_id_csv(works))
    return JSONResponse({"ok": True, "added": added})


@app.post("/wishlist/{work_id}")
def wishlist_add(request: Request, work_id: int):
    """Guarda un disco (usuario con sesión). Anónimo → 401 (el JS usa localStorage)."""
    user = users.current_user(request)
    if not user:
        return JSONResponse({"ok": False, "anon": True}, status_code=401)
    users.wishlist_add(user, work_id)
    return JSONResponse({"ok": True, "wished": True})


@app.delete("/wishlist/{work_id}")
def wishlist_del(request: Request, work_id: int):
    """Quita un disco (usuario con sesión). Anónimo → 401."""
    user = users.current_user(request)
    if not user:
        return JSONResponse({"ok": False, "anon": True}, status_code=401)
    users.wishlist_remove(user, work_id)
    return JSONResponse({"ok": True, "wished": False})


# ---------------------------------------------------------------------------
# Sesión (server-side): logout + OAuth. El "invitado" se retiró (M3c · Fase 3):
# la wishlist anónima vive en el navegador (localStorage), así que una cuenta sin
# identidad ya no tiene sentido. Identidad = Google / Discogs / Last.fm.
# ---------------------------------------------------------------------------

@app.post("/auth/logout")
def auth_logout(request: Request):
    """Cierra la sesión (server-side) y borra la cookie. Redirige a home."""
    token = request.cookies.get(users.SESSION_COOKIE)
    if token:
        users.close_session(token)
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(users.SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# OAuth real — Discogs (OAuth 1.0a) + Last.fm (api_sig) (M3b)
# ---------------------------------------------------------------------------
# Solo establece IDENTIDAD + sesión (linking invitado→identidad incluido). NO
# sincroniza colección/escucha (eso lo hace el pipeline de core; v2 solo lee).

@app.get("/auth/discogs/login")
def discogs_login(request: Request):
    """Inicia OAuth1 de Discogs: pide request token (callback dinámico), guarda el
    request-token-secret server-side y redirige a authorize. Sin credenciales en
    entorno → aviso 'login no configurado' (no 500)."""
    if not oauth.discogs_configured():
        return _oauth_error(
            request, "Discogs",
            "El login con Discogs no está configurado en este entorno.")
    # Destino de VINCULACIÓN = el usuario logueado AHORA (sea invitado o una cuenta
    # ya identificada). Así, conectar un proveedor estando dentro lo AÑADE a tu
    # cuenta en vez de crear una nueva y expulsarte a ella. Anónimo → None (login
    # fresco: se reutiliza la identidad si ya existe, o se crea).
    current = users.current_user(request)
    guest_id = current["id"] if current else None
    try:
        token, secret = oauth.discogs_request_token()
    except Exception as e:  # noqa: BLE001 — degradación honesta ante rechazo
        return _oauth_error(
            request, "Discogs",
            "Discogs no devolvió un request token ({}).".format(e))
    state = oauth.FLOW_STORE.put({
        "provider": "discogs",
        "oauth_token": token,
        "request_token_secret": secret,
        "guest_user_id": guest_id,
        "return_to": "/cuenta" if current else "/mi",
    })
    resp = RedirectResponse(url=oauth.discogs_authorize_url(token),
                            status_code=302)
    _set_oauth_state_cookie(resp, state)
    return resp


@app.get("/auth/discogs/callback")
def discogs_callback(request: Request, oauth_token: str = "",
                     oauth_verifier: str = ""):
    """Callback de Discogs: recupera el estado del flow por la cookie, intercambia
    por access token, resuelve identidad y aplica la regla de mapeo. Callback sin
    estado (llegada directa) → error suave (no 500)."""
    state = request.cookies.get(oauth.OAUTH_STATE_COOKIE)
    flow = oauth.FLOW_STORE.pop(state)
    if not flow or flow.get("provider") != "discogs":
        return _oauth_error(
            request, "Discogs",
            "No encontramos el estado de tu inicio de sesión (expiró o llegaste "
            "directo). Vuelve a empezar desde el botón de conexión.")
    if not oauth_verifier or not oauth_token:
        return _oauth_error(
            request, "Discogs",
            "Discogs no devolvió el verificador. Cancela y vuelve a intentarlo.")
    # El oauth_token del callback debe coincidir con el del request token.
    if oauth_token != flow.get("oauth_token"):
        return _oauth_error(
            request, "Discogs",
            "El token de Discogs no coincide con el de tu sesión. Reintenta.")
    try:
        access_token, access_secret = oauth.discogs_access_token(
            oauth_token, flow["request_token_secret"], oauth_verifier)
        account_id, username = oauth.discogs_identity(access_token, access_secret)
    except Exception as e:  # noqa: BLE001
        return _oauth_error(
            request, "Discogs",
            "No pudimos completar el intercambio con Discogs ({}).".format(e))
    user_id, _outcome = oauth.persist_identity(
        provider="discogs", provider_account_id=account_id,
        provider_username=username, guest_user_id=flow.get("guest_user_id"),
        oauth_token=access_token, oauth_token_secret=access_secret,
    )
    return _login_after_oauth(user_id, flow.get("return_to"))


@app.get("/auth/lastfm/login")
def lastfm_login(request: Request):
    """Inicia el auth flow de Last.fm: guarda el invitado (si lo hay) en estado
    server-side y redirige a last.fm/api/auth con api_key + cb. Sin credenciales
    → aviso 'no configurado' (no 500)."""
    if not oauth.lastfm_configured():
        return _oauth_error(
            request, "Last.fm",
            "El login con Last.fm no está configurado en este entorno.")
    # Destino de VINCULACIÓN = el usuario logueado AHORA (sea invitado o una cuenta
    # ya identificada). Así, conectar un proveedor estando dentro lo AÑADE a tu
    # cuenta en vez de crear una nueva y expulsarte a ella. Anónimo → None (login
    # fresco: se reutiliza la identidad si ya existe, o se crea).
    current = users.current_user(request)
    guest_id = current["id"] if current else None
    state = oauth.FLOW_STORE.put({
        "provider": "lastfm",
        "guest_user_id": guest_id,
        "return_to": "/cuenta" if current else "/mi",
    })
    resp = RedirectResponse(url=oauth.lastfm_auth_url(), status_code=302)
    _set_oauth_state_cookie(resp, state)
    return resp


@app.get("/auth/lastfm/callback")
def lastfm_callback(request: Request, token: str = ""):
    """Callback de Last.fm: recupera el estado del flow, cambia el token por una
    sesión (auth.getSession firmado) y aplica la regla de mapeo. Callback sin
    estado o sin token → error suave (no 500)."""
    state = request.cookies.get(oauth.OAUTH_STATE_COOKIE)
    flow = oauth.FLOW_STORE.pop(state)
    if not flow or flow.get("provider") != "lastfm":
        return _oauth_error(
            request, "Last.fm",
            "No encontramos el estado de tu inicio de sesión (expiró o llegaste "
            "directo). Vuelve a empezar desde el botón de conexión.")
    if not token:
        return _oauth_error(
            request, "Last.fm",
            "Last.fm no devolvió el token de autorización. Reintenta.")
    try:
        session_key, username = oauth.lastfm_session(token)
    except Exception as e:  # noqa: BLE001
        return _oauth_error(
            request, "Last.fm",
            "No pudimos obtener tu sesión de Last.fm ({}).".format(e))
    user_id, _outcome = oauth.persist_identity(
        provider="lastfm", provider_account_id=username,
        provider_username=username, guest_user_id=flow.get("guest_user_id"),
        session_key=session_key,
    )
    return _login_after_oauth(user_id, flow.get("return_to"))


# ---------------------------------------------------------------------------
# OAuth real — Google (OAuth2 / OpenID Connect) (M3c · Fase 2)
# ---------------------------------------------------------------------------
# Google es IDENTIDAD pura: da cuenta persistente (wishlist cross-device) sin pedir
# datos de música. Mismo molde que Discogs/Last.fm (FlowStore + cookie de estado),
# con un check CSRF extra: el `state` que devuelve Google debe coincidir con el de
# la cookie.

@app.get("/auth/google/login")
def google_login(request: Request):
    """Inicia el code flow de Google. Sin credenciales → aviso 'no configurado'."""
    if not oauth.google_configured():
        return _oauth_error(
            request, "Google",
            "El login con Google no está configurado en este entorno.")
    # Destino de VINCULACIÓN = el usuario logueado AHORA (sea invitado o una cuenta
    # ya identificada). Así, conectar un proveedor estando dentro lo AÑADE a tu
    # cuenta en vez de crear una nueva y expulsarte a ella. Anónimo → None (login
    # fresco: se reutiliza la identidad si ya existe, o se crea).
    current = users.current_user(request)
    guest_id = current["id"] if current else None
    state = oauth.FLOW_STORE.put({
        "provider": "google", "guest_user_id": guest_id,
        "return_to": "/cuenta" if current else "/mi",
    })
    resp = RedirectResponse(url=oauth.google_authorize_url(state), status_code=302)
    _set_oauth_state_cookie(resp, state)
    return resp


@app.get("/auth/google/callback")
def google_callback(request: Request, code: str = "", state: str = "",
                    error: str = ""):
    """Callback de Google: valida estado (cookie + `state` devuelto), intercambia el
    code por tokens, resuelve identidad (sub/email/name) y aplica la regla de mapeo.
    Llegada directa / state que no casa / error de Google → aviso suave (no 500)."""
    cookie_state = request.cookies.get(oauth.OAUTH_STATE_COOKIE)
    flow = oauth.FLOW_STORE.pop(cookie_state)
    if not flow or flow.get("provider") != "google":
        return _oauth_error(
            request, "Google",
            "No encontramos el estado de tu inicio de sesión (expiró o llegaste "
            "directo). Vuelve a empezar desde el botón de conexión.")
    if not state or state != cookie_state:
        return _oauth_error(
            request, "Google",
            "El identificador de tu sesión no coincide (posible reenvío). Reintenta.")
    if error or not code:
        return _oauth_error(
            request, "Google",
            "Google no devolvió el código de autorización ({}). Reintenta.".format(
                error or "sin code"))
    try:
        tokens = oauth.google_exchange(code)
        sub, email, name = oauth.google_identity(tokens["access_token"])
    except Exception as e:  # noqa: BLE001
        return _oauth_error(
            request, "Google",
            "No pudimos completar el intercambio con Google ({}).".format(e))
    # Google es SOLO identidad: el access token se usa aquí para leer sub/email y
    # NO se persiste (nadie lo consume después; ver migración 003). Minimización de
    # datos: menos secreto guardado, menos riesgo at-rest.
    user_id, _outcome = oauth.persist_identity(
        provider="google", provider_account_id=sub,
        provider_username=name or email, guest_user_id=flow.get("guest_user_id"),
    )
    return _login_after_oauth(user_id, flow.get("return_to"))


# ---------------------------------------------------------------------------
# Cuenta (M3c · Fase 2) — hub de identidad: conexiones, valor, salir, borrar
# ---------------------------------------------------------------------------

@app.get("/cuenta", response_class=HTMLResponse)
def cuenta(request: Request):
    """Página de cuenta. Anónimo → invitación a entrar. Con sesión → estado de las
    conexiones (Google/Discogs/Last.fm) + valor de colección + acciones."""
    user = users.current_user(request)
    if not user:
        return _render(request, "cuenta.html", user=None, anon=True,
                       connections=users.connection_status([]))
    summary = users.collection_summary(user)
    connections = users.connection_status(user.get("providers") or [])
    return _render(request, "cuenta.html", user=user, anon=False,
                   summary=summary, connections=connections)


@app.post("/auth/{provider}/disconnect")
def auth_disconnect(request: Request, provider: str):
    """Desvincula un proveedor. Se niega si es la ÚNICA identidad (dejaría la cuenta
    sin forma de entrar → para eso está 'Borrar cuenta'). Redirige a /cuenta."""
    user = users.current_user(request)
    if user and provider in ("google", "discogs", "lastfm"):
        users.disconnect_provider(user, provider)
    return RedirectResponse(url="/cuenta", status_code=303)


@app.get("/privacidad", response_class=HTMLResponse)
def privacidad(request: Request):
    """Política de privacidad (estática). Fecha fija = última revisión del texto."""
    return _render(request, "privacidad.html", updated="12 de julio de 2026")


@app.get("/account/export")
def account_export(request: Request):
    """Exporta los datos personales del usuario (GDPR, derecho de acceso/portabilidad)
    como JSON descargable. Sin sesión → a /cuenta. No incluye tokens OAuth."""
    user = users.current_user(request)
    if not user:
        return RedirectResponse(url="/cuenta", status_code=303)
    data = users.export_user_data(user)
    return JSONResponse(
        content=jsonable_encoder(data),
        headers={"Content-Disposition": 'attachment; filename="vinilogy-mis-datos.json"'},
    )


@app.post("/account/delete")
def account_delete(request: Request):
    """Borra la cuenta y todo lo suyo (CASCADE: sesiones, credenciales, wishlist).
    Limpia la cookie y vuelve a la home."""
    user = users.current_user(request)
    if user:
        users.delete_account(user)
    resp = RedirectResponse(url="/", status_code=303)
    resp.delete_cookie(users.SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# LOGIN-DEV guardado (SOLO si VINYLBE_DEV_LOGIN=1; en prod NO se monta)
# ---------------------------------------------------------------------------
# Es el gancho de prueba de la capa personal SIN OAuth real (M3b). Permite
# identificarte como un usuario EXISTENTE (p.ej. user 1 = Carlos) para verificar
# reco personal / gap de vinilo. NUNCA debe existir en producción.

if users.DEV_LOGIN_ENABLED:

    @app.post("/dev/login/{user_id}")
    def dev_login(request: Request, user_id: int):
        u = users.get_user(user_id)
        if not u:
            return _render(request, "404.html", what="usuario", ident=user_id,
                           status_code=404, user=None)
        token = users.open_session(user_id)
        resp = RedirectResponse(url="/mi", status_code=303)
        _set_session_cookie(resp, token)
        return resp
