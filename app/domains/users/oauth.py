"""OAuth real — Google (OAuth2/OIDC) + Discogs (OAuth 1.0a) + Last.fm (api_sig).

Construye ENCIMA de la sesión server-side (`app.domains.users`): OAuth solo
establece IDENTIDAD y abre sesión; NO sincroniza colección/escucha (eso lo hace el
pipeline de core; v2 solo lee). Escritura acotada a `user_oauth_credentials` +
`app_users` (crear/last_login) vía db.py — su función, no DDL.

Cada proveedor cumple un rol distinto: Google = identidad/cuenta persistente,
Discogs = colección (gap de vinilo), Last.fm = escucha (reco). Conectar un 2º
proveedor estando logueado VINCULA la identidad a la cuenta actual (ver
`map_identity`), no crea otra.

Piezas (todas testeables SIN navegador):
  - `config()`               — lee secretos del entorno; los `*_configured()`
    comprueban por-proveedor (login "no configurado" degrada suave, no revienta).
  - `lastfm_api_sig(params)` — md5 firmado del flujo Last.fm (vector determinista).
  - `*_authorize_url` / `*_auth_url` — URLs de autorización/consentimiento formadas.
  - `map_identity(...)`      — la REGLA DE MAPEO pura: decide el user_id a partir de
    la credencial existente / usuario a vincular / nada. Sin red.
  - `FlowStore`              — estado server-side del flow (secreto de Discogs,
    `state` CSRF) ligado a la sesión del navegador por un `state` opaco, TTL corto.
  - clientes de red (`discogs_*`, `lastfm_session`, `google_exchange`,
    `google_identity`) — SÍ tocan red; se mockean en el selftest.

Límite one-way intacto: oauth depende de db (+ requests/oauthlib); nada del catálogo
depende de users/oauth.
"""
import os
import time
import json
import hashlib
import secrets
import urllib.parse

from app import db

# ---------------------------------------------------------------------------
# Constantes de proveedor (endpoints oficiales)
# ---------------------------------------------------------------------------
DISCOGS_REQUEST_TOKEN_URL = "https://api.discogs.com/oauth/request_token"
DISCOGS_AUTHORIZE_URL = "https://www.discogs.com/oauth/authorize"
DISCOGS_ACCESS_TOKEN_URL = "https://api.discogs.com/oauth/access_token"
DISCOGS_IDENTITY_URL = "https://api.discogs.com/oauth/identity"
DISCOGS_USER_AGENT = "Vinilogy/2.0 +https://vinylbe.local"

LASTFM_AUTH_URL = "http://www.last.fm/api/auth/"
LASTFM_API_ROOT = "https://ws.audioscrobbler.com/2.0/"

# Google — OAuth2 / OpenID Connect. Solo IDENTIDAD (openid email profile): a Google
# no le pedimos datos de música, solo "quién eres" para tener cuenta persistente.
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_SCOPE = "openid email profile"

PROVIDER_DISCOGS = "discogs"
PROVIDER_LASTFM = "lastfm"
PROVIDER_GOOGLE = "google"

_NET_TIMEOUT = 10  # s — degradación honesta ante red lenta.


# ---------------------------------------------------------------------------
# Configuración por entorno (secretos NUNCA hardcodeados)
# ---------------------------------------------------------------------------

def base_url():
    return (os.environ.get("VINILOGY_BASE_URL") or "http://localhost:7788").rstrip("/")


def config():
    """Secretos de OAuth desde el entorno. Devuelve dict con lo que haya; los
    handlers comprueban por-proveedor. NUNCA lanza (login no configurado degrada)."""
    return {
        "discogs_key": os.environ.get("DISCOGS_KEY") or "",
        "discogs_secret": os.environ.get("DISCOGS_SECRET") or "",
        "lastfm_key": os.environ.get("LASTFM_API_KEY") or "",
        "lastfm_secret": os.environ.get("LASTFM_API_SECRET") or "",
        "google_client_id": os.environ.get("GOOGLE_CLIENT_ID") or "",
        "google_client_secret": os.environ.get("GOOGLE_CLIENT_SECRET") or "",
        "base_url": base_url(),
    }


def discogs_configured(cfg=None):
    cfg = cfg or config()
    return bool(cfg["discogs_key"] and cfg["discogs_secret"])


