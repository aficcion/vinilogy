"""i18n ligero para Vinilogy (ES por defecto + EN).

Sin frameworks ni build step: un diccionario `ES → EN` indexado por el propio texto
español (la "clave" es el string fuente), y un helper `t(texto, lang)`. Ventajas:
  · las plantillas quedan legibles: `{{ t('Precios en tiendas ES') }}`.
  · fallback natural: si falta una traducción, se muestra el español (nunca una clave
    cruda ni un hueco) → la web funciona aunque la traducción esté a medias.

Idioma por petición: cookie `vb_lang` (elección explícita del selector) > cabecera
Accept-Language (autodetección) > 'es'.
"""
from __future__ import annotations

SUPPORTED = ("es", "en")
DEFAULT = "es"
LANG_COOKIE = "vb_lang"

# ES → EN. Se rellena por bloques a medida que se traducen las plantillas/etiquetas.
# Clave = texto español EXACTO tal como aparece en la plantilla (sin espacios de más).
EN: dict[str, str] = {
    # ── cabecera / nav (base.html) ──
    "Busca un disco o un artista…": "Search a record or an artist…",
    "Buscar": "Search",
    "Por vibra ✦": "By vibe ✦",
    "Wishlist": "Wishlist",
    "Cuenta": "Account",
    "Salir": "Log out",
    "Entrar o crear cuenta": "Sign in or create account",
    "Cambiar tema": "Toggle theme",
    "Tu wishlist": "Your wishlist",
    # ── footer ──
    "Vinilogy · precios de vinilo en tiendas independientes de España":
        "Vinilogy · vinyl prices at independent record shops in Spain",
    "Privacidad": "Privacy",
}


def resolve_lang(request) -> str:
    """Idioma de la petición: cookie > Accept-Language > DEFAULT."""
    cookie = request.cookies.get(LANG_COOKIE)
    if cookie in SUPPORTED:
        return cookie
    accept = (request.headers.get("accept-language") or "").lower()
    # heurística barata: el primer idioma que reconozcamos gana
    for chunk in accept.replace(" ", "").split(","):
        code = chunk.split(";")[0][:2]
        if code in SUPPORTED:
            return code
    return DEFAULT


def t(text, lang):
    """Traduce `text` al idioma `lang`. ES (o desconocido) → el propio texto."""
    if lang == "en":
        return EN.get(text, text)
    return text
