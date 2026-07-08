"""Dominio reco — M1: recomendación por CONTENIDO (embeddings de core).

Fachada fina sobre db.py (SQL puro de pgvector, embeddings PRECALCULADOS — cero
embed en vivo, cero API externa). Explicabilidad `porque` en cada recomendación.

Además, un helper de orquestación para /buscar: dado el primer resultado fuerte
de una búsqueda (obra o artista), devuelve los "vinilos afines".

Límite one-way: reco depende de db/catalog/press, nunca al revés.

Porqués editoriales (M2): cuando una obra recomendada TIENE señales de prensa, su
`porque` se apoya en la crítica real (batch sin N+1 vía `press.enrich_porque_batch`);
sin señales, mantiene el `porque` de contenido de M1.
"""
from app import db
from app.domains import press


def similar_to_work(work_id, limit=12, exclude_user_id=None):
    """Vinilos afines a una obra. [] honesto si el seed no tiene embedding.

    Con porqué editorial donde haya prensa (batch, 1 query extra). `exclude_user_id`
    (M3a): excluye la colección del logueado de las recomendaciones.
    """
    items = db.recommend_similar_to_work(
        work_id, limit=limit, exclude_user_id=exclude_user_id)
    return press.enrich_porque_batch(items)


def similar_by_press_to_work(work_id, limit=8):
    """BONUS: afines por VIBRA DE CRÍTICA (`embedding_press`). [] si el seed no
    tiene embedding_press (la ficha oculta la sub-sección)."""
    return db.similar_by_press(work_id, limit=limit)


def similar_to_artist(artist_id, limit=12, exclude_user_id=None):
    """Vinilos en la onda de un artista (centroide con fallback). [] si no hay semilla.

    Con porqué editorial donde haya prensa (batch, 1 query extra). `exclude_user_id`
    (M3a): excluye la colección del logueado de las recomendaciones.
    """
    items = db.recommend_similar_to_artist(
        artist_id, limit=limit, exclude_user_id=exclude_user_id)
    return press.enrich_porque_batch(items)


def affine_for_search(works, artists, limit=12, exclude_user_id=None):
    """Bloque "Vinilos afines" para /buscar desde el primer resultado FUERTE.

    Preferencia: la primera OBRA (más específica que un artista). Si no hay obra
    pero sí artista, usa el primer artista. Devuelve un dict:
      - kind: 'work' | 'artist' | None
      - seed_title / seed_id: para la cabecera del bloque
      - items: recomendaciones con `porque`
    """
    if works:
        seed = works[0]
        items = similar_to_work(seed["id"], limit=limit,
                                exclude_user_id=exclude_user_id)
        return {
            "kind": "work",
            "seed_id": seed["id"],
            "seed_title": seed.get("title"),
            "seed_artist": seed.get("artist_name"),
            "results": items,
        }
    if artists:
        seed = artists[0]
        items = similar_to_artist(seed["id"], limit=limit,
                                  exclude_user_id=exclude_user_id)
        return {
            "kind": "artist",
            "seed_id": seed["id"],
            "seed_title": seed.get("name"),
            "seed_artist": None,
            "results": items,
        }
    return {"kind": None, "seed_id": None, "seed_title": None,
            "seed_artist": None, "results": []}
