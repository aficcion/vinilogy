"""Dominio users — M3c: sesión + identidad + wishlist + cuenta + capa personal.

Fachada fina sobre db.py para la capa de USUARIO (la única que escribe en core, y
solo en sus tablas — `app_users`/`user_sessions`/`user_oauth_credentials`/
`user_wishlist` —; es su función, no es DDL). Aquí viven:
  - sesión server-side (cookie `vb_session`): abrir/validar/cerrar + la dependencia
    FastAPI `current_user` (cookie → user o None). El "invitado" se retiró (Fase 3):
    la identidad la da OAuth y la wishlist anónima vive en el navegador.
  - wishlist del usuario con sesión (la anónima NO pasa por aquí).
  - cuenta: estado de conexiones, desvincular proveedor (con salvaguarda de última
    identidad) y borrar cuenta.
  - resumen de colección + recomendación PERSONAL ("Para ti" por grafo de
    co-escucha de Last.fm) + gap de vinilo, delegando en db.py + pricing.

El OAuth real (Google/Discogs/Last.fm) vive en el submódulo `oauth`. `providers` de
un usuario se LEE para saber qué identidades tiene vinculadas.

Límite one-way: users depende de db/pricing; nada del catálogo depende de users.
"""
from app import db
from app.domains import pricing, covers
from app.domains.users import oauth  # noqa: F401 (identidad OAuth)

# Nombre de la cookie de sesión (httponly, server-side).
SESSION_COOKIE = "vb_session"

# Login-dev: solo existe si VINYLBE_DEV_LOGIN=1. Es el gancho de prueba de la capa
# personal SIN pasar por OAuth real. En prod NO se monta el endpoint.
import os
DEV_LOGIN_ENABLED = os.environ.get("VINYLBE_DEV_LOGIN") == "1"


# ---------------------------------------------------------------------------
# Sesión (escritura acotada a app_users/user_sessions)
# ---------------------------------------------------------------------------
# El "invitado" se retiró en M3c · Fase 3: la wishlist anónima vive en el navegador
# (localStorage), así que una cuenta sin identidad ya no aporta. La identidad la da
# OAuth (Google/Discogs/Last.fm) y el linking vincula un 2º proveedor a la cuenta
# actual (ver oauth.map_identity). `db.create_guest_user` sobrevive como fábrica de
# usuarios mínima para el selftest, no como feature de producto.


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


def display_label(user):
    """Etiqueta para la cabecera: display_name (nombre del proveedor OAuth) si lo
    hay. Fallback neutro para el caso límite sin nombre (no debería darse: toda
    identidad OAuth rellena display_name)."""
    if not user:
        return None
    return user.get("display_name") or "Tu cuenta"


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
    """"Para ti" por GRAFO DE CO-ESCUCHA (Last.fm getSimilar). [] honesto si el
    usuario no tiene semillas en el grafo (el caller lo explica).

    NO se pasa por press.enrich_porque_batch (a diferencia de M1): el `porque` de
    esta sección ES la atribución a la co-escucha ("porque tienes A y B", con
    anclas REALES de su colección) y ese es precisamente el valor de la sección —
    la vibra de crítica sería otra sección, no esta (mismo criterio que
    recommend_from_listening).

    Encola las portadas que falten (convergencia) y devuelve la lista con portada."""
    res = db.recommend_for_user(user_id, limit=limit)
    covers.request_missing_ids(res.get("missing_cover_ids"))
    return res.get("works", [])


def recommend_from_listening(user_id, limit=12):
    """"Basado en lo que escuchas": la ESCUCHA REAL del usuario (Last.fm), en tres
    tiers (no poseído → upgrade → otros discos de sus artistas). [] honesto si el
    usuario no tiene escucha resuelta. Anónimo → [].

    Encola las portadas que falten (convergencia) y devuelve la lista con portada.
    Cada work lleva `tier` ('buy'|'upgrade'|'artist') y `porque`."""
    res = db.recommend_from_listening(user_id, limit=limit)
    covers.request_missing_ids(res.get("missing_cover_ids"))
    return res.get("works", [])


