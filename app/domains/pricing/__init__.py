"""Dominio pricing: lectura de marketplace_listings, orden por precio, frescura.

Fachada sobre db.get_prices_for_work + formateo para render (euros, etiqueta de
disponibilidad, nota de frescura). Nunca inventa precio: si db devuelve [], se
propaga vacío y la vista lo dice honestamente.
"""
from app import db

# Etiquetas legibles para el campo `availability` de core.
_AVAILABILITY_LABELS = {
    "in_stock": "En stock",
    "listed": "Listado",
    "on_request": "Bajo pedido",
    "out_of_stock": "Agotado",
}

# Nombres legibles de tienda (por `source` en core).
_SOURCE_LABELS = {
    "bajoelvolcan": "Bajo el Volcán",
    "borabora": "Discos Bora Bora",
    "marilians-internacional": "Marilians (internacional)",
    "marilians-nacional": "Marilians (nacional)",
    "altafidelidad": "Discos Alta Fidelidad",
}


def _fmt_price(cents, currency):
    if cents is None:
        return None
    value = cents / 100.0
    if (currency or "EUR") == "EUR":
        return "{:.2f} €".format(value).replace(".", ",")
    return "{:.2f} {}".format(value, currency)


def attach_cheapest(works):
    """Adorna una lista de obras (dicts) con su precio ES MÁS BARATO, en lote.

    A cada obra le añade `cheapest_price` (str tipo "32,95 €" o None) y
    `cheapest_store` (nombre de tienda) para pintarlo en la tarjeta. Una sola query
    para toda la lista (ver db.cheapest_prices_for_works); mismo match que la ficha.
    Devuelve la misma lista (mutada) por comodidad. Acepta []/None sin romper.
    """
    items = [w for w in (works or []) if w and w.get("id") is not None]
    if not items:
        return works
    by_id = db.cheapest_prices_for_works([w["id"] for w in items])
    for w in items:
        row = by_id.get(w["id"])
        if row:
            w["cheapest_price"] = _fmt_price(row.get("price_cents"), row.get("currency"))
            w["cheapest_store"] = _SOURCE_LABELS.get(row.get("source"), row.get("source"))
        else:
            w["cheapest_price"] = None
            w["cheapest_store"] = None
    return works


def get_prices_for_work(work_id, max_age_days=None):
    """Precios ordenados asc, decorados para render.

    Devuelve un dict:
      - listings: filas con `price_display`, `store_label`, `availability_label`
      - any_stale: bool (algún dato envejecido)
      - data_as_of: fecha más antigua entre los listings (para la nota de frescura)
    """
    rows = db.get_prices_for_work(work_id, max_age_days=max_age_days)
    out = []
    any_stale = False
    oldest = None
    for r in rows:
        r = dict(r)
        r["price_display"] = _fmt_price(r.get("price_cents"), r.get("currency"))
        r["store_label"] = _SOURCE_LABELS.get(r.get("source"), r.get("source"))
        r["availability_label"] = _AVAILABILITY_LABELS.get(
            r.get("availability"), r.get("availability") or "—"
        )
        if r.get("stale"):
            any_stale = True
        d = r.get("data_as_of")
        if d is not None and (oldest is None or d < oldest):
            oldest = d
        out.append(r)
    return {
        "listings": out,
        "any_stale": any_stale,
        "data_as_of": oldest,
    }
