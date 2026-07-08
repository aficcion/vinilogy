"""Dominio users — M3a: sesión + cuenta invitado + capa personal.

Fachada fina sobre db.py para la capa de USUARIO (la única que escribe en core, y
solo en `app_users`/`user_sessions` — es su función, no es DDL). Aquí viven:
  - auth ligera: crear invitado, abrir/validar/cerrar sesión (server-side).
  - dependencia FastAPI `current_user` (lee la cookie `vb_session` → user o None).
  - resumen de colección + recomendación PERSONAL (centroide de gusto) + gap de
    vinilo, delegando en db.py + pricing.

OAuth de Discogs/Last.fm es M3b (necesita credenciales + navegador): NO se cablea
aquí. `providers` de un usuario se LEE (para saber si es invitado puro o ya tiene
identidad vinculada).

Límite one-way: users depende de db/pricing; nada del catálogo depende de users.
"""
from app import db
from app.domains import pricing
from app.domains.users import oauth  # noqa: F401 (fachada M3b)

# Nombre de la cookie de sesión (httponly, server-side).
SESSION_COOKIE = "vb_session"

# Login-dev: solo existe si VINYLBE_DEV_LOGIN=1. Es el gancho de prueba de la capa
# personal SIN OAuth real (M3b). En prod NO se monta el endpoint.
import os
DEV_LOGIN_ENABLED = os.environ.get("VINYLBE_DEV_LOGIN") == "1"


# ---------------------------------------------------------------------------
# Sesión + invitado (escritura acotada a app_users/user_sessions)
# ---------------------------------------------------------------------------

def start_guest():
    """Crea invitado + sesión. Devuelve (user_id, session_token)."""
    user_id = db.create_guest_user()
    token = db.create_session(user_id)
    return user_id, token


def open_session(user_id):
    """Abre una sesión para un user existente. Devuelve el token."""
    return db.create_session(user_id)


def resolve_session(token):
    """token → app_user (dict con `providers`) o None. Refresca last_used_at."""
    return db.get_user_by_session(token)


def close_session(token):
    db.delete_session(token)


def get_user(user_id):
    return db.get_app_user(user_id)


def is_guest(user):
    """True si el user es una cuenta LIGERA sin identidad OAuth (display_name NULL
    y sin proveedores vinculados)."""
    if not user:
        return False
    return not (user.get("providers") or []) and not user.get("display_name")


def display_label(user):
    """Etiqueta para la cabecera: display_name si lo hay, si no 'Invitado'."""
    if not user:
        return None
    return user.get("display_name") or "Invitado"


# ---------------------------------------------------------------------------
# Dependencia FastAPI
# ---------------------------------------------------------------------------

def current_user(request):
    """Dependencia: lee la cookie `vb_session` → app_user (dict) o None (anónimo).

    Pensada para usarse como `Depends(current_user)` o llamada directa desde el
    router. No lanza si no hay cookie/sesión válida → None (anónimo funciona).
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return db.get_user_by_session(token)


# ---------------------------------------------------------------------------
# Capa personal: resumen de colección + reco + gap de vinilo
# ---------------------------------------------------------------------------

def collection_summary(user):
    """Resumen para la cabecera de /mi: nº ítems + valor (si lo hay en app_users).

    Devuelve dict con counts (total/resolved/vinyl/cd/other) y el valor formateado
    (mediana en €) cuando `collection_value_median` está poblado. None → sin valor.
    """
    counts = db.user_collection_summary(user["id"])
    value = None
    median = user.get("collection_value_median")
    if median is not None:
        cur = (user.get("collection_value_currency") or "EUR").strip()
        value = {
            "median": median,
            "currency": cur,
            "display": _fmt_money(median, cur),
            "updated_at": user.get("collection_value_updated_at"),
        }
    return {"counts": counts, "value": value}


def _fmt_money(amount, currency):
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return None
    if (currency or "EUR") == "EUR":
        return "{:,.0f} €".format(val).replace(",", ".")
    return "{:,.0f} {}".format(val, currency)


def recommend_for_user(user_id, limit=12):
    """Recomendación personal por centroide de gusto. [] honesto si el usuario no
    tiene colección con embeddings (el caller lo explica)."""
    from app.domains import press
    items = db.recommend_for_user(user_id, limit=limit)
    return press.enrich_porque_batch(items)


def recommend_from_listening(user_id, limit=12):
    """Recomendación por ESCUCHA de Last.fm (centroide de escucha, embeddings de
    core). [] honesto si el usuario no tiene datos Last.fm resueltos con embedding
    (la sección de /mi simplemente no aparece). Anónimo → [].

    A diferencia de recommend_for_user, NO se pasa por press.enrich_porque_batch:
    el `porque` de esta sección ES la atribución a la escucha ("en la onda de lo
    que escuchas (…)") y el valor de la sección es precisamente esa atribución —
    la vibra de crítica sería otra sección, no esta."""
    return db.recommend_from_listening(user_id, limit=limit)


def vinyl_gap(user_id, limit=24):
    """Gap de vinilo con PRECIO por obra (reutiliza pricing). Cada ítem lleva sus
    ediciones de vinilo y su bloque de precios (o vacío honesto)."""
    items = db.vinyl_gap(user_id, limit=limit)
    for it in items:
        it["prices"] = pricing.get_prices_for_work(it["id"])
    return items


def vinyl_gap_count(user_id):
    """Conteo interno del gap (para el resumen honesto de /mi)."""
    return db.vinyl_gap_count(user_id)
