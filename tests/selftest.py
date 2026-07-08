"""Selftest v0 de Vinylbe v2 — red de seguridad contra `vinology_core`.

Checks DUROS. Los fixtures se DERIVAN con SQL (no hay títulos hardcodeados
frágiles): si cambian los datos de core, el test sigue eligiendo una obra
válida en vez de romperse por un id concreto.

Correr:
    python3 -m tests.selftest       (o)   python3 tests/selftest.py

Sale con código != 0 si algún check falla.
"""
import sys
import os

# Permitir `python3 tests/selftest.py` además de `-m tests.selftest`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db  # noqa: E402

_FAILS = []
_PASSES = 0


def check(name, cond, detail=""):
    global _PASSES
    if cond:
        _PASSES += 1
        print("PASS  {}".format(name))
    else:
        _FAILS.append(name)
        print("FAIL  {}  -- {}".format(name, detail))


def _q(sql, params=None):
    with db._cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()


# ---------------------------------------------------------------------------
# Fixtures derivados por SQL
# ---------------------------------------------------------------------------

def derive_fixtures():
    fx = {}

    # Work popular con vinilo cuyo artista TIENE listings con precio.
    rows = _q("""
        SELECT w.id
        FROM works w
        WHERE w.has_vinyl = true
          AND EXISTS (
              SELECT 1 FROM marketplace_listings ml
              WHERE ml.artist_id = w.primary_artist_id AND ml.price_cents > 0
          )
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_with_prices"] = rows[0]["id"] if rows else None

    # Work top por popularidad con vinilo (para editions).
    rows = _q("""
        SELECT w.id
        FROM works w
        WHERE w.has_vinyl = true
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_top_vinyl"] = rows[0]["id"] if rows else None

    # Work cuyo artista NO tiene ningún listing (camino honesto → precios []).
    rows = _q("""
        SELECT w.id
        FROM works w
        WHERE w.has_vinyl = true
          AND NOT EXISTS (
              SELECT 1 FROM marketplace_listings ml
              WHERE ml.artist_id = w.primary_artist_id
          )
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_no_prices"] = rows[0]["id"] if rows else None

    # Artista primary con >=3 works de estudio/EP en vinilo (para discografía).
    rows = _q("""
        SELECT w.primary_artist_id AS artist_id
        FROM works w
        WHERE w.has_vinyl = true
          AND w.work_type IN ('studio_album','ep')
        GROUP BY w.primary_artist_id
        HAVING count(*) >= 3
        ORDER BY max(w.releases_count) DESC NULLS LAST
        LIMIT 1
    """)
    fx["artist_with_discog"] = rows[0]["artist_id"] if rows else None

    # Work POPULAR con embedding y con vinilo (semilla de similar_to_work).
    rows = _q("""
        SELECT w.id
        FROM works w
        WHERE w.has_vinyl = true
          AND w.embedding IS NOT NULL
          AND w.work_type IN ('studio_album','ep')
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_with_embedding"] = rows[0]["id"] if rows else None

    # Artista con >=1 work con embedding y vinilo (semilla de similar_to_artist).
    rows = _q("""
        SELECT w.primary_artist_id AS artist_id
        FROM works w
        WHERE w.has_vinyl = true
          AND w.embedding IS NOT NULL
          AND w.work_type IN ('studio_album','ep')
        GROUP BY w.primary_artist_id
        ORDER BY max(w.releases_count) DESC NULLS LAST
        LIMIT 1
    """)
    fx["artist_with_embedding"] = rows[0]["artist_id"] if rows else None

    # Work con vinilo SIN embedding (camino honesto → similar = []).
    rows = _q("""
        SELECT id FROM works
        WHERE has_vinyl = true AND embedding IS NULL
        LIMIT 1
    """)
    fx["work_without_embedding"] = rows[0]["id"] if rows else None

    return fx


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def run_checks(fx):
    # 1. search_works SOLO devuelve works con has_vinyl.
    # Derivamos un término de búsqueda del título de una work con vinilo.
    seed = _q("""
        SELECT split_part(w.title, ' ', 1) AS term
        FROM works w
        WHERE w.has_vinyl = true AND length(w.title) > 4
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    term = seed[0]["term"] if seed else "love"
    results = db.search_works(term, limit=20)
    check(
        "search_works devuelve resultados",
        len(results) > 0,
        "término '{}' no devolvió nada".format(term),
    )
    # Verificar has_vinyl de cada resultado vía get_work.
    all_vinyl = True
    for r in results:
        w = db.get_work(r["id"])
        if not (w and w["has_vinyl"] is True):
            all_vinyl = False
            break
    check(
        "search_works SOLO devuelve works con has_vinyl=true",
        all_vinyl,
        "algún resultado no tenía has_vinyl",
    )

    # 2. Work top por popularidad con vinilo → >=1 edición vinilo.
    if fx["work_top_vinyl"]:
        eds = db.get_work_vinyl_editions(fx["work_top_vinyl"])
        check(
            "get_work_vinyl_editions devuelve >=1 edición vinilo",
            len(eds) >= 1,
            "work {} sin ediciones vinilo".format(fx["work_top_vinyl"]),
        )
    else:
        check("fixture work_top_vinyl existe", False, "no derivada")

    # 3. Work cuyo artista tiene listings → >=1 precio, EUR, price>0, asc.
    if fx["work_with_prices"]:
        prices = db.get_prices_for_work(fx["work_with_prices"])
        check(
            "get_prices_for_work devuelve >=1 precio",
            len(prices) >= 1,
            "work {} sin precios".format(fx["work_with_prices"]),
        )
        if prices:
            all_valid = all(
                (p["price_cents"] or 0) > 0 and p["currency"] == "EUR"
                for p in prices
            )
            check(
                "precios tienen price_cents>0 y currency='EUR'",
                all_valid,
                "algún listing inválido",
            )
            cents = [p["price_cents"] for p in prices]
            check(
                "precios ordenados ASC por price_cents",
                cents == sorted(cents),
                "orden roto: {}".format(cents[:6]),
            )
            has_freshness = all(
                "data_as_of" in p and "stale" in p for p in prices
            )
            check(
                "cada precio lleva data_as_of + stale (frescura)",
                has_freshness,
                "faltan campos de frescura",
            )
    else:
        check("fixture work_with_prices existe", False, "no derivada")

    # 4. Work cuyo artista NO tiene listings → precios [] sin petar.
    if fx["work_no_prices"]:
        try:
            prices = db.get_prices_for_work(fx["work_no_prices"])
            check(
                "work sin listings → precios [] (camino honesto)",
                prices == [],
                "esperado [], obtenido {} filas".format(len(prices)),
            )
        except Exception as e:  # noqa: BLE001
            check("work sin listings no peta", False, repr(e))
    else:
        # No es un fallo si todo artista con vinilo tuviera listings (improbable),
        # pero lo marcamos como skip informativo.
        print("SKIP  fixture work_no_prices no derivada (sin caso limpio)")

    # 5. Discografía: sin morralla + ordenada por playcount desc.
    if fx["artist_with_discog"]:
        discog = db.get_artist_discography(fx["artist_with_discog"], limit=40)
        check(
            "discografía devuelve resultados",
            len(discog) > 0,
            "artista {} sin discografía".format(fx["artist_with_discog"]),
        )
        types_ok = all(w["work_type"] in ("studio_album", "ep") for w in discog)
        check(
            "discografía sin morralla (solo studio_album/ep)",
            types_ok,
            "tipos: {}".format(sorted({w["work_type"] for w in discog})),
        )
        # No expone playcount crudo al render.
        no_raw_playcount = all("lastfm_playcount" not in w for w in discog)
        check(
            "discografía NO expone lastfm_playcount crudo (regla de números)",
            no_raw_playcount,
            "playcount crudo filtrado al render",
        )
        # Monotonía de orden por playcount con NULLS al final.
        # Reconsultamos el playcount para verificar la monotonía (el orden lo
        # produce el SQL; validamos que efectivamente decrece con NULLS last).
        ids = [w["id"] for w in discog]
        pc_rows = _q(
            "SELECT id, lastfm_playcount FROM works WHERE id = ANY(%(ids)s)",
            {"ids": ids},
        )
        pc_map = {r["id"]: r["lastfm_playcount"] for r in pc_rows}
        seq = [pc_map[i] for i in ids]
        # non-null decreciente, y ningún non-null tras un NULL.
        seen_null = False
        monotone = True
        prev = None
        for v in seq:
            if v is None:
                seen_null = True
            else:
                if seen_null:
                    monotone = False
                    break
                if prev is not None and v > prev:
                    monotone = False
                    break
                prev = v
        check(
            "discografía ordenada por playcount DESC (NULLS al final)",
            monotone,
            "secuencia: {}".format(seq[:8]),
        )
    else:
        check("fixture artist_with_discog existe", False, "no derivada")

    # -----------------------------------------------------------------------
    # M1 — recomendación por contenido (embeddings) + mood
    # -----------------------------------------------------------------------

    # 7. similar_to_work: excluye el propio artista, cap 1/artista, vinilo,
    #    studio_album/ep, todos con `porque`.
    if fx["work_with_embedding"]:
        seed_id = fx["work_with_embedding"]
        seed_w = db.get_work(seed_id)
        seed_artist = seed_w["artist_id"] if seed_w else None
        sims = db.recommend_similar_to_work(seed_id, limit=12)
        check(
            "similar_to_work devuelve resultados",
            len(sims) > 0,
            "seed {} sin similares".format(seed_id),
        )
        check(
            "similar_to_work NUNCA devuelve el mismo primary_artist_id que el seed",
            all(s["artist_id"] != seed_artist for s in sims),
            "seed artist {} coló".format(seed_artist),
        )
        art_ids = [s["artist_id"] for s in sims]
        check(
            "similar_to_work cap por artista = 1 (sin artistas repetidos)",
            len(set(art_ids)) == len(art_ids),
            "artistas repetidos: {}".format(art_ids),
        )
        # Verificar vinilo/tipo/porque contra la BD.
        all_ok = True
        for s in sims:
            w = db.get_work(s["id"])
            if not (w and w["has_vinyl"] is True
                    and w["work_type"] in ("studio_album", "ep")):
                all_ok = False
                break
        check(
            "similar_to_work solo vinilo + studio_album/ep",
            all_ok,
            "algún similar sin vinilo o con morralla",
        )
        check(
            "similar_to_work todos con `porque` no vacío",
            all((s.get("porque") or "").strip() for s in sims),
            "algún similar sin porque",
        )
    else:
        check("fixture work_with_embedding existe", False, "no derivada")

    # 8. similar_to_work con seed SIN embedding → [] honesto.
    if fx["work_without_embedding"]:
        try:
            sims = db.recommend_similar_to_work(fx["work_without_embedding"])
            check(
                "similar_to_work sin embedding → [] honesto",
                sims == [],
                "esperado [], obtenido {}".format(len(sims)),
            )
        except Exception as e:  # noqa: BLE001
            check("similar_to_work sin embedding no peta", False, repr(e))
    else:
        print("SKIP  fixture work_without_embedding (no hay works sin embedding)")

    # 9. similar_to_artist: excluye al propio artista, cap, vinilo/sin morralla.
    if fx["artist_with_embedding"]:
        aid = fx["artist_with_embedding"]
        sims = db.recommend_similar_to_artist(aid, limit=12)
        check(
            "similar_to_artist devuelve resultados",
            len(sims) > 0,
            "artista {} sin similares".format(aid),
        )
        check(
            "similar_to_artist excluye al propio artista",
            all(s["artist_id"] != aid for s in sims),
            "el propio artista coló",
        )
        art_ids = [s["artist_id"] for s in sims]
        check(
            "similar_to_artist cap por artista = 1",
            len(set(art_ids)) == len(art_ids),
            "artistas repetidos: {}".format(art_ids),
        )
        all_ok = True
        for s in sims:
            w = db.get_work(s["id"])
            if not (w and w["has_vinyl"] is True
                    and w["work_type"] in ("studio_album", "ep")):
                all_ok = False
                break
        check(
            "similar_to_artist solo vinilo + studio_album/ep",
            all_ok,
            "algún similar sin vinilo o con morralla",
        )
        check(
            "similar_to_artist todos con `porque`",
            all((s.get("porque") or "").strip() for s in sims),
            "algún similar sin porque",
        )
    else:
        check("fixture artist_with_embedding existe", False, "no derivada")

    # 9b. similar_to_artist fallback: probamos un artista con >=1 work embebido.
    #     La función degrada a la obra más popular si el centroide falla; en
    #     ambos casos debe devolver resultados válidos (ya cubierto por el
    #     artista popular; verificamos que NO peta con un artista de 1 solo work).
    rows = _q("""
        SELECT w.primary_artist_id AS aid
        FROM works w
        WHERE w.has_vinyl = true AND w.embedding IS NOT NULL
          AND w.work_type IN ('studio_album','ep')
        GROUP BY w.primary_artist_id
        HAVING count(*) = 1
        ORDER BY max(w.releases_count) DESC NULLS LAST
        LIMIT 1
    """)
    if rows:
        try:
            sims = db.recommend_similar_to_artist(rows[0]["aid"], limit=6)
            check(
                "similar_to_artist (artista de 1 work, ruta fallback) no peta y da resultados",
                len(sims) > 0 and all(s["artist_id"] != rows[0]["aid"] for s in sims),
                "fallback vacío o coló el propio artista",
            )
        except Exception as e:  # noqa: BLE001
            check("similar_to_artist fallback no peta", False, repr(e))

    # 10. recommend_by_mood: mood conocido → >=N vinilos, todos con porque.
    from app.domains import editorial
    from app.domains.editorial import mood_lexicon
    known = mood_lexicon.MOODS[0]["key"]
    res = editorial.recommend_by_mood(known, limit=20)
    check(
        "recommend_by_mood(mood conocido) devuelve >=5 vinilos",
        res["mood"] is not None and len(res["results"]) >= 5,
        "mood '{}' devolvió {}".format(known, len(res["results"])),
    )
    if res["results"]:
        # todos con vinilo (via get_work) + porque no vacío.
        vinyl_ok = True
        for it in res["results"]:
            w = db.get_work(it["id"])
            if not (w and w["has_vinyl"] is True):
                vinyl_ok = False
                break
        check("recommend_by_mood: todos los items tienen has_vinyl", vinyl_ok,
              "algún item sin vinilo")
        check(
            "recommend_by_mood: todos con `porque` no vacío",
            all((it.get("porque") or "").strip() for it in res["results"]),
            "algún item sin porque",
        )

    # 11. recommend_by_mood: texto inexistente → degradación honesta sin excepción.
    try:
        res = editorial.recommend_by_mood("xyzqwerty-no-existe-vibra")
        check(
            "recommend_by_mood(texto inexistente) → mood None + items []",
            res["mood"] is None and res["results"] == [],
            "esperado degradación honesta, obtenido {}".format(res),
        )
        check(
            "recommend_by_mood degradado ofrece chips sugeridos",
            len(res.get("suggestions") or []) > 0,
            "sin sugerencias",
        )
    except Exception as e:  # noqa: BLE001
        check("recommend_by_mood(texto inexistente) no peta", False, repr(e))

    # 12. Léxico: todos los styles del léxico EXISTEN en core (no inventados).
    all_styles = set()
    for m in mood_lexicon.MOODS:
        all_styles.update(m["styles"])
    present = _q(
        "SELECT name FROM styles WHERE name = ANY(%(names)s)",
        {"names": list(all_styles)},
    )
    present_names = {r["name"] for r in present}
    missing = all_styles - present_names
    check(
        "léxico de mood: todos los styles existen en core",
        not missing,
        "styles inexistentes: {}".format(sorted(missing)),
    )

    # 13. Resolución de texto libre del léxico (acentos/sinónimos).
    check(
        "léxico resuelve texto libre con acentos ('domingo lluvioso')",
        (mood_lexicon.resolve("algo para un domingo lluvioso") or {}).get("key")
        == "domingo_lluvioso",
        "no resolvió domingo lluvioso",
    )

    # 6. get_work / get_artist → None para id inexistente sin excepción.
    BOGUS = 999999999
    try:
        check("get_work(id inexistente) → None", db.get_work(BOGUS) is None)
    except Exception as e:  # noqa: BLE001
        check("get_work(id inexistente) no peta", False, repr(e))
    try:
        check("get_artist(id inexistente) → None", db.get_artist(BOGUS) is None)
    except Exception as e:  # noqa: BLE001
        check("get_artist(id inexistente) no peta", False, repr(e))


def run_http_smoke(fx):
    """Smoke test HTTP opcional con TestClient. No rompe el selftest si falta
    httpx/starlette TestClient (dependencia opcional)."""
    try:
        from fastapi.testclient import TestClient
        from app.main import app
    except Exception as e:  # noqa: BLE001
        print("SKIP  smoke HTTP (TestClient no disponible: {})".format(e))
        return

    client = TestClient(app)
    r = client.get("/")
    check("GET / → 200", r.status_code == 200, "status {}".format(r.status_code))

    r = client.get("/buscar", params={"q": "radiohead"})
    check("GET /buscar?q=radiohead → 200", r.status_code == 200,
          "status {}".format(r.status_code))

    if fx["work_with_embedding"]:
        r = client.get("/obra/{}".format(fx["work_with_embedding"]))
        check("GET /obra/{id} real → 200", r.status_code == 200,
              "status {}".format(r.status_code))
        check("GET /obra/{id} contiene 'afines'",
              "afines" in r.text.lower(),
              "no aparece 'afines' en la ficha de obra")
    elif fx["work_top_vinyl"]:
        r = client.get("/obra/{}".format(fx["work_top_vinyl"]))
        check("GET /obra/{id} real → 200", r.status_code == 200,
              "status {}".format(r.status_code))

    if fx["artist_with_embedding"]:
        r = client.get("/artista/{}".format(fx["artist_with_embedding"]))
        check("GET /artista/{id} → 200", r.status_code == 200,
              "status {}".format(r.status_code))
        check("GET /artista/{id} contiene 'onda'",
              "onda" in r.text.lower(),
              "no aparece 'onda' en la ficha de artista")

    r = client.get("/vibra")
    check("GET /vibra → 200", r.status_code == 200,
          "status {}".format(r.status_code))
    r = client.get("/vibra", params={"mood": "festivo"})
    check("GET /vibra?mood=festivo → 200 con grid",
          r.status_code == 200 and "porque" in r.text.lower()
          and "card-porque" in r.text,
          "status {} / falta porque".format(r.status_code))

    r = client.get("/obra/999999999")
    check("GET /obra/{inexistente} → 404", r.status_code == 404,
          "status {}".format(r.status_code))


def main():
    print("== Vinylbe v2 selftest (core: {}) ==".format(
        os.environ.get("VINYLBE_DB_DSN", "postgresql://localhost/vinology_core")))
    fx = derive_fixtures()
    print("Fixtures: {}".format(fx))
    print("-" * 60)
    run_checks(fx)
    print("-" * 60)
    run_http_smoke(fx)
    print("-" * 60)
    print("{} PASS, {} FAIL".format(_PASSES, len(_FAILS)))
    if _FAILS:
        print("FALLOS: {}".format(", ".join(_FAILS)))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
