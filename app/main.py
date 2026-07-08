"""Vinylbe v2 — M3a: capa personal (sesión + invitado + reco personal + /mi).

FastAPI + Jinja server-rendered. Sobre M0/M1/M2 (buscar → ficha → reco anónima)
añade:
  - auth ligera server-side (cookie `vb_session`): invitado, logout, y un
    LOGIN-DEV guardado (`VINYLBE_DEV_LOGIN=1`) para probar la capa personal sin
    OAuth real (eso es M3b).
  - `/mi`: perfil del usuario — "Para ti" (centroide de gusto) + "Sube a vinilo"
    (gap de vinilo con precio) + resumen de colección.
  - la reco anónima (`/buscar`, `/obra`, `/artista`, `/vibra`) EXCLUYE la
    colección cuando hay usuario logueado.

Arranque:
    VINYLBE_DB_DSN=postgresql://localhost/vinology_core VINYLBE_DEV_LOGIN=1 \
        uvicorn app.main:app --port 7788 --reload
"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.domains import catalog, pricing, reco, editorial, press, users

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


# ---------------------------------------------------------------------------
# Páginas (anónimas; excluyen colección cuando hay user)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    user = users.current_user(request)
    return _render(request, "home.html", user=user)


@app.get("/buscar", response_class=HTMLResponse)
def buscar(request: Request, q: str = ""):
    user = users.current_user(request)
    uid = user["id"] if user else None
    q = (q or "").strip()
    results = catalog.search(q) if q else {"works": [], "artists": []}
    affines = (
        reco.affine_for_search(results["works"], results["artists"],
                               exclude_user_id=uid)
        if q else None
    )
    return _render(
        request, "search.html",
        q=q,
        works=results["works"],
        artists=results["artists"],
        affines=affines,
        user=user,
    )


@app.get("/obra/{work_id}", response_class=HTMLResponse)
def obra(request: Request, work_id: int):
    user = users.current_user(request)
    uid = user["id"] if user else None
    work = catalog.get_work(work_id)
    if not work:
        return _render(request, "404.html", what="obra", ident=work_id,
                       status_code=404, user=user)
    editions = catalog.get_work_vinyl_editions(work_id)
    tracklist = catalog.get_work_tracklist(work_id)
    prices = pricing.get_prices_for_work(work_id)
    press_signals = press.get_signals(work_id)
    similar = reco.similar_to_work(work_id, exclude_user_id=uid)
    similar_press = reco.similar_by_press_to_work(work_id)
    artist = catalog.get_artist(work["artist_id"])
    artist_bio = catalog.artist_bio_excerpt(artist)
    return _render(
        request, "work.html",
        work=work,
        editions=editions,
        tracklist=tracklist,
        prices=prices,
        press=press_signals,
        similar=similar,
        similar_press=similar_press,
        artist_bio=artist_bio,
        user=user,
    )


@app.get("/artista/{artist_id}", response_class=HTMLResponse)
def artista(request: Request, artist_id: int):
    user = users.current_user(request)
    uid = user["id"] if user else None
    artist = catalog.get_artist(artist_id)
    if not artist:
        return _render(request, "404.html", what="artista", ident=artist_id,
                       status_code=404, user=user)
    discography = catalog.get_artist_discography(artist_id)
    similar = reco.similar_to_artist(artist_id, exclude_user_id=uid)
    return _render(
        request, "artist.html",
        artist=artist,
        discography=discography,
        similar=similar,
        user=user,
    )


@app.get("/vibra", response_class=HTMLResponse)
def vibra(request: Request, mood: str = "", q: str = ""):
    user = users.current_user(request)
    uid = user["id"] if user else None
    entry = (q or mood or "").strip()
    chips = editorial.list_mood_chips()
    result = (editorial.recommend_by_mood(entry, exclude_user_id=uid)
              if entry else None)
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
    for_you = users.recommend_for_user(user["id"], limit=12)
    gap = users.vinyl_gap(user["id"], limit=24)
    gap_total = users.vinyl_gap_count(user["id"])
    return _render(
        request, "mi.html",
        user=user,
        anon=False,
        summary=summary,
        for_you=for_you,
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
