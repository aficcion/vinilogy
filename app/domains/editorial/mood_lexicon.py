"""Léxico de mood curado — ESPAÑOL → styles (base fiable) + tags whitelisted.

Diferenciador de Vinilogy: recomendación por AMBIENTE. Sin embed en vivo
(decisión Carlos, 8-jul): la vibra se resuelve por LÉXICO curado sobre la
folksonomía limpia de core.

  - `styles`: la BASE. Todos VERIFICADOS que existen y están poblados en core
    (`styles` + `work_styles`, tier-1 limpios; medido 8-jul). Son la señal
    fiable — deciden el match.
  - `tags`: whitelist de tags de mood BUENOS (existen en `works.lastfm_tags`,
    verificados). Solo SUMAN señal de afinidad; nunca deciden solos (la
    folksonomía es ruidosa).
  - `sinonimos`: disparadores en español (sin acentos, minúsculas) para resolver
    texto libre / chips.

Ampliable: añade un mood aquí y aparece como chip en `/vibra` automáticamente.
Cada `key` es estable (se usa en URL). Si tocas styles, VERIFÍCALOS con psql.

TAG_BLACKLIST: basura conocida de la folksonomía (por si algún día se casan
tags fuera de whitelist).
"""

TAG_BLACKLIST = {
    "name", "url", "cover", "image", "images", "mbid", "streamable",
    "seen live", "albums i own", "favorites", "favourite albums",
    "vinyl", "spotify", "00s", "10s", "20s",
}

# Cada entrada:
#   key        -> slug estable (URL/chip)
#   label      -> etiqueta visible en ES
#   styles     -> lista de styles EXACTOS de core (verificados)
#   tags       -> whitelist de tags de mood (verificados en works.lastfm_tags)
#   sinonimos  -> disparadores ES (normalizados: minúsculas, sin acentos)
MOODS = [
    {
        "key": "melancolico",
        "label": "Melancólico / triste",
        "styles": ["Slowcore", "Dream Pop", "Shoegaze", "Ballad", "Folk"],
        "tags": ["melancholic", "melancholy", "sad", "moody"],
        "sinonimos": ["melancolico", "triste", "tristeza", "melancolia",
                      "nostalgia triste", "para llorar", "bajon", "pena"],
    },
    {
        "key": "animado",
        "label": "Animado / enérgico",
        "styles": ["Power Pop", "Garage Rock", "Punk", "Indie Rock"],
        "tags": ["energetic", "uplifting"],
        "sinonimos": ["animado", "energico", "energia", "alegre", "marcha",
                      "con energia", "para animarse", "eufórico", "euforico",
                      "vitalista"],
    },
    {
        "key": "oscuro",
        "label": "Oscuro / nocturno",
        "styles": ["Darkwave", "Coldwave", "Goth Rock", "Post-Punk",
                   "Dark Ambient"],
        "tags": ["dark", "nocturnal", "moody"],
        "sinonimos": ["oscuro", "nocturno", "de noche", "tenebroso", "sombrio",
                      "noche", "tinieblas", "gotico", "siniestro"],
    },
    {
        "key": "relajado",
        "label": "Relajado / chill",
        "styles": ["Downtempo", "Trip Hop", "Lounge", "Ambient"],
        "tags": ["chill", "chillout", "relaxing", "mellow"],
        "sinonimos": ["relajado", "chill", "tranquilo", "relax", "calma",
                      "descansar", "sosegado", "para relajarse", "chillout"],
    },
    {
        "key": "veraniego",
        "label": "Veraniego / soleado",
        "styles": ["Surf", "Nu-Disco", "Boogie", "Indie Pop"],
        "tags": ["summer", "summery"],
        "sinonimos": ["veraniego", "verano", "playa", "soleado", "solecito",
                      "estival", "para la playa", "vacaciones"],
    },
    {
        "key": "nostalgico",
        "label": "Nostálgico",
        "styles": ["New Wave", "Synth-pop", "Soft Rock", "Rock & Roll"],
        "tags": ["nostalgia", "nostalgic"],
        "sinonimos": ["nostalgico", "nostalgia", "retro", "de antes",
                      "recuerdos", "anhelo", "vintage"],
    },
    {
        "key": "romantico",
        "label": "Romántico",
        "styles": ["Soul", "Ballad", "Bossa Nova", "Smooth Jazz"],
        "tags": ["romantic", "mellow"],
        "sinonimos": ["romantico", "amor", "cita", "enamorado", "sensual",
                      "para dos", "velada", "intimo"],
    },
    {
        "key": "festivo",
        "label": "Festivo / baile",
        "styles": ["Disco", "House", "Funk", "Italo-Disco", "Nu-Disco"],
        "tags": ["party", "danceable"],
        "sinonimos": ["festivo", "fiesta", "baile", "bailar", "para bailar",
                      "party", "discoteca", "pista de baile", "juerga"],
    },
    {
        "key": "introspectivo",
        "label": "Introspectivo",
        "styles": ["Folk", "Acoustic", "Art Rock", "Slowcore"],
        "tags": ["introspective", "moody", "mellow"],
        "sinonimos": ["introspectivo", "reflexivo", "pensativo", "intimista",
                      "para pensar", "meditativo", "recogido"],
    },
    {
        "key": "canero",
        "label": "Cañero / potente",
        "styles": ["Hard Rock", "Heavy Metal", "Thrash", "Stoner Rock",
                   "Hardcore"],
        "tags": ["energetic"],
        "sinonimos": ["canero", "canera", "potente", "cana", "duro", "fuerte",
                      "heavy", "a tope", "para el gimnasio", "gimnasio", "gym",
                      "intenso", "guitarrazos"],
    },
    {
        "key": "psicodelico",
        "label": "Psicodélico",
        "styles": ["Psychedelic Rock", "Space Rock", "Krautrock", "Prog Rock"],
        "tags": ["psychedelic"],
        "sinonimos": ["psicodelico", "psicodelia", "lisergico", "viaje",
                      "trip", "espacial", "cosmico", "alucinante"],
    },
    {
        "key": "ensonador",
        "label": "Ensoñador / etéreo",
        "styles": ["Dream Pop", "Shoegaze", "Ambient", "Ethereal"],
        "tags": ["dreamy", "ethereal", "atmospheric", "dreampop"],
        "sinonimos": ["ensonador", "etereo", "onirico", "flotante", "sueno",
                      "sonar", "atmosferico", "ensonacion", "nebuloso"],
    },
    {
        "key": "domingo_lluvioso",
        "label": "Domingo lluvioso",
        "styles": ["Slowcore", "Ambient", "Folk", "Trip Hop"],
        "tags": ["rainy day", "late night", "melancholic", "atmospheric"],
        "sinonimos": ["domingo lluvioso", "lluvia", "lluvioso", "dia gris",
                      "gris", "para un domingo", "domingo", "otonal",
                      "tarde de lluvia"],
    },
    {
        "key": "jazz_nocturno",
        "label": "Jazz de madrugada",
        "styles": ["Cool Jazz", "Soul-Jazz", "Smooth Jazz", "Bossa Nova"],
        "tags": ["late night", "mellow", "atmospheric"],
        "sinonimos": ["jazz nocturno", "jazz", "madrugada", "copa", "whisky",
                      "bar", "de madrugada", "club de jazz"],
    },
]

