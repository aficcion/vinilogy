"""Vinylbe v2 — M3a: capa personal (sesión + invitado + reco personal + /mi).

FastAPI + Jinja server-rendered. Sobre M0/M1/M2 (buscar → ficha → reco anónima)
añade:
  - auth ligera server-side (cookie `vb_session`): invitado, logout, y un
    LOGIN-DEV guardado (`VINYLBE_DEV_LOGIN=1`) para probar la capa personal sin
    OAuth real (eso es M3b).
  - `/mi`: perfil del usuario — "Para ti" (grafo de co-escucha) + "Sube a vinilo"
    (gap de vinilo con precio) + resumen de colección.
  - la reco anónima (`/buscar`, `/obra`, `/artista`, `/vibra`) EXCLUYE la
    colección cuando hay usuario logueado.

Arranque:
    VINYLBE_DB_DSN=postgresql://localhost/vinology_core VINYLBE_DEV_LOGIN=1 \
        uvicorn app.main:app --port 7788 --reload
"""
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request
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


def _render(request, name, status_code=200, **ctx):
    ctx["request"] = request
    # `user` disponible en TODAS las plantillas (cabecera): la resuelve el router
    # y lo pasa; si no, lo inferimos de la cookie para no romper vistas simples.
    if "user" not in ctx:
        ctx["user"] = users.current_user(request)
    ctx["display_label"] = users.display_label(ctx.get("user"))
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


def _login_after_oauth(user_id):
    """Abre sesión para user_id, redirige a /mi con set-cookie de sesión y limpia
    la cookie de estado del flow."""
    token = users.open_session(user_id)
    resp = RedirectResponse(url="/mi", status_code=303)
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

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = users.current_user(request)
    # Mosaico de portadas del fondo del hero (decorativo, best-effort).
    try:
        mosaic = db.sample_cover_thumbs(60)
    except Exception:
        mosaic = []
    return _render(request, "home.html", user=user, mosaic=mosaic)


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


def _spotify_search_link(*parts):
    """Link "escuchar en Spotify": búsqueda pública de los `parts` (p.ej. artista +
    título de obra, o solo el artista). SIN OAuth ni API key (patrón de degradación
    honesta del diseño). Devuelve {"web", "app"}: `app` es la URI `spotify:` que abre
    la APP de escritorio/móvil si está instalada; `web` es el fallback en el navegador
    (lo maneja el JS: intenta la app y cae a la web). None si no hay texto útil."""
    import urllib.parse
    q = " ".join(p for p in parts if p).strip()
    if not q:
        return None
    quoted = urllib.parse.quote(q)
    return {"web": "https://open.spotify.com/search/" + quoted,
            "app": "spotify:search:" + quoted}


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
        spotify_url=_spotify_search_link(work.get("artist_name"), work.get("title")),
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
    # Backfill de FOTO DE ARTISTA sin bloquear: si la ficha mostraría el
    # monograma (image_url NULL), pide la foto a Discogs (mismo worker/throttle
    # que las portadas). Esta carga muestra monograma; la siguiente ya trae foto.
    covers.request_missing_artists(artist)
    return _render(
        request, "artist.html",
        artist=artist,
        discography=discography,
        spotify_url=_spotify_search_link(artist.get("name")),
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
        f_for_you = ex.submit(users.recommend_for_user, uid, 12)
        f_listening = ex.submit(users.recommend_from_listening, uid, 12)
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
# Auth ligera (server-side, sin OAuth — eso es M3b)
# ---------------------------------------------------------------------------

@app.post("/auth/guest")
def auth_guest(request: Request):
    """Crea una cuenta LIGERA (invitado) + sesión + set-cookie. Redirige a /mi.

    Idempotente con sesión válida: si ya hay cookie válida, no fabrica duplicado.
    """
    existing = users.current_user(request)
    resp = RedirectResponse(url="/mi", status_code=303)
    if existing:
        return resp
    _uid, token = users.start_guest()
    _set_session_cookie(resp, token)
    return resp


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
    guest = users.current_user(request)
    guest_id = guest["id"] if (guest and users.is_guest(guest)) else None
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
    return _login_after_oauth(user_id)


@app.get("/auth/lastfm/login")
def lastfm_login(request: Request):
    """Inicia el auth flow de Last.fm: guarda el invitado (si lo hay) en estado
    server-side y redirige a last.fm/api/auth con api_key + cb. Sin credenciales
    → aviso 'no configurado' (no 500)."""
    if not oauth.lastfm_configured():
        return _oauth_error(
            request, "Last.fm",
            "El login con Last.fm no está configurado en este entorno.")
    guest = users.current_user(request)
    guest_id = guest["id"] if (guest and users.is_guest(guest)) else None
    state = oauth.FLOW_STORE.put({
        "provider": "lastfm",
        "guest_user_id": guest_id,
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
    return _login_after_oauth(user_id)


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
