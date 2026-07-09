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
from app.domains import press, covers


def _unwrap_and_enqueue(result):
    """Desempaqueta el dict {"works", "missing_cover_ids"} de un camino de reco:
    ENCOLA los candidatos sin portada (convergencia de la regla transversal) y
    devuelve la lista de works CON portada a mostrar. Acepta también una lista pura
    (compat) → la devuelve tal cual."""
    if isinstance(result, dict):
        covers.request_missing_ids(result.get("missing_cover_ids"))
        return result.get("works", [])
    return result or []


def similar_to_work(work_id, limit=12, exclude_user_id=None):
    """Vinilos afines a una obra. [] honesto si el seed no tiene embedding.

    Con porqué editorial donde haya prensa (batch, 1 query extra). `exclude_user_id`
    (M3a): excluye la colección del logueado. Encola los afines sin portada
    (convergencia) y devuelve solo los que tienen portada de Discogs.
    """
    items = _unwrap_and_enqueue(db.recommend_similar_to_work(
        work_id, limit=limit, exclude_user_id=exclude_user_id))
    return press.enrich_porque_batch(items)


def similar_by_press_to_work(work_id, limit=8):
    """BONUS: afines por VIBRA DE CRÍTICA (`embedding_press`). [] si el seed no
    tiene embedding_press (la ficha oculta la sub-sección)."""
    return _unwrap_and_enqueue(db.similar_by_press(work_id, limit=limit))


def similar_to_artist(artist_id, limit=12, exclude_user_id=None):
    """Vinilos en la onda de un artista (centroide con fallback). [] si no hay semilla.

    Con porqué editorial donde haya prensa (batch, 1 query extra). `exclude_user_id`
    (M3a): excluye la colección del logueado. Encola los afines sin portada.
    """
    items = _unwrap_and_enqueue(db.recommend_similar_to_artist(
        artist_id, limit=limit, exclude_user_id=exclude_user_id))
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


def search_by_selection(artist_ids, work_ids, limit=12, exclude_user_id=None):
    """Búsqueda por SELECCIÓN (multi-select, §6): produce dos bloques y encola las
    portadas que falten (convergencia).

    Devuelve:
      {"artist_blocks": [{artist_id, artist_name, works:[...]}],  # top-3 por artista
       "combined": {"results": [...]}}                             # co-escucha combinada

    (1) Por cada ARTISTA seleccionado, sus 3 mejores álbumes en vinilo NO poseídos.
    (2) Recos COMBINADAS: los artistas seleccionados + los artistas de los works
        seleccionados como SEMILLAS de co-escucha (grafo Last.fm), excluye poseídos,
        ordena por score. Un work seleccionado → similares por su artista.
    """
    artist_ids = [int(a) for a in (artist_ids or []) if a is not None]
    work_ids = [int(w) for w in (work_ids or []) if w is not None]

    top = db.top_works_for_artists(
        artist_ids, per_artist=3, exclude_user_id=exclude_user_id)
    covers.request_missing_ids(top.get("missing_cover_ids"))

    # Semillas de co-escucha = artistas seleccionados + artistas de los works sel.
    seed_artists = list(artist_ids)
    if work_ids:
        for aid in db.works_primary_artists(work_ids):
            if aid not in seed_artists:
                seed_artists.append(aid)

    combined_items = _unwrap_and_enqueue(db.coescucha_from_seed_artists(
        seed_artists, limit=limit, exclude_user_id=exclude_user_id))
    combined_items = press.enrich_porque_batch(combined_items)

    return {
        "artist_blocks": top.get("blocks", []),
        "combined": {"results": combined_items},
    }
