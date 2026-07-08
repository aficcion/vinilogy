"""Vinylbe v2 — M0: esqueleto y contrato de datos.

FastAPI + Jinja server-rendered. Rutas mínimas: home, búsqueda, ficha de obra
(pieza estrella), discografía de artista. SIN reco / embeddings / auth (M1+).

Arranque:
    VINYLBE_DB_DSN=postgresql://localhost/vinology_core \
        uvicorn app.main:app --port 7788 --reload
"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.domains import catalog, pricing

_HERE = os.path.dirname(__file__)
_TEMPLATES_DIR = os.path.join(_HERE, "web", "templates")
_STATIC_DIR = os.path.join(_HERE, "web", "static")

app = FastAPI(title="Vinylbe v2", version="0.0.1-m0")
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _render(request, name, status_code=200, **ctx):
    ctx["request"] = request
    return templates.TemplateResponse(name, ctx, status_code=status_code)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return _render(request, "home.html")


@app.get("/buscar", response_class=HTMLResponse)
def buscar(request: Request, q: str = ""):
    q = (q or "").strip()
    results = catalog.search(q) if q else {"works": [], "artists": []}
    return _render(
        request, "search.html",
        q=q,
        works=results["works"],
        artists=results["artists"],
    )


@app.get("/obra/{work_id}", response_class=HTMLResponse)
def obra(request: Request, work_id: int):
    work = catalog.get_work(work_id)
    if not work:
        return _render(request, "404.html", what="obra", ident=work_id, status_code=404)
    editions = catalog.get_work_vinyl_editions(work_id)
    prices = pricing.get_prices_for_work(work_id)
    return _render(
        request, "work.html",
        work=work,
        editions=editions,
        prices=prices,
    )


@app.get("/artista/{artist_id}", response_class=HTMLResponse)
def artista(request: Request, artist_id: int):
    artist = catalog.get_artist(artist_id)
    if not artist:
        return _render(request, "404.html", what="artista", ident=artist_id, status_code=404)
    discography = catalog.get_artist_discography(artist_id)
    return _render(
        request, "artist.html",
        artist=artist,
        discography=discography,
    )
