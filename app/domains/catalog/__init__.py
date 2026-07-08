"""Dominio catalog: búsqueda de works/artists, ficha de obra, discografía.

Fachada fina sobre db.py. No hace SQL propio; expone la capa de catálogo al
router web. Los límites internos son one-way (catalog no depende de pricing).
"""
from app import db


def search(q, limit=20):
    """Búsqueda combinada: works con vinilo + artistas que casan."""
    return {
        "works": db.search_works(q, limit=limit),
        "artists": db.search_artists(q, limit=limit),
    }


def get_work(work_id):
    return db.get_work(work_id)


def get_work_vinyl_editions(work_id):
    return db.get_work_vinyl_editions(work_id)


def get_artist(artist_id):
    return db.get_artist(artist_id)


def get_artist_discography(artist_id, limit=40):
    return db.get_artist_discography(artist_id, limit=limit)