def vinyl_gap(user_id, limit=24):
    """Gap de vinilo con PRECIO por obra (reutiliza pricing). Cada ítem lleva sus
    ediciones de vinilo y su bloque de precios (o vacío honesto). Encola las
    portadas que falten (convergencia) y devuelve la lista con portada."""
    res = db.vinyl_gap(user_id, limit=limit)
    covers.request_missing_ids(res.get("missing_cover_ids"))
    items = res.get("works", [])
    for it in items:
        it["prices"] = pricing.get_prices_for_work(it["id"])
    return items


def vinyl_gap_count(user_id):
    """Conteo interno del gap (para el resumen honesto de /mi)."""
    return db.vinyl_gap_count(user_id)


# ---------------------------------------------------------------------------
# Wishlist (M3c · Fase 1)
# ---------------------------------------------------------------------------
# Escritura acotada a `user_wishlist`. La wishlist ANÓNIMA vive en el navegador
# (localStorage) y NO pasa por aquí; estas funciones son para usuarios con sesión.
# La hidratación de ids → tarjetas (portada/precio) la hace el router reutilizando
# catalog/covers/pricing, igual que el modo selección del buscador.


def wishlist_ids(user):
    """IDs guardados por el usuario, lo más reciente primero. [] si anónimo/vacía."""
    if not user:
        return []
    return db.wishlist_work_ids(user["id"])


def wishlist_add(user, work_id):
    """Guarda un disco. Idempotente. No-op si no hay usuario."""
    if user:
        db.wishlist_add(user["id"], work_id)


def wishlist_remove(user, work_id):
    """Quita un disco. No-op si no hay usuario."""
    if user:
        db.wishlist_remove(user["id"], work_id)


def wishlist_import(user, work_ids):
    """Fusiona los ids que traía el navegador (localStorage) tras iniciar sesión.
    Devuelve cuántos se guardaron de verdad. 0 si anónimo."""
    if not user:
        return 0
    return db.wishlist_add_many(user["id"], work_ids)


# ---------------------------------------------------------------------------
# Cuenta (M3c · Fase 2): conexiones + desvincular + borrar
# ---------------------------------------------------------------------------
# Roles de cada proveedor (por qué conectar cada uno) — el hilo del rediseño: cada
# conexión tiene un propósito distinto y explicable, no tres botones iguales.
_PROVIDER_DEFS = [
    {"key": "google", "label": "Google",
     "purpose": "Tu cuenta: guarda tu wishlist y llévala a todos tus dispositivos."},
    {"key": "discogs", "label": "Discogs",
     "purpose": "Importa tu colección real y calcula tu gap de vinilo."},
    {"key": "lastfm", "label": "Last.fm",
     "purpose": "Afina las recomendaciones con lo que de verdad escuchas."},
]


def connection_status(providers):
    """Estado de las 3 conexiones para /cuenta. Cada una: conectada, configurada en
    el entorno (si no, el botón avisa 'no disponible'), y su propósito. Marca
    `is_only` en la única identidad conectada (no se puede desvincular esa)."""
    connected = set(providers or [])
    configured = {
        "google": oauth.google_configured(),
        "discogs": oauth.discogs_configured(),
        "lastfm": oauth.lastfm_configured(),
    }
    n_connected = len(connected)
    out = []
    for d in _PROVIDER_DEFS:
        is_conn = d["key"] in connected
        out.append({
            **d,
            "connected": is_conn,
            "configured": configured.get(d["key"], False),
            "is_only": is_conn and n_connected <= 1,
        })
    return out


def disconnect_provider(user, provider):
    """Desvincula un proveedor. Se NIEGA si es la única identidad del usuario (si
    no, la cuenta quedaría sin forma de volver a entrar). Devuelve True si desvinculó.
    """
    providers = user.get("providers") or []
    if provider not in providers or len(providers) <= 1:
        return False
    db.delete_oauth_credential(user["id"], provider)
    return True


def delete_account(user):
    """Borra la cuenta y todo lo suyo (CASCADE). No-op si no hay usuario."""
    if user:
        db.delete_user_and_sessions(user["id"])


def export_user_data(user):
    """Vuelca los datos personales del usuario para portabilidad GDPR (derecho de
    acceso). None si anónimo. No incluye los tokens OAuth (credenciales de terceros,
    no datos del sujeto) — ver db.export_user_data."""
    if not user:
        return None
    return db.export_user_data(user["id"])
