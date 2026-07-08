"""Dominio editorial — M1: recomendación por MOOD (léxico curado).

Fachada sobre el léxico (`mood_lexicon`) + db.works_by_styles_and_tags. Resuelve
texto libre/chip → mood → vinilos con `porque`. Mood no reconocido → degradación
honesta (lista vacía + los chips sugeridos), NUNCA inventa.

Límite one-way: editorial depende de db (y del léxico); nada depende de editorial.
"""
from app import db
from app.domains import press
from app.domains.editorial import mood_lexicon


def list_mood_chips():
    """[{key, label}] para pintar los chips de /vibra."""
    return mood_lexicon.list_moods()


def _porque_for(mood, row):
    """Frase-porqué desde los styles del mood que casaron (base fiable)."""
    matched = row.get("matched_styles") or []
    if matched:
        shown = ", ".join(matched[:3])
        return "por su vibra {} ({})".format(mood["label"].lower(), shown)
    return "por su vibra {}".format(mood["label"].lower())


def recommend_by_mood(text_or_key, limit=20):
    """Resuelve el texto→mood y devuelve vinilos afines con `porque`.

    Devuelve un dict:
      - mood: {key, label} reconocido, o None
      - items: filas con `porque` (o [] si no reconocido / sin resultados)
      - suggestions: chips sugeridos (siempre, para degradación honesta)
    """
    suggestions = mood_lexicon.list_moods()
    mood = mood_lexicon.resolve(text_or_key)
    if not mood:
        return {"mood": None, "results": [], "suggestions": suggestions}

    rows = db.works_by_styles_and_tags(
        style_names=mood["styles"],
        tag_whitelist=mood.get("tags"),
        limit=limit,
    )
    items = []
    for r in rows:
        r = dict(r)
        r["porque"] = _porque_for(mood, r)
        items.append(r)
    # Porqué editorial donde haya prensa (batch, 1 query). Sin señales → el
    # porqué de mood de M1.
    press.enrich_porque_batch(items)
    return {
        "mood": {"key": mood["key"], "label": mood["label"]},
        "results": items,
        "suggestions": suggestions,
    }
