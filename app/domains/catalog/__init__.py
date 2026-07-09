"""Dominio catalog: búsqueda de works/artists, ficha de obra, discografía.

Fachada fina sobre db.py. No hace SQL propio; expone la capa de catálogo al
router web. Los límites internos son one-way (catalog no depende de pricing).
"""
from concurrent.futures import ThreadPoolExecutor

from app import db


def search(q, limit=20):
    """Búsqueda combinada: works con vinilo + artistas que casan.

    Las dos queries son independientes y cada una tarda ~1-1,5s; se lanzan en
    PARALELO (el pool es ThreadedConnectionPool, cada hilo saca su conexión) para
    que `/buscar` no pague la suma en serie. Ver latencia medida en M2.

    Devuelve {"works", "artists", "missing_cover_ids"}: `works` son los que casan
    CON portada de Discogs; `missing_cover_ids` los candidatos SIN portada aún (el
    router los encola → convergencia de la regla transversal).
    """
    with ThreadPoolExecutor(max_workers=2) as ex:
        fw = ex.submit(db.search_works, q, limit)
        fa = ex.submit(db.search_artists, q, limit)
        wres = fw.result()
        return {
            "works": wres["works"],
            "artists": fa.result(),
            "missing_cover_ids": wres["missing_cover_ids"],
        }


def search_works_only(q, limit=20):
    """Solo la búsqueda de WORKS (dict {"works","missing_cover_ids"}). Para el
    router que solapa artistas+afines en paralelo (ver /buscar)."""
    return db.search_works(q, limit=limit)


def search_artists_only(q, limit=20):
    """Solo la búsqueda de ARTISTAS (lista). Para el router que la solapa con los
    afines en paralelo."""
    return db.search_artists(q, limit=limit)


def suggest(q, per_kind=6):
    """Sugerencias type-ahead: {artists:[{id,name}], works:[{id,title,artist_name,
    year}]}. Mismo ranking/filtros que search (portada-obligatoria en works). Min 3
    chars (lo controla db). NO devuelve missing_cover_ids (el buscador pleno los
    encola; sugerir es de solo lectura)."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        fw = ex.submit(db.search_works, q, per_kind)
        fa = ex.submit(db.search_artists, q, per_kind)
        works = fw.result()["works"]
        artists = fa.result()
    return {
        "artists": [{"id": a["id"], "name": a["name"]} for a in artists[:per_kind]],
        "works": [{"id": w["id"], "title": w["title"],
                   "artist_name": w.get("artist_name"), "year": w.get("year")}
                  for w in works[:per_kind]],
    }


def get_work(work_id):
    return db.get_work(work_id)


def get_work_vinyl_editions(work_id):
    return db.get_work_vinyl_editions(work_id)


def get_work_tracklist(work_id):
    """Tracklist normalizada de una edición de vinilo representativa. [] si no hay."""
    return db.get_work_tracklist(work_id)


_BIO_MAX_CHARS = 480


def artist_bio_excerpt(artist, max_chars=_BIO_MAX_CHARS):
    """Bio recortada del artista para el contexto en la ficha de obra.

    Corta en el límite de frase/palabra más cercano bajo `max_chars` y añade '…'.
    None/vacío → None (la vista oculta el bloque). No inventa.
    """
    bio = ((artist or {}).get("bio") or "").strip()
    if not bio:
        return None
    if len(bio) <= max_chars:
        return bio
    cut = bio[:max_chars]
    # Preferir cortar en el último punto; si no, en el último espacio.
    dot = cut.rfind(". ")
    if dot >= max_chars * 0.5:
        return cut[: dot + 1]
    sp = cut.rfind(" ")
    if sp > 0:
        cut = cut[:sp]
    return cut.rstrip(",;:. ") + "…"


def get_artist(artist_id):
    return db.get_artist(artist_id)


def get_artist_discography(artist_id, limit=40):
    """Discografía en vinilo: dict {"works", "missing_cover_ids"} (regla
    transversal de portada + convergencia)."""
    return db.get_artist_discography(artist_id, limit=limit)