def lastfm_configured(cfg=None):
    cfg = cfg or config()
    return bool(cfg["lastfm_key"] and cfg["lastfm_secret"])


def google_configured(cfg=None):
    cfg = cfg or config()
    return bool(cfg["google_client_id"] and cfg["google_client_secret"])


# ---------------------------------------------------------------------------
# Last.fm — cálculo de api_sig (determinista, testeable sin red)
# ---------------------------------------------------------------------------

def lastfm_api_sig(params, secret):
    """api_sig de Last.fm: md5( concat(k+v por clave ORDENADA) + secret ), hex.

    Regla oficial: se ordenan los parámetros por nombre, se concatenan como
    `k1v1k2v2…`, se pega el secreto compartido al final y se toma el md5 hex. NO
    entra `format` ni el propio `api_sig`. `secret` va SIEMPRE al final.
    """
    items = sorted((str(k), str(v)) for k, v in params.items()
                   if k not in ("format", "api_sig"))
    raw = "".join(k + v for k, v in items) + (secret or "")
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# URLs de autorización (bien formadas, sin red)
# ---------------------------------------------------------------------------

def discogs_callback_url(cfg=None):
    cfg = cfg or config()
    return cfg["base_url"] + "/auth/discogs/callback"


def lastfm_callback_url(cfg=None):
    cfg = cfg or config()
    return cfg["base_url"] + "/auth/lastfm/callback"


def discogs_authorize_url(oauth_token):
    """URL de autorización de Discogs para el request token obtenido."""
    return DISCOGS_AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {"oauth_token": oauth_token})


def lastfm_auth_url(cfg=None):
    """URL de auth de Last.fm con api_key + callback."""
    cfg = cfg or config()
    return LASTFM_AUTH_URL + "?" + urllib.parse.urlencode({
        "api_key": cfg["lastfm_key"],
        "cb": lastfm_callback_url(cfg),
    })


def google_callback_url(cfg=None):
    cfg = cfg or config()
    return cfg["base_url"] + "/auth/google/callback"


def google_authorize_url(state, cfg=None):
    """URL de consentimiento de Google (OAuth2 code flow). `state` es el token
    opaco del FlowStore (viaja también en cookie httponly → doble check CSRF en el
    callback). Scope mínimo (identidad); prompt=select_account para poder cambiar de
    cuenta."""
    cfg = cfg or config()
    return GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cfg["google_client_id"],
        "redirect_uri": google_callback_url(cfg),
        "response_type": "code",
        "scope": GOOGLE_SCOPE,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    })


# ---------------------------------------------------------------------------
# REGLA DE MAPEO DE IDENTIDAD (función PURA — el corazón del callback)
# ---------------------------------------------------------------------------

def map_identity(provider, provider_account_id, provider_username=None,
                 guest_user_id=None):
    """Decide el user_id de una identidad OAuth recién autenticada + persiste.

    Implementa los pasos 1-4 del mandato (UPSERT + mapeo), SIN tocar red (los
    tokens ya se obtuvieron): recibe la identidad ya resuelta y decide/crea el
    usuario, dejando la credencial persistida con tokens frescos.

    NOTA: los TOKENS frescos los pasa el caller vía `**creds` a través de
    `persist_identity` — esta función NO firma, solo MAPEA. Se mantiene pura
    (solo lee/escribe BD) para poder testearla con inserciones directas.

    Reglas:
      2. Existe (provider, provider_account_id) → devuelve su user_id (dueño).
      3. No existe y hay `guest_user_id` → VINCULA la identidad a ESE usuario. Es el
         "destino de vinculación": puede ser un invitado O una cuenta ya identificada
         que está conectando un SEGUNDO proveedor desde /cuenta (así no se crea una
         cuenta nueva ni se expulsa de la actual).
      4. No existe y no hay destino → crea app_users nuevo (login fresco anónimo).

    Devuelve (user_id, outcome) con outcome ∈ {'existing','linked_guest','new'}.
    (El nombre 'linked_guest' se conserva por compatibilidad; hoy cubre cualquier
    vinculación al usuario en sesión, no solo invitados.)
    """
    existing = db.find_oauth_credential(provider, provider_account_id)
    if existing:
        return existing["user_id"], "existing"
    if guest_user_id:
        return guest_user_id, "linked_guest"
    new_id = db.create_identified_user(display_name=provider_username)
    return new_id, "new"


