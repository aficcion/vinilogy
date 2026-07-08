"""Dominio press — capa editorial de prensa española (EL CORAZÓN de M2).

Fachada sobre `db.get_press_signals` / `db.press_signals_batch` /
`db.resolve_suena_a_artists`. Da forma a "La crítica dice": frases con
atribución a la cabecera, chips de vibra, "suena a" (enlazable cuando el artista
resuelve a uno con vinilo en core) y temas destacados.

Además destila un `porque` EDITORIAL corto para la recomendación cuando la obra
recomendada tiene señales de prensa (apoyado en la crítica real, no genérico).

Límite one-way: press depende de db; nada de la reco/catálogo al revés salvo por
esta fachada. No inventa: sin señales → estructura vacía / porque None.
"""
from app import db


def get_signals(work_id, resolve_suena_a=True):
    """Señales agregadas de prensa para la ficha de obra.

    Devuelve el agregado de `db.get_press_signals` + `has_signals` (bool) y, si
    `resolve_suena_a`, `suena_a_links` = [{name, artist_id|None}] para enlazar los
    artistas de "suena a" que resuelven a uno con vinilo en core.
    """
    agg = db.get_press_signals(work_id)
    has = bool(agg["frases"] or agg["vibra"] or agg["suena_a"]
               or agg["temas_destacados"])
    agg["has_signals"] = has
    if resolve_suena_a and agg["suena_a"]:
        resolved = db.resolve_suena_a_artists(agg["suena_a"])
        agg["suena_a_links"] = [
            {"name": n, "artist_id": resolved.get(n)} for n in agg["suena_a"]
        ]
    else:
        agg["suena_a_links"] = [
            {"name": n, "artist_id": None} for n in agg["suena_a"]
        ]
    return agg


def _editorial_porque(agg):
    """Frase-porqué EDITORIAL corta desde el agregado de prensa. None si no da.

    Preferencia: (1) los primeros adjetivos de `vibra` ("la crítica lo describe
    como X, Y y Z"); (2) si no hay vibra pero sí frase, una versión recortada de
    la primera `frase_vibra` ("según la crítica: …"). Sin señales útiles → None.
    """
    vibra = agg.get("vibra") or []
    if vibra:
        shown = vibra[:3]
        if len(shown) == 1:
            listado = shown[0]
        elif len(shown) == 2:
            listado = "{} y {}".format(shown[0], shown[1])
        else:
            listado = "{}, {} y {}".format(shown[0], shown[1], shown[2])
        return "la crítica lo describe como {}".format(listado)
    frases = agg.get("frases") or []
    if frases:
        frase = frases[0]["frase"].strip().rstrip(".")
        if len(frase) > 120:
            frase = frase[:117].rstrip(",;: ") + "…"
        return "según la crítica: {}".format(frase.lower()[:1] + frase[1:]
                                             if frase else frase)
    return None


def enrich_porque_batch(items):
    """Sustituye el `porque` genérico por uno EDITORIAL donde haya prensa.

    Batch SIN N+1: UNA sola query (`db.press_signals_batch`) para el conjunto de
    obras recomendadas. Muta cada item que tenga señales (deja `porque_source`=
    'press'); los demás conservan su `porque` de M1 (`porque_source`='content').
    Devuelve la misma lista (mutada in place) por comodidad del caller.
    """
    if not items:
        return items
    ids = [it.get("id") for it in items if it.get("id") is not None]
    signals = db.press_signals_batch(ids)  # 1 query
    for it in items:
        agg = signals.get(it.get("id"))
        editorial = _editorial_porque(agg) if agg else None
        if editorial:
            it["porque"] = editorial
            it["porque_source"] = "press"
        else:
            it.setdefault("porque_source", "content")
    return items
