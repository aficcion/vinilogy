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

    # -- M2 --

    # Work con vinilo cuya edición representativa tiene tracklist (para tracklist).
    rows = _q("""
        SELECT r.work_id AS id
        FROM releases r
        JOIN works w ON w.id = r.work_id
        WHERE w.has_vinyl = true
          AND r.format = 'vinyl'
          AND r.tracklist_cache IS NOT NULL
          AND jsonb_typeof(r.tracklist_cache) = 'array'
          AND jsonb_array_length(r.tracklist_cache) >= 4
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_with_tracklist"] = rows[0]["id"] if rows else None

    # Work con vinilo que SÍ tiene señales de prensa con frase_vibra (para press).
    rows = _q("""
        SELECT p.work_id AS id
        FROM work_press_signals p
        JOIN works w ON w.id = p.work_id
        WHERE w.has_vinyl = true AND p.frase_vibra IS NOT NULL
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_with_press"] = rows[0]["id"] if rows else None

    # Work con vinilo SIN ninguna señal de prensa (camino honesto → []).
    rows = _q("""
        SELECT w.id
        FROM works w
        WHERE w.has_vinyl = true
          AND NOT EXISTS (SELECT 1 FROM work_press_signals p WHERE p.work_id = w.id)
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_no_press"] = rows[0]["id"] if rows else None

    # Seed CON embedding_press (para similar_by_press) — obra de verdad, vinilo.
    rows = _q("""
        SELECT w.id
        FROM works w
        WHERE w.has_vinyl = true
          AND w.embedding_press IS NOT NULL
          AND w.work_type IN ('studio_album','ep')
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 1
    """)
    fx["work_with_embedding_press"] = rows[0]["id"] if rows else None

    # Work con vinilo SIN embedding_press (para similar_by_press → []).
    rows = _q("""
        SELECT id FROM works
        WHERE has_vinyl = true AND embedding IS NOT NULL AND embedding_press IS NULL
          AND work_type IN ('studio_album','ep')
        LIMIT 1
    """)
    fx["work_without_embedding_press"] = rows[0]["id"] if rows else None

    # Seed cuyos vecinos por contenido incluyen alguna obra CON prensa (para el
    # check de porqué editorial). Se busca en Python en run_checks (necesita reco);
    # aquí solo dejamos la lista de candidatos-semilla (populares con prensa).
    rows = _q("""
        SELECT w.id
        FROM works w
        JOIN work_press_signals p ON p.work_id = w.id
        WHERE w.has_vinyl = true AND w.embedding IS NOT NULL
          AND w.work_type IN ('studio_album','ep')
        ORDER BY w.releases_count DESC NULLS LAST
        LIMIT 40
    """)
    fx["press_seed_candidates"] = [r["id"] for r in rows]

    # -- M3a: usuarios FIXTURE reales (user 1 = Carlos, con colección + gap) --
    # No los inventamos: si no existen, los checks personales se marcan skip.
    rows = _q("SELECT id FROM app_users WHERE id = 1")
    fx["fixture_user"] = rows[0]["id"] if rows else None

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

    # -----------------------------------------------------------------------
    # M2 — tracklist, prensa, porqué editorial, similar_by_press, anti-morralla
    # -----------------------------------------------------------------------

    # 14. get_work_tracklist: pistas normalizadas (position/title/duration).
    if fx["work_with_tracklist"]:
        tl = db.get_work_tracklist(fx["work_with_tracklist"])
        check(
            "get_work_tracklist devuelve pistas",
            len(tl) >= 1,
            "work {} sin tracklist".format(fx["work_with_tracklist"]),
        )
        if tl:
            shape_ok = all(
                set(t.keys()) == {"position", "title", "duration"} for t in tl
            )
            check("tracklist normalizada a {position,title,duration}", shape_ok,
                  "claves inesperadas: {}".format(tl[0].keys()))
            titles_ok = all((t["title"] or "").strip() for t in tl)
            check("tracklist: todos los títulos presentes (no vacíos)", titles_ok,
                  "alguna pista sin título")
            pos_ok = any(t["position"] for t in tl)
            check("tracklist: al menos alguna posición presente (A1/B2…)", pos_ok,
                  "ninguna pista con posición")
    else:
        check("fixture work_with_tracklist existe", False, "no derivada")

    # 15. get_press_signals: frase/vibra/suena_a para obra CON prensa.
    if fx["work_with_press"]:
        from app.domains import press as press_dom
        ps = db.get_press_signals(fx["work_with_press"])
        check(
            "get_press_signals: >=1 frase_vibra para obra con prensa",
            len(ps["frases"]) >= 1,
            "sin frases",
        )
        check(
            "get_press_signals: frase con atribución a cabecera (source_label)",
            all(f.get("source_label") for f in ps["frases"]),
            "alguna frase sin cabecera",
        )
        check(
            "get_press_signals: vibra o suena_a poblados",
            bool(ps["vibra"] or ps["suena_a"]),
            "vibra/suena_a vacíos",
        )
        # dedup case-insensitive de vibra
        low = [v.lower() for v in ps["vibra"]]
        check("get_press_signals: vibra dedup (sin repes case-insensitive)",
              len(low) == len(set(low)), "vibra con duplicados")
        # fachada press.get_signals marca has_signals True + links de suena_a
        sig = press_dom.get_signals(fx["work_with_press"])
        check("press.get_signals: has_signals=True para obra con prensa",
              sig["has_signals"] is True, "has_signals no True")
        check("press.get_signals: suena_a_links poblado (mismo nº que suena_a)",
              len(sig["suena_a_links"]) == len(sig["suena_a"]),
              "links descuadrados")
    else:
        check("fixture work_with_press existe", False, "no derivada")

    # 16. get_press_signals: obra SIN prensa → estructura vacía limpia.
    if fx["work_no_press"]:
        ps = db.get_press_signals(fx["work_no_press"])
        empty_ok = (ps["frases"] == [] and ps["vibra"] == []
                    and ps["suena_a"] == [] and ps["temas_destacados"] == []
                    and ps["sources"] == [])
        check("get_press_signals: obra sin prensa → estructura vacía", empty_ok,
              "esperado vacío, obtenido {}".format(ps))
        from app.domains import press as press_dom
        sig = press_dom.get_signals(fx["work_no_press"])
        check("press.get_signals: has_signals=False sin prensa",
              sig["has_signals"] is False, "has_signals no False")
    else:
        print("SKIP  fixture work_no_press (sin caso limpio)")

    # 17. Porqué editorial: alguna obra recomendada con prensa refleja la crítica
    #     (NO el genérico), vía batch sin N+1.
    from app.domains import reco as reco_dom
    press_backed_found = False
    for seed in (fx.get("press_seed_candidates") or []):
        items = reco_dom.similar_to_work(seed, limit=12)
        press_items = [it for it in items if it.get("porque_source") == "press"]
        if press_items:
            press_backed_found = True
            it = press_items[0]
            gen = "afín en género y estilo"
            check(
                "porqué editorial: item con prensa NO usa el porqué genérico",
                gen not in (it.get("porque") or ""),
                "porqué sigue genérico: {}".format(it.get("porque")),
            )
            check(
                "porqué editorial: refleja la crítica ('la crítica'/'según la crítica')",
                "crítica" in (it.get("porque") or "").lower(),
                "porqué no menciona la crítica: {}".format(it.get("porque")),
            )
            break
    check("porqué editorial: se encontró al menos una reco apoyada en prensa",
          press_backed_found,
          "ningún seed candidato produjo recos con prensa")

    # 17b. Batch sin N+1: press_signals_batch trae N obras en 1 query (nº acotado).
    ids = (fx.get("press_seed_candidates") or [])[:10]
    if ids:
        import app.db as _dbmod
        calls = {"n": 0}
        orig = _dbmod._cursor
        from contextlib import contextmanager

        @contextmanager
        def _counting_cursor(*a, **k):
            calls["n"] += 1
            with orig(*a, **k) as cur:
                yield cur

        _dbmod._cursor = _counting_cursor
        try:
            db.press_signals_batch(ids)
        finally:
            _dbmod._cursor = orig
        check("press_signals_batch: 1 sola query para el conjunto (sin N+1)",
              calls["n"] == 1, "usó {} cursores".format(calls["n"]))

    # 18. similar_by_press: seed CON embedding_press → excluye mismo artista,
    #     cap 1/artista, solo vinilo, `porque` de crítica.
    if fx["work_with_embedding_press"]:
        seed_id = fx["work_with_embedding_press"]
        seed_w = db.get_work(seed_id)
        seed_artist = seed_w["artist_id"] if seed_w else None
        sims = db.similar_by_press(seed_id, limit=8)
        check("similar_by_press devuelve resultados para seed con embedding_press",
              len(sims) > 0, "seed {} sin afines por prensa".format(seed_id))
        check("similar_by_press excluye el propio artista",
              all(s["artist_id"] != seed_artist for s in sims),
              "coló el propio artista")
        aids = [s["artist_id"] for s in sims]
        check("similar_by_press cap 1/artista", len(set(aids)) == len(aids),
              "artistas repetidos")
        vinyl_ok = True
        for s in sims:
            w = db.get_work(s["id"])
            if not (w and w["has_vinyl"] is True
                    and w["work_type"] in ("studio_album", "ep")):
                vinyl_ok = False
                break
        check("similar_by_press solo vinilo + studio_album/ep", vinyl_ok,
              "algún afín sin vinilo o con morralla")
        check("similar_by_press todos con `porque`",
              all((s.get("porque") or "").strip() for s in sims),
              "algún afín sin porque")
    else:
        check("fixture work_with_embedding_press existe", False, "no derivada")

    # 19. similar_by_press: seed SIN embedding_press → [] honesto.
    if fx["work_without_embedding_press"]:
        sims = db.similar_by_press(fx["work_without_embedding_press"])
        check("similar_by_press sin embedding_press → [] honesto", sims == [],
              "esperado [], obtenido {}".format(len(sims)))
    else:
        print("SKIP  fixture work_without_embedding_press (no hay caso limpio)")

    # 20. Anti-morralla: ningún camino de reco devuelve artistas kind='various'
    #     ni el literal "Various"/"Various Artists" ni tributos.
    def _artist_kinds_and_names(items):
        aids = [it["artist_id"] for it in items if it.get("artist_id")]
        if not aids:
            return []
        return _q("SELECT kind, lower(btrim(name)) AS lname, lower(name) AS namel "
                  "FROM artists WHERE id = ANY(%(ids)s)", {"ids": aids})

    BAD_NAMES = {"various", "various artists", "varios", "v.a.", "va"}
    checked_any = False
    for seed in (fx.get("press_seed_candidates") or [])[:5]:
        for items in (reco_dom.similar_to_work(seed, limit=12),):
            meta = _artist_kinds_and_names(items)
            checked_any = checked_any or bool(meta)
            no_various = all(
                m["kind"] != "various"
                and m["lname"] not in BAD_NAMES
                and "tribute" not in m["namel"]
                for m in meta
            )
            check(
                "afines (obra) sin artistas various/tributo (seed {})".format(seed),
                no_various,
                "coló un artista morralla",
            )
    # mood también
    from app.domains import editorial as ed_dom
    mres = ed_dom.recommend_by_mood(mood_lexicon.MOODS[0]["key"], limit=20)
    mmeta = _artist_kinds_and_names(mres["results"])
    check("mood sin artistas various/tributo",
          all(m["kind"] != "various" and m["lname"] not in BAD_NAMES
              and "tribute" not in m["namel"] for m in mmeta),
          "coló un artista morralla en mood")

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

    # -----------------------------------------------------------------------
    # M3a — sesión + invitado + capa personal (user 1 fixture)
    # -----------------------------------------------------------------------
    run_m3a_checks(fx)


def run_m3a_checks(fx):
    from app.domains import users

    # 21. Round-trip invitado: crear + sesión + resolver (con LIMPIEZA garantizada).
    guest_id = None
    try:
        guest_id, token = users.start_guest()
        check("create_guest_user devuelve un id nuevo",
              isinstance(guest_id, int) and guest_id > 0,
              "id inválido: {}".format(guest_id))
        u = db.get_user_by_session(token)
        check("get_user_by_session resuelve la sesión recién creada",
              u is not None and u["id"] == guest_id,
              "no resolvió la sesión")
        if u:
            check("invitado: display_name NULL + sin providers (cuenta ligera)",
                  u["display_name"] is None and (u["providers"] == []),
                  "no parece invitado puro: {}".format(u))
        # token inválido → None
        check("get_user_by_session(token inválido) → None",
              db.get_user_by_session("no-existe-este-token-xyz") is None,
              "token inválido no dio None")
        # token expirado → None (sesión con TTL negativo)
        exp_tok = db.create_session(guest_id, ttl_days=-1)
        check("get_user_by_session(token expirado) → None",
              db.get_user_by_session(exp_tok) is None,
              "token expirado no dio None")
        # logout borra la sesión
        db.delete_session(token)
        check("delete_session invalida el token (logout)",
              db.get_user_by_session(token) is None,
              "el token seguía vivo tras logout")
    except Exception as e:  # noqa: BLE001
        check("round-trip invitado no peta", False, repr(e))
    finally:
        # LIMPIEZA: borrar el invitado de test y sus sesiones (CASCADE).
        if guest_id is not None:
            db.delete_user_and_sessions(guest_id)
            check("limpieza: el invitado de test queda BORRADO",
                  db.get_app_user(guest_id) is None,
                  "el invitado de test no se borró")

    if not fx.get("fixture_user"):
        print("SKIP  checks personales (no existe user 1 = Carlos en core)")
        return
    U = fx["fixture_user"]

    # 22. recommend_for_user(1): >=N vinilos, NINGUNO en la colección, con porque,
    #     cap 1/artista.
    recs = db.recommend_for_user(U, limit=12)
    check("recommend_for_user(1) devuelve >=6 resultados",
          len(recs) >= 6, "solo {} recos".format(len(recs)))
    with db._cursor() as cur:
        owned = set(db._owned_work_ids(cur, U))
    check("recommend_for_user(1): NINGUNA reco está en la colección del user",
          all(r["id"] not in owned for r in recs),
          "coló un disco de la colección")
    aids = [r["artist_id"] for r in recs]
    check("recommend_for_user(1): cap 1/artista (sin artistas repetidos)",
          len(set(aids)) == len(aids), "artistas repetidos")
    all_ok = all(
        (lambda w: w and w["has_vinyl"] is True
                   and w["work_type"] in ("studio_album", "ep"))(db.get_work(r["id"]))
        for r in recs)
    check("recommend_for_user(1): todos vinilo + studio_album/ep", all_ok,
          "alguna reco sin vinilo o con morralla")
    check("recommend_for_user(1): todos con `porque` no vacío",
          all((r.get("porque") or "").strip() for r in recs),
          "alguna reco sin porque")

    # 23. vinyl_gap(1): >0 (idealmente ~287), cada obra existe en vinilo, el user la
    #     tiene en formato≠vinyl y NO posee ya un prensado de vinilo; trae ediciones.
    gap_total = db.vinyl_gap_count(U)
    check("vinyl_gap_count(1) > 0 (gap real de vinilo)",
          gap_total > 0, "gap = {}".format(gap_total))
    check("vinyl_gap_count(1) en rango esperado (>200 para Carlos)",
          gap_total > 200, "gap = {} (esperado ~287)".format(gap_total))
    gap = db.vinyl_gap(U, limit=24)
    check("vinyl_gap(1) devuelve página de resultados",
          len(gap) > 0, "página vacía")
    # cada obra del gap tiene has_vinyl y trae >=1 edición de vinilo.
    gap_ok = all(
        (lambda w: w and w["has_vinyl"] is True)(db.get_work(g["id"]))
        and len(g.get("editions") or []) >= 1
        for g in gap)
    check("vinyl_gap(1): cada obra tiene has_vinyl y >=1 edición de vinilo",
          gap_ok, "alguna obra sin vinilo o sin ediciones")
    # DURO: el user NO posee ya un prensado de vinilo de ninguna obra del gap.
    gap_ids = [g["id"] for g in gap]
    if gap_ids:
        viol = _q("""
            SELECT DISTINCT r.work_id
            FROM user_collection uc JOIN releases r ON r.id = uc.release_id
            WHERE uc.user_id = %(u)s AND r.format = 'vinyl'
              AND r.work_id = ANY(%(ids)s)
        """, {"u": U, "ids": gap_ids})
        check("vinyl_gap(1): el user NO posee ya el vinilo de ninguna obra del gap",
              len(viol) == 0, "{} obras del gap ya en vinilo".format(len(viol)))
    # DURO: el user SÍ tiene cada obra del gap en formato ≠ vinilo.
    if gap_ids:
        missing_owned = _q("""
            SELECT g.wid FROM unnest(%(ids)s::bigint[]) g(wid)
            WHERE NOT EXISTS (
                SELECT 1 FROM user_collection uc JOIN releases r ON r.id = uc.release_id
                WHERE uc.user_id = %(u)s AND r.work_id = g.wid AND r.format <> 'vinyl'
            )
        """, {"u": U, "ids": gap_ids})
        check("vinyl_gap(1): el user tiene cada obra del gap en formato ≠ vinilo",
              len(missing_owned) == 0,
              "{} obras del gap no las tiene en no-vinilo".format(len(missing_owned)))
    check("vinyl_gap(1): cada ítem lleva `porque`",
          all((g.get("porque") or "").strip() for g in gap),
          "algún ítem del gap sin porque")

    # 24. Exclusión cruzada: afines con exclude_user_id=1 NO incluyen la colección.
    if fx.get("work_with_embedding"):
        sims = db.recommend_similar_to_work(
            fx["work_with_embedding"], limit=12, exclude_user_id=U)
        check("afines (obra) con exclude_user_id=1 excluyen la colección del user",
              all(s["id"] not in owned for s in sims),
              "coló un disco de la colección en afines")


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

    # M2: ficha de obra CON prensa muestra el bloque "crítica" + tracklist.
    if fx["work_with_press"]:
        r = client.get("/obra/{}".format(fx["work_with_press"]))
        check("GET /obra/{id_con_prensa} → 200", r.status_code == 200,
              "status {}".format(r.status_code))
        low = r.text.lower()
        check("GET /obra/{id_con_prensa} contiene 'crítica' (bloque de prensa)",
              "crítica" in low,
              "no aparece 'crítica' en la ficha con prensa")
        check("GET /obra/{id_con_prensa} muestra tracklist ('canciones')",
              "canciones" in low,
              "no aparece tracklist en la ficha con prensa")

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

    # ---- M3a: login-dev + /mi (con y sin sesión) ----
    from app.domains import users
    # /mi anónimo → invita a entrar, NO 500.
    r = client.get("/mi")
    check("GET /mi sin sesión → 200 e invita a entrar (no 500)",
          r.status_code == 200 and "invitado" in r.text.lower(),
          "status {} / no invita".format(r.status_code))

    if not users.DEV_LOGIN_ENABLED:
        print("SKIP  smoke login-dev (VINYLBE_DEV_LOGIN != 1)")
    elif fx.get("fixture_user"):
        # POST /dev/login/1 → set-cookie de sesión.
        r = client.post("/dev/login/1", follow_redirects=False)
        cookie = r.headers.get("set-cookie", "")
        check("POST /dev/login/1 → 303 + set-cookie vb_session",
              r.status_code in (302, 303) and "vb_session" in cookie,
              "status {} / cookie {}".format(r.status_code, cookie[:40]))
        # TestClient guarda la cookie automáticamente → /mi ahora es personal.
        r = client.get("/mi")
        check("GET /mi con sesión dev → 200 con 'Sube a vinilo'",
              r.status_code == 200 and "Sube a vinilo" in r.text,
              "status {} / falta gap".format(r.status_code))
        check("GET /mi con sesión dev → contiene 'Para ti'",
              "Para ti" in r.text, "falta 'Para ti'")
        # logout limpia la sesión.
        client.post("/auth/logout")
        r = client.get("/mi")
        check("GET /mi tras logout → vuelve a invitar (sesión cerrada)",
              "invitado" in r.text.lower(),
              "la sesión no se cerró")
    else:
        print("SKIP  smoke login-dev (no existe user 1)")

    # POST /auth/guest crea invitado + cookie; LIMPIEZA del invitado creado.
    guest_client = TestClient(app)
    r = guest_client.post("/auth/guest", follow_redirects=False)
    gcookie = r.headers.get("set-cookie", "")
    check("POST /auth/guest → 303 + set-cookie vb_session",
          r.status_code in (302, 303) and "vb_session" in gcookie,
          "status {} / cookie {}".format(r.status_code, gcookie[:40]))
    # resolver el user creado para borrarlo (limpieza).
    tok = None
    for part in gcookie.split(";"):
        if part.strip().startswith("vb_session="):
            tok = part.strip().split("=", 1)[1]
    if tok:
        gu = db.get_user_by_session(tok)
        if gu:
            db.delete_user_and_sessions(gu["id"])
            check("limpieza: invitado creado por /auth/guest borrado",
                  db.get_app_user(gu["id"]) is None, "no se borró")


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