def persist_identity(provider, provider_account_id, provider_username=None,
                     guest_user_id=None, oauth_token=None,
                     oauth_token_secret=None, session_key=None,
                     oauth2_access_token=None, oauth2_refresh_token=None,
                     oauth2_expires_at=None):
    """Aplica la regla de mapeo, UPSERTa los tokens frescos, rellena display_name
    del invitado si estaba vacío y toca last_login. Devuelve (user_id, outcome).

    Este es el punto ÚNICO que el callback usa tras completar el OAuth. Separa el
    mapeo puro (`map_identity`) de la escritura de tokens para que el test del
    mapeo no dependa de tokens reales. Los campos oauth2_* son para Google.
    """
    user_id, outcome = map_identity(
        provider, provider_account_id, provider_username, guest_user_id)
    db.upsert_oauth_credential(
        user_id=user_id, provider=provider,
        provider_account_id=provider_account_id,
        provider_username=provider_username,
        oauth_token=oauth_token, oauth_token_secret=oauth_token_secret,
        session_key=session_key,
        oauth2_access_token=oauth2_access_token,
        oauth2_refresh_token=oauth2_refresh_token,
        oauth2_expires_at=oauth2_expires_at,
    )
    if outcome == "linked_guest" and provider_username:
        db.set_display_name_if_empty(user_id, provider_username)
    db.touch_last_login(user_id)
    return user_id, outcome


# ---------------------------------------------------------------------------
# Estado del flow server-side (request-token-secret de Discogs, state de Last.fm)
# ---------------------------------------------------------------------------
#
# El request-token-secret de Discogs NO puede viajar en cookie plana (es un
# secreto). Lo guardamos en el PROCESO (monolito = 1 uvicorn), indexado por un
# `state` opaco que sí viaja en cookie httponly firmada, con TTL corto. El
# callback sin `state` (usuario que llega directo) → None → error suave, no 500.


class FlowStore:
    """Store en memoria del proceso para el estado del flow OAuth, con TTL.

    Ligado a la sesión del navegador vía un `state` opaco (cookie httponly).
    Un solo proceso uvicorn (monolito modular) → in-memory es suficiente y
    evita DDL (no podemos crear tablas de estado). Auto-purga entradas caducas.
    """

    def __init__(self, ttl_seconds=600):
        self._ttl = ttl_seconds
        self._data = {}  # state -> (expires_at, payload_dict)

    def put(self, payload):
        """Guarda `payload` (dict) bajo un state nuevo. Devuelve el state."""
        self._purge()
        state = secrets.token_urlsafe(24)
        self._data[state] = (time.time() + self._ttl, dict(payload))
        return state

    def pop(self, state):
        """Consume el estado (single-use). None si no existe o caducó."""
        self._purge()
        if not state:
            return None
        entry = self._data.pop(state, None)
        if not entry:
            return None
        expires_at, payload = entry
        if time.time() > expires_at:
            return None
        return payload

    def _purge(self):
        now = time.time()
        dead = [s for s, (exp, _) in self._data.items() if now > exp]
        for s in dead:
            self._data.pop(s, None)


# Instancia única del proceso.
FLOW_STORE = FlowStore()
OAUTH_STATE_COOKIE = "vb_oauth"


# ---------------------------------------------------------------------------
# Clientes de red (SÍ tocan red — se mockean en el selftest)
# ---------------------------------------------------------------------------

def _require_requests():
    import requests  # noqa: PLC0415
    return requests


def discogs_request_token(cfg=None):
    """Pide un request token a Discogs (OAuth1). Devuelve (oauth_token,
    oauth_token_secret). Lanza si Discogs rechaza (el caller degrada suave)."""
    cfg = cfg or config()
    from requests_oauthlib import OAuth1  # noqa: PLC0415
    requests = _require_requests()
    auth = OAuth1(
        cfg["discogs_key"], client_secret=cfg["discogs_secret"],
        callback_uri=discogs_callback_url(cfg),
    )
    resp = requests.post(
        DISCOGS_REQUEST_TOKEN_URL, auth=auth,
        headers={"User-Agent": DISCOGS_USER_AGENT}, timeout=_NET_TIMEOUT,
    )
    resp.raise_for_status()
    parsed = urllib.parse.parse_qs(resp.text)
    tok = parsed.get("oauth_token", [None])[0]
    sec = parsed.get("oauth_token_secret", [None])[0]
    if not tok or not sec:
        raise ValueError("Discogs request_token sin token/secret: {}".format(
            resp.text[:200]))
    return tok, sec