_MOODS_BY_KEY = {m["key"]: m for m in MOODS}


def _norm(s):
    """Minúsculas, sin acentos, espacios colapsados."""
    import unicodedata
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().split())


def list_moods():
    """Moods para pintar los chips: [{key, label}]."""
    return [{"key": m["key"], "label": m["label"]} for m in MOODS]


def get_mood(key):
    return _MOODS_BY_KEY.get(key)


def resolve(text_or_key):
    """Texto libre / chip → mood dict, o None si no reconocido.

    Prioridad: (1) key exacta; (2) sinónimo exacto; (3) sinónimo/label contenido
    en el texto (o el texto contenido en un sinónimo). Tolerante a acentos/casing.
    """
    if not text_or_key:
        return None
    raw = text_or_key.strip()
    # 1. key exacta
    if raw in _MOODS_BY_KEY:
        return _MOODS_BY_KEY[raw]

    n = _norm(raw)
    if not n:
        return None

    # 2. sinónimo exacto
    for m in MOODS:
        if n in (_norm(x) for x in m["sinonimos"]):
            return m
        if n == _norm(m["label"]):
            return m

    # 3. contención en ambos sentidos (texto libre)
    best = None
    best_len = 0
    for m in MOODS:
        cands = [m["label"]] + m["sinonimos"]
        for c in cands:
            cn = _norm(c)
            if not cn:
                continue
            if cn in n or (len(cn) >= 4 and n in cn):
                # preferimos el disparador más largo (match más específico)
                if len(cn) > best_len:
                    best = m
                    best_len = len(cn)
    return best