def discogs_access_token(oauth_token, request_token_secret, oauth_verifier,
                         cfg=None):
    """Intercambia request token + verifier por access token. Devuelve
    (access_token, access_token_secret)."""
    cfg = cfg or config()
    from requests_oauthlib import OAuth1  # noqa: PLC0415
    requests = _require_requests()
    auth = OAuth1(
        cfg["discogs_key"], client_secret=cfg["discogs_secret"],
        resource_owner_key=oauth_token,
        resource_owner_secret=request_token_secret,
        verifier=oauth_verifier,
    )
    resp = requests.post(
        DISCOGS_ACCESS_TOKEN_URL, auth=auth,
        headers={"User-Agent": DISCOGS_USER_AGENT}, timeout=_NET_TIMEOUT,
    )
    resp.raise_for_status()
    parsed = urllib.parse.parse_qs(resp.text)
    tok = parsed.get("oauth_token", [None])[0]
    sec = parsed.get("oauth_token_secret", [None])[0]
    if not tok or not sec:
        raise ValueError("Discogs access_token sin token/secret")
    return tok, sec


def discogs_identity(access_token, access_token_secret, cfg=None):
    """Llama a /oauth/identity con el access token. Devuelve (account_id, username).
    User-Agent SIEMPRE presente (Discogs lo exige)."""
    cfg = cfg or config()
    from requests_oauthlib import OAuth1  # noqa: PLC0415
    requests = _require_requests()
    auth = OAuth1(
        cfg["discogs_key"], client_secret=cfg["discogs_secret"],
        resource_owner_key=access_token,
        resource_owner_secret=access_token_secret,
    )
    resp = requests.get(
        DISCOGS_IDENTITY_URL, auth=auth,
        headers={"User-Agent": DISCOGS_USER_AGENT}, timeout=_NET_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    account_id = data.get("id")
    username = data.get("username")
    if account_id is None:
        raise ValueError("Discogs identity sin id")
    return str(account_id), username


def lastfm_session(token, cfg=None):
    """Intercambia el token del callback por una sesión Last.fm (auth.getSession,
    firmado con api_sig). Devuelve (session_key, username)."""
    cfg = cfg or config()
    requests = _require_requests()
    params = {
        "method": "auth.getSession",
        "api_key": cfg["lastfm_key"],
        "token": token,
    }
    params["api_sig"] = lastfm_api_sig(params, cfg["lastfm_secret"])
    params["format"] = "json"
    resp = requests.get(LASTFM_API_ROOT, params=params, timeout=_NET_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise ValueError("Last.fm getSession error {}: {}".format(
            data.get("error"), data.get("message")))
    session = data.get("session") or {}
    key = session.get("key")
    name = session.get("name")
    if not key or not name:
        raise ValueError("Last.fm getSession sin key/name: {}".format(
            json.dumps(data)[:200]))
    return key, name


def google_exchange(code, cfg=None):
    """Intercambia el `code` del callback por tokens (OAuth2 code flow). Devuelve el
    dict de token de Google: access_token, expires_in, id_token, (refresh_token)."""
    cfg = cfg or config()
    requests = _require_requests()
    resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": cfg["google_client_id"],
            "client_secret": cfg["google_client_secret"],
            "redirect_uri": google_callback_url(cfg),
            "grant_type": "authorization_code",
        },
        timeout=_NET_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("access_token"):
        raise ValueError("Google token sin access_token: {}".format(
            json.dumps(data)[:200]))
    return data


def google_identity(access_token, cfg=None):
    """Llama al endpoint userinfo (OIDC) con el access token. Devuelve
    (sub, email, name). `sub` es el id ESTABLE de la cuenta Google (no el email,
    que puede cambiar) → es el provider_account_id."""
    cfg = cfg or config()
    requests = _require_requests()
    resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": "Bearer " + access_token},
        timeout=_NET_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    sub = data.get("sub")
    if not sub:
        raise ValueError("Google userinfo sin sub: {}".format(
            json.dumps(data)[:200]))
    email = data.get("email")
    name = data.get("name") or email
    return str(sub), email, name
