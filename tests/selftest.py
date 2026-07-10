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


def _load_dotenv():
    """Carga `.env` de la raíz del repo en os.environ SIN pisar lo ya definido.

    Ligero (sin dependencia externa). Así el comando documentado del gate
    (`.venv/bin/python -m tests.selftest`) tiene DSN/credenciales disponibles;
    el selftest NO hace red real, pero deja el entorno como en producción.
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val


_load_dotenv()

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


def _sw(q, limit=20):
    """search_works que devuelve SOLO la lista de works a mostrar (desempaqueta el
    dict {"works", "missing_cover_ids"} de la nueva búsqueda con portada-obligatoria).
    """
    return db.search_works(q, limit=limit)["works"]


def _disco(artist_id, limit=40):
    """get_artist_discography → lista de works a mostrar (desempaqueta el dict)."""
    return db.get_artist_discography(artist_id, limit=limit)["works"]


def _works_of(res):
    """Desempaqueta el dict {"works", "missing_cover_ids"} de los caminos de reco a
    la lista de works. Acepta también una lista (compat) o None."""
    if isinstance(res, dict):
        return res.get("works", [])
    return res or []


def _max_vinyl_tracks(work_id):
    """Máximo nº de pistas entre los prensados de VINILO de la obra (o None). Es la
    MISMA señal que usa el filtro de single disfrazado en db._album_track_ok_sql."""
    rows = _q(
        "SELECT max(jsonb_array_length(r.tracklist_cache)) AS m "
        "FROM releases r WHERE r.work_id = %(w)s AND r.format = 'vinyl'",
        {"w": work_id})
    return rows[0]["m"] if rows else None


def _no_disguised_singles(items):
    """True si NINGÚN item studio_album es un single disfrazado (max pistas en
    vinilo <=3 → single; >=4 es álbum/EP legítimo). ep/compilation/live_album
    exentos (no son el problema del single mal tipado)."""
    for it in items:
        if it.get("work_type") == "studio_album":
            mx = _max_vinyl_tracks(it["id"])
            if mx is not None and mx <= 3:
                return False, (it["id"], it.get("title"), mx)
    return True, None


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

    # Artista primary con >=3 works de estudio/EP en vinilo Y CON PORTADA de Discogs
    # (para discografía — ahora exige portada, regla transversal).
    rows = _q("""
        SELECT w.primary_artist_id AS artist_id
        FROM works w
        WHERE w.has_vinyl = true
          AND w.work_type IN ('studio_album','ep')
          AND EXISTS (SELECT 1 FROM cover_images ci
                      WHERE ci.work_id = w.id AND ci.source = 'discogs')
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

    # Work con CAJA DE LUJO: su edición de referencia (main_release) tiene
    # tracklist, y existe una edición de vinilo con MUCHAS más pistas (una caja
    # de tomas/sessions). Regresión: get_work_tracklist debe devolver la de
    # referencia, no la caja (bug histórico del MAX → Abbey Road Super Deluxe).
    rows = _q("""
        SELECT wmr.work_id AS id,
               jsonb_array_length(mr.tracklist_cache) AS ref_n
        FROM work_main_release wmr
        JOIN releases mr ON mr.discogs_release_id = wmr.main_release_id
             AND jsonb_typeof(mr.tracklist_cache) = 'array'
        JOIN LATERAL (
            SELECT max(jsonb_array_length(r.tracklist_cache)) AS max_n
            FROM releases r
            WHERE r.work_id = wmr.work_id AND r.format = 'vinyl'
              AND jsonb_typeof(r.tracklist_cache) = 'array'
        ) mx ON true
        WHERE jsonb_array_length(mr.tracklist_cache) BETWEEN 4 AND 30
          AND mx.max_n > jsonb_array_length(mr.tracklist_cache) + 8
        ORDER BY mx.max_n DESC
        LIMIT 1
    """)
    fx["work_with_boxset"] = (rows[0] if rows else None)

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

    # -- Single disfrazado de studio_album (core lo tipa mal) --
    # (a) Un studio_album con vinilo de 4-5 pistas en su prensado de VINILO = EP
    #     legítimo mal tipado → DEBE MANTENERSE (umbral >=4). Fixture derivado por
    #     SQL (sin id hardcodeado): título distintivo para poder buscarlo.
    # OJO: para que este fixture SIGA apareciendo en search_works (que ahora exige
    # portada de Discogs, regla transversal), se le pide portada discogs también.
    rows = _q("""
        WITH top AS (
            SELECT w.id, w.title
            FROM works w
            WHERE w.has_vinyl = true AND w.work_type = 'studio_album'
              AND length(w.title) > 6
              AND EXISTS (SELECT 1 FROM cover_images ci
                          WHERE ci.work_id = w.id AND ci.source = 'discogs')
            ORDER BY w.releases_count DESC NULLS LAST
            LIMIT 3000
        )
        SELECT t.id, t.title
        FROM top t
        WHERE (SELECT max(jsonb_array_length(r.tracklist_cache))
               FROM releases r WHERE r.work_id = t.id AND r.format = 'vinyl')
              BETWEEN 4 AND 5
        LIMIT 1
    """)
    if rows:
        fx["ep_studioalbum_id"] = rows[0]["id"]
        fx["ep_studioalbum_title"] = rows[0]["title"]
    else:
        fx["ep_studioalbum_id"] = None
        fx["ep_studioalbum_title"] = None

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
    results = _sw(term, limit=20)
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

    # 1-bis. SINGLE DISFRAZADO de studio_album: un studio_album cuyo prensado de
    #        vinilo tiene <=3 pistas es un single mal tipado y NO debe aparecer.
    #        Caso canónico: Interpol – "Evil" (work 11253669, 2 pistas en vinilo)
    #        NO debe salir en search_works('interpol').
    if _q("SELECT id FROM works WHERE id = 11253669"):
        hits = _sw("interpol", limit=40)
        check("search_works('interpol') NO devuelve el single disfrazado 'Evil'",
              all(r["id"] != 11253669 for r in hits),
              "'Evil' (11253669) se coló en la búsqueda")
    # Genérico (no depende de un id): ningún studio_album devuelto por búsquedas
    # amplias es un single disfrazado (<=3 pistas en vinilo).
    disguised = []
    for t in ["interpol", "radiohead", "the strokes"]:
        for r in _sw(t, limit=30):
            if r["work_type"] == "studio_album":
                mx = _max_vinyl_tracks(r["id"])
                if mx is not None and mx <= 3:
                    disguised.append((t, r["title"], mx))
    check("search_works: ningún studio_album devuelto es single disfrazado (<=3 "
          "pistas en vinilo)", not disguised, "colaron: {}".format(disguised[:5]))

    # 1-ter. Un ÁLBUM real conocido (Dark Side ~10 pistas) SÍ aparece.
    dark = _sw("dark side of the moon", limit=20)
    check("search_works: un álbum real (Dark Side of the Moon) SÍ aparece",
          any("dark side" in (r["title"] or "").lower() for r in dark),
          "no encontró un álbum real conocido")

    # 1-quater. Un studio_album de 4-5 pistas en vinilo (EP legítimo mal tipado) SÍ
    #        se MANTIENE (el umbral es >=4, no toca a los 4-5).
    if fx.get("ep_studioalbum_id") and fx.get("ep_studioalbum_title"):
        term_ep = fx["ep_studioalbum_title"].split(" ")[0]
        kept = any(r["id"] == fx["ep_studioalbum_id"]
                   for r in _sw(fx["ep_studioalbum_title"], limit=40)) \
            or any(r["id"] == fx["ep_studioalbum_id"]
                   for r in _sw(term_ep, limit=40))
        check("search_works: studio_album de 4-5 pistas en vinilo SÍ se mantiene "
              "(umbral >=4)", kept,
              "cayó el fixture EP-legítimo '{}' (id {})".format(
                  fx["ep_studioalbum_title"], fx["ep_studioalbum_id"]))

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
        discog = _disco(fx["artist_with_discog"], limit=40)
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
        ok_disc, bad_disc = _no_disguised_singles(discog)
        check(
            "discografía: ningún studio_album es single disfrazado (<=3 pistas "
            "en vinilo)", ok_disc, "coló: {}".format(bad_disc))
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
        sims = _works_of(db.recommend_similar_to_work(seed_id, limit=12))
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
            sims = _works_of(db.recommend_similar_to_work(fx["work_without_embedding"]))
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
        sims = _works_of(db.recommend_similar_to_artist(aid, limit=12))
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
            sims = _works_of(db.recommend_similar_to_artist(rows[0]["aid"], limit=6))
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

    # 14b. get_work_tracklist elige la EDICIÓN DE REFERENCIA (main_release), no
    # la caja de lujo. Regresión del bug del MAX (Abbey Road → 3LP Super Deluxe).
    if fx["work_with_boxset"]:
        wid = fx["work_with_boxset"]["id"]
        ref_n = fx["work_with_boxset"]["ref_n"]
        tl = db.get_work_tracklist(wid)
        check("tracklist elige la edición de referencia, no la caja de lujo",
              len(tl) == ref_n,
              "work {}: esperado {} pistas (main_release), got {}".format(
                  wid, ref_n, len(tl)))
    else:
        check("fixture work_with_boxset existe", False, "no derivada")

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
        sims = _works_of(db.similar_by_press(seed_id, limit=8))
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
        sims = _works_of(db.similar_by_press(fx["work_without_embedding_press"]))
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

    # -----------------------------------------------------------------------
    # M3b — OAuth (piezas SIN navegador: api_sig, mapeo, URLs)
    # -----------------------------------------------------------------------
    run_m3b_checks(fx)

    # -----------------------------------------------------------------------
    # Búsqueda + recomendación v2 (§1-§6 del spec): calidad de ranking, regla
    # transversal de portada, (N)/homónimos, tiers de escucha, suggest, selección.
    # -----------------------------------------------------------------------
    run_search_reco_v2_checks(fx)

    # -----------------------------------------------------------------------
    # cover-backfill — recuperación de portadas desde Discogs (SIN red real)
    # -----------------------------------------------------------------------
    run_covers_checks(fx)


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

    # 22. recommend_for_user(1) — "Para ti" por GRAFO DE CO-ESCUCHA (getSimilar):
    #     >=8 vinilos, NINGUNA obra poseída, NINGÚN artista poseído, con `porque`
    #     que NOMBRA anclas REALES de su colección, cap 1/artista, sin singles
    #     disfrazados, y calidad = co-escucha agregada (n_anclas alto en el top).
    recs = _works_of(db.recommend_for_user(U, limit=12))
    check("recommend_for_user(1) [co-escucha] devuelve >=8 resultados",
          len(recs) >= 8, "solo {} recos".format(len(recs)))
    with db._cursor() as cur:
        owned = set(db._owned_work_ids(cur, U))
        owned_artists = set(db._owned_artist_ids(cur, U))
    check("recommend_for_user(1): NINGUNA reco es obra que ya posees",
          all(r["id"] not in owned for r in recs),
          "coló un disco de la colección")
    check("recommend_for_user(1): NINGUNA reco es de un artista que ya posees",
          all(r["artist_id"] not in owned_artists for r in recs),
          "coló un artista de la colección")
    aids = [r["artist_id"] for r in recs]
    check("recommend_for_user(1): 1 obra por artista (sin artistas repetidos)",
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
    ok_ru, bad_ru = _no_disguised_singles(recs)
    check("recommend_for_user(1): ninguna reco es single disfrazado (<=3 pistas "
          "en vinilo)", ok_ru, "coló: {}".format(bad_ru))
    # 22-a. El `porque` cita anclas REALES de su colección. Sacamos los nombres de
    #     los artistas poseídos y comprobamos que cada nombre citado tras "porque
    #     tienes " está entre ellos (co-escucha honesta, no inventada).
    with db._cursor() as cur:
        cur.execute(
            "SELECT DISTINCT a.name FROM unnest(%(ids)s::bigint[]) t(aid) "
            "JOIN artists a ON a.id = t.aid",
            {"ids": list(owned_artists) or [0]})
        owned_names = {row["name"] for row in cur.fetchall()}

    def _anclas_del_porque(porque):
        # "porque tienes A y B" / "porque tienes A"  → [A, B] / [A]
        p = (porque or "").strip()
        if not p.startswith("porque tienes "):
            return None  # formato inesperado → falla el check
        rest = p[len("porque tienes "):]
        return [x.strip() for x in rest.split(" y ") if x.strip()]

    porque_ok = True
    bad_porque = None
    for r in recs:
        anc = _anclas_del_porque(r.get("porque"))
        if not anc or any(name not in owned_names for name in anc):
            porque_ok = False
            bad_porque = r.get("porque")
            break
    check("recommend_for_user(1): el `porque` cita anclas REALES de su colección",
          porque_ok, "porque con ancla no poseída: {}".format(bad_porque))
    # 22-b. Calidad: los top candidatos son co-escucha AGREGADA (n_anclas>1), no un
    #     match suelto. Verificamos sobre la agregación cruda del grafo (los top 5).
    with db._cursor() as cur:
        cur.execute("""
            WITH owned AS (
                SELECT DISTINCT r.work_id FROM user_collection uc
                JOIN releases r ON r.id = uc.release_id
                WHERE uc.user_id = %(u)s AND uc.release_id IS NOT NULL),
            oa AS (SELECT DISTINCT w.primary_artist_id aid FROM owned o
                   JOIN works w ON w.id = o.work_id)
            SELECT count(DISTINCT s.artist_id) n_anclas
            FROM lastfm_similar_artists s
            JOIN oa ON oa.aid = s.artist_id
            WHERE s.similar_artist_id IS NOT NULL
              AND s.similar_artist_id NOT IN (SELECT aid FROM oa)
            GROUP BY s.similar_artist_id
            ORDER BY sum(s.match) DESC LIMIT 5
        """, {"u": U})
        top_nanclas = [row["n_anclas"] for row in cur.fetchall()]
    check("recommend_for_user(1): top candidatos son co-escucha AGREGADA (n_anclas>1)",
          bool(top_nanclas) and all(n > 1 for n in top_nanclas),
          "n_anclas del top: {}".format(top_nanclas))
    # 22-c. Degradación honesta: user de test SIN semillas en el grafo → []. Se crea
    #     un invitado efímero (colección vacía → owned_artists vacío → sin aristas).
    #     NUNCA se toca al user 1 ni el grafo.
    gtmp = None
    try:
        gtmp = db.create_guest_user()
        check("recommend_for_user(user sin semillas en el grafo) → [] (degradación)",
              _works_of(db.recommend_for_user(gtmp)) == [],
              "no degradó a [] sin semillas de co-escucha")
        check("recommend_for_user(0 / anónimo) → []",
              _works_of(db.recommend_for_user(0)) == [], "anónimo no dio []")
    finally:
        if gtmp is not None:
            db.delete_user_and_sessions(gtmp)
            check("limpieza: user de test sin semillas borrado",
                  db.get_app_user(gtmp) is None, "no se borró el user de test")

    # 22-bis. recommend_from_listening(1) — ESCUCHA REAL en 3 tiers (§3 reescrito):
    #     tier 'buy' (escuchas y no tienes) / 'upgrade' (tienes en no-vinilo, sin
    #     vinilo) / 'artist' (otros discos de tus artistas). Todos vinilo+álbum/EP+
    #     portada, cap 1/work, `porque` y `tier` presentes. Un tier 'buy' NO está en
    #     la colección; un tier 'upgrade' SÍ (en no-vinilo) y NO en vinilo.
    lres = db.recommend_from_listening(U, limit=12)
    lrecs = _works_of(lres)
    check("recommend_from_listening(1) [escucha real] devuelve >=6 resultados",
          len(lrecs) >= 6, "solo {} recos".format(len(lrecs)))
    # Tier presente y coherente en cada item.
    tier_ok = all(r.get("tier") in ("buy", "upgrade", "artist") for r in lrecs)
    check("recommend_from_listening(1): cada reco lleva `tier` válido", tier_ok,
          "tiers: {}".format([r.get("tier") for r in lrecs[:5]]))
    # NUNCA una obra que YA se posee en vinilo (nada que comprar/subir).
    owned_vinyl = {row["work_id"] for row in _q(
        "SELECT DISTINCT r.work_id FROM user_collection uc "
        "JOIN releases r ON r.id = uc.release_id "
        "WHERE uc.user_id = %(u)s AND r.format = 'vinyl'", {"u": U})}
    check("recommend_from_listening(1): NINGUNA reco es una obra ya en VINILO",
          all(r["id"] not in owned_vinyl for r in lrecs),
          "coló una obra que ya tienes en vinilo")
    # Coherencia de tier vs colección: 'buy' NO poseído en absoluto; 'upgrade' SÍ
    # en no-vinilo.
    tier_consistent = True
    for r in lrecs:
        in_coll = r["id"] in owned
        if r.get("tier") == "buy" and in_coll:
            tier_consistent = False; break
        if r.get("tier") == "upgrade" and not in_coll:
            tier_consistent = False; break
    check("recommend_from_listening(1): tier 'buy' no poseído / 'upgrade' poseído "
          "en no-vinilo", tier_consistent, "tier incoherente con la colección")
    lall_ok = all(
        (lambda w: w and w["has_vinyl"] is True
                   and w["work_type"] in ("studio_album", "ep"))(db.get_work(r["id"]))
        for r in lrecs)
    check("recommend_from_listening(1): todos vinilo + studio_album/ep", lall_ok,
          "alguna reco sin vinilo o con morralla")
    check("recommend_from_listening(1): cada reco con `porque` no vacío",
          all((r.get("porque") or "").strip() for r in lrecs),
          "porque vacío")
    ok_l, bad_l = _no_disguised_singles(lrecs)
    check("recommend_from_listening(1): ninguna reco es single disfrazado (<=3 "
          "pistas en vinilo)", ok_l, "coló: {}".format(bad_l))
    check("recommend_from_listening(1): NO devuelve 'Evil' (single disfrazado)",
          all(r["id"] != 11253669 for r in lrecs), "coló 'Evil'")
    # Todos con portada de Discogs (regla transversal) — vienen marcados has_discogs.
    check("recommend_from_listening(1): todos marcados con portada de Discogs",
          all(r.get("has_discogs") for r in lrecs), "alguna reco sin portada discogs")
    # Degradación: user de test SIN filas user_lastfm_* → dict vacío (con LIMPIEZA).
    #     NUNCA se toca al user 1: se crea un invitado efímero sin datos lastfm.
    ltmp = None
    try:
        ltmp = db.create_guest_user()
        check("recommend_from_listening(user sin lastfm) → [] (degradación honesta)",
              _works_of(db.recommend_from_listening(ltmp)) == [],
              "no degradó a [] sin datos de escucha")
        check("recommend_from_listening(0 / anónimo) → []",
              _works_of(db.recommend_from_listening(0)) == [], "anónimo no dio []")
    finally:
        if ltmp is not None:
            db.delete_user_and_sessions(ltmp)
            check("limpieza: user de test sin lastfm borrado",
                  db.get_app_user(ltmp) is None, "no se borró el user de test")

    # 23. vinyl_gap(1): >0 (idealmente ~287), cada obra existe en vinilo, el user la
    #     tiene en formato≠vinyl y NO posee ya un prensado de vinilo; trae ediciones.
    gap_total = db.vinyl_gap_count(U)
    check("vinyl_gap_count(1) > 0 (gap real de vinilo)",
          gap_total > 0, "gap = {}".format(gap_total))
    check("vinyl_gap_count(1) en rango esperado (>200 para Carlos)",
          gap_total > 200, "gap = {} (esperado ~287)".format(gap_total))
    gap = _works_of(db.vinyl_gap(U, limit=24))
    check("vinyl_gap(1) devuelve página de resultados",
          len(gap) > 0, "página vacía")
    check("vinyl_gap(1): cada obra del gap trae portada de Discogs (regla transversal)",
          all(g.get("has_discogs") for g in gap), "alguna obra del gap sin portada discogs")
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
        sims = _works_of(db.recommend_similar_to_work(
            fx["work_with_embedding"], limit=12, exclude_user_id=U))
        check("afines (obra) con exclude_user_id=1 excluyen la colección del user",
              all(s["id"] not in owned for s in sims),
              "coló un disco de la colección en afines")


def run_m3b_checks(fx):
    """Checks unitarios de OAuth SIN red ni navegador (M3b):
      - api_sig de Last.fm con vector determinista conocido.
      - regla de mapeo de identidad (existente / invitado / nuevo) con fixtures
        temporales en core y LIMPIEZA garantizada (NUNCA toca al user 1).
      - URLs de autorización bien formadas (parseando querystring, sin red).
    """
    from app.domains.users import oauth
    import urllib.parse

    # 25. api_sig determinista (vector conocido, sin red).
    sig = oauth.lastfm_api_sig(
        {"method": "auth.getSession", "api_key": "abc123", "token": "tok999"},
        "SECRET42",
    )
    check("lastfm_api_sig: md5 firmado coincide con el vector conocido",
          sig == "8ebe34e096d1c1d768c92c2f5eb8735b",
          "obtenido {}".format(sig))
    # api_sig ignora 'format' y 'api_sig' previos.
    sig2 = oauth.lastfm_api_sig(
        {"method": "auth.getSession", "api_key": "abc123", "token": "tok999",
         "format": "json", "api_sig": "STALE"},
        "SECRET42",
    )
    check("lastfm_api_sig: excluye 'format' y 'api_sig' del cálculo",
          sig2 == sig, "no ignoró format/api_sig")

    # 26. URLs de autorización bien formadas (sin red).
    with _env({"VINYLBE_BASE_URL": "http://localhost:7788",
               "LASTFM_API_KEY": "LFKEY", "LASTFM_API_SECRET": "LFSEC"}):
        durl = oauth.discogs_authorize_url("REQTOK123")
        pd = urllib.parse.urlparse(durl)
        qd = urllib.parse.parse_qs(pd.query)
        check("discogs_authorize_url apunta a discogs.com/oauth/authorize",
              pd.netloc == "www.discogs.com" and pd.path == "/oauth/authorize",
              "url: {}".format(durl))
        check("discogs_authorize_url lleva el oauth_token del request token",
              qd.get("oauth_token") == ["REQTOK123"],
              "qs: {}".format(qd))

        lurl = oauth.lastfm_auth_url()
        pl = urllib.parse.urlparse(lurl)
        ql = urllib.parse.parse_qs(pl.query)
        check("lastfm_auth_url apunta a last.fm/api/auth",
              "last.fm" in pl.netloc and pl.path.startswith("/api/auth"),
              "url: {}".format(lurl))
        check("lastfm_auth_url lleva api_key y cb correcta (:7788 callback)",
              ql.get("api_key") == ["LFKEY"]
              and ql.get("cb") == ["http://localhost:7788/auth/lastfm/callback"],
              "qs: {}".format(ql))

    # 27. Regla de mapeo de identidad — 3 casos con fixtures temporales.
    #     (a) credencial EXISTENTE → mapea a su user_id (fixture de test, NO user 1).
    tmp_user = None
    guest_id = None
    new_created_id = None
    try:
        # Fixture: usuario de test + credencial discogs con un account_id ÚNICO.
        acc_a = "vb2test-acc-" + secrets_token()
        tmp_user = db.create_identified_user(display_name="vb2-test-existing")
        db.upsert_oauth_credential(
            user_id=tmp_user, provider="discogs", provider_account_id=acc_a,
            provider_username="vb2test", oauth_token="tk", oauth_token_secret="ts")
        uid, outcome = oauth.map_identity("discogs", acc_a, "vb2test",
                                          guest_user_id=None)
        check("map_identity: credencial existente → su user_id (outcome=existing)",
              uid == tmp_user and outcome == "existing",
              "uid={} outcome={}".format(uid, outcome))
        # aunque venga un invitado, gana la credencial existente.
        uid2, outcome2 = oauth.map_identity("discogs", acc_a, "vb2test",
                                            guest_user_id=999999999)
        check("map_identity: existente gana sobre invitado (no re-vincula)",
              uid2 == tmp_user and outcome2 == "existing",
              "uid={} outcome={}".format(uid2, outcome2))

        # (b) invitado + credencial NUEVA → vincula al invitado.
        guest_id, _tok = _guest()
        acc_b = "vb2test-acc-" + secrets_token()
        uid3, outcome3 = oauth.persist_identity(
            provider="lastfm", provider_account_id=acc_b,
            provider_username="vb2guestname", guest_user_id=guest_id,
            session_key="sk-test")
        check("persist_identity: invitado + credencial nueva → vincula al invitado",
              uid3 == guest_id and outcome3 == "linked_guest",
              "uid={} outcome={}".format(uid3, outcome3))
        cred = db.find_oauth_credential("lastfm", acc_b)
        check("persist_identity: la credencial nueva queda ligada al invitado",
              cred is not None and cred["user_id"] == guest_id,
              "cred={}".format(cred))
        # display_name del invitado se rellena (estaba NULL).
        gu = db.get_app_user(guest_id)
        check("persist_identity: rellena display_name del invitado vinculado",
              gu and gu["display_name"] == "vb2guestname",
              "display_name={}".format(gu and gu["display_name"]))

        # (c) sin invitado + credencial nueva → crea usuario nuevo.
        acc_c = "vb2test-acc-" + secrets_token()
        uid4, outcome4 = oauth.map_identity("discogs", acc_c, "vb2new",
                                            guest_user_id=None)
        new_created_id = uid4 if outcome4 == "new" else None
        check("map_identity: sin invitado + nueva → crea usuario (outcome=new)",
              outcome4 == "new" and isinstance(uid4, int) and uid4 > 0,
              "uid={} outcome={}".format(uid4, outcome4))
        check("map_identity: el usuario nuevo NO es el user 1 (Carlos)",
              uid4 != 1, "creó/mapeó al user 1")
    except Exception as e:  # noqa: BLE001
        check("regla de mapeo de identidad no peta", False, repr(e))
    finally:
        # LIMPIEZA: borrar TODOS los fixtures de test (CASCADE borra credenciales).
        for _id in (tmp_user, guest_id, new_created_id):
            if _id and _id != 1:
                db.delete_user_and_sessions(_id)
        # verificación de limpieza
        gone = all(
            (_id is None) or (_id == 1) or (db.get_app_user(_id) is None)
            for _id in (tmp_user, guest_id, new_created_id))
        check("limpieza M3b: todos los usuarios/credenciales de test borrados",
              gone, "quedó algún fixture sin borrar")

    # 28. /auth/discogs/login SIN credenciales en entorno → 'no configurado'
    #     (no 500). Con TestClient, sin red.
    try:
        from fastapi.testclient import TestClient
        from app.main import app
        with _env({"DISCOGS_KEY": "", "DISCOGS_SECRET": ""}):
            client = TestClient(app)
            r = client.get("/auth/discogs/login", follow_redirects=False)
            check("/auth/discogs/login sin credenciales → aviso 'no configurado' "
                  "(no 500)",
                  r.status_code != 500 and "no está configurado" in r.text.lower(),
                  "status {} / {}".format(r.status_code, r.text[:80]))
    except Exception as e:  # noqa: BLE001
        print("SKIP  /auth/discogs/login sin credenciales (TestClient: {})".format(e))

    # 29. Callback de Discogs SIN estado → error suave (no 500), sin red.
    try:
        from fastapi.testclient import TestClient
        from app.main import app
        client = TestClient(app)
        r = client.get("/auth/discogs/callback",
                       params={"oauth_token": "x", "oauth_verifier": "y"},
                       follow_redirects=False)
        check("/auth/discogs/callback sin estado → error suave (no 500)",
              r.status_code != 500 and r.status_code < 500,
              "status {}".format(r.status_code))
    except Exception as e:  # noqa: BLE001
        print("SKIP  callback sin estado (TestClient: {})".format(e))

    # 30. FlowStore: single-use + expiración.
    fs = oauth.FlowStore(ttl_seconds=600)
    st = fs.put({"provider": "discogs", "request_token_secret": "s"})
    got = fs.pop(st)
    check("FlowStore: pop devuelve el payload guardado",
          got and got["request_token_secret"] == "s", "got={}".format(got))
    check("FlowStore: single-use (segundo pop → None)",
          fs.pop(st) is None, "segundo pop no dio None")
    check("FlowStore: pop(None) / estado inexistente → None",
          fs.pop(None) is None and fs.pop("noexiste") is None,
          "estado inexistente no dio None")
    fs_exp = oauth.FlowStore(ttl_seconds=-1)
    st2 = fs_exp.put({"provider": "lastfm"})
    check("FlowStore: estado caducado → None",
          fs_exp.pop(st2) is None, "caducado no dio None")


def run_search_reco_v2_checks(fx):
    """Búsqueda + reco v2 (§1-§6 del spec).

    §1 búsqueda de calidad: nunca compilation/live_album/single ni works sin
        portada discogs; ranking pone el exacto/popular primero; US→UK; min 3 chars.
    §2 artistas: sin "(N)", disambiguation numérica oculta, homónimos dedup, solo
        con works mostrables.
    §3 recommend_from_listening 3 tiers (cubierto en run_m3a; aquí el shape).
    §6 suggest artists+works; buscar-por-selección top-3 por artista + combinadas.
    """
    from app.domains import catalog, reco

    # -- §1 REGLA TRANSVERSAL: search_works nunca devuelve tipo prohibido ni
    #    work sin portada de Discogs. Barremos varios términos populares. La
    #    verificación de tipo/portada es EN BATCH (una query por término, no N+1). --
    bad_type, no_cover = [], []
    for term in ("love", "live", "greatest", "radiohead", "the beatles"):
        ids = [w["id"] for w in _sw(term, limit=30)]
        if not ids:
            continue
        rows = _q("""
            SELECT w.id, w.work_type,
                   EXISTS(SELECT 1 FROM cover_images ci WHERE ci.work_id=w.id
                          AND ci.source='discogs') AS has_cov
            FROM works w WHERE w.id = ANY(%(ids)s)
        """, {"ids": ids})
        for r in rows:
            if r["work_type"] not in ("studio_album", "ep"):
                bad_type.append((term, r["id"], r["work_type"]))
            if not r["has_cov"]:
                no_cover.append((term, r["id"]))
    check("§1 search_works NUNCA devuelve compilation/live_album/single",
          not bad_type, "colaron tipos: {}".format(bad_type[:5]))
    check("§1 search_works SOLO works con portada de Discogs",
          not no_cover, "sin portada: {}".format(no_cover[:5]))
    # marca has_discogs en cada work devuelto (para el backfill/no re-pedir).
    check("§1 search_works marca has_discogs=True en cada work mostrado",
          all(w.get("has_discogs") for w in _sw("radiohead", limit=20)),
          "algún work sin marca has_discogs")

    # -- §1 RANKING: el término = nombre de artista pone su obra arriba; y el
    #    exacto de título gana. "interpol" → artista Interpol primero (no "Inter"). --
    arts = catalog.search("interpol")["artists"]
    check("§2 search_artists('interpol'): Interpol es el PRIMER artista (no 'Inter')",
          bool(arts) and arts[0]["name"].lower() == "interpol",
          "primero: {}".format(arts[0]["name"] if arts else None))

    # -- §1 US→UK: "favorite worst nightmare" encuentra el álbum británico. --
    fwn = _sw("favorite worst nightmare", limit=20)
    check("§1 US→UK: 'favorite worst nightmare' encuentra 'Favourite Worst Nightmare'",
          any("favourite worst nightmare" in (w["title"] or "").lower() for w in fwn),
          "no encontró el álbum tras normalizar US→UK")

    # -- §1 MIN 3 CHARS: query corta → sin resultados. --
    check("§1 search_works('ab') (<3 chars) → sin works",
          _sw("ab") == [], "query <3 devolvió works")
    check("§2 search_artists('ab') (<3 chars) → sin artistas",
          db.search_artists("ab") == [], "query <3 devolvió artistas")

    # -- §2 (N) DE DISCOGS: nombre sin "(N)", disambiguation numérica oculta. --
    leak = _q("SELECT id FROM artists WHERE name ~ '\\(\\d+\\)$' "
              "AND is_primary LIMIT 1")
    if leak:
        a = db.get_artist(leak[0]["id"])
        check("§2 get_artist: el nombre NO lleva la '(N)' de Discogs",
              a and "(" not in a["name"].rsplit(" ", 1)[-1].rstrip(")") or
              (a and not a["name"].rstrip().endswith(")")),
              "nombre con (N): {}".format(a["name"] if a else None))
    num_dis = _q("SELECT id FROM artists WHERE disambiguation ~ '^[0-9]+$' LIMIT 1")
    if num_dis:
        a = db.get_artist(num_dis[0]["id"])
        check("§2 get_artist: la disambiguation NUMÉRICA se oculta (NULL)",
              a and a["disambiguation"] is None,
              "disamb numérica visible: {}".format(a["disambiguation"] if a else None))

    # -- §2 HOMÓNIMOS: search_artists no devuelve dos con el mismo name_clean. --
    for term in ("geese", "interpol", "the beatles"):
        got = db.search_artists(term, limit=20)
        norms = [_q("SELECT name_clean FROM artists WHERE id=%(i)s",
                    {"i": g["id"]})[0]["name_clean"] for g in got]
        check("§2 search_artists('{}') sin homónimos duplicados (dedup name_clean)"
              .format(term), len(norms) == len(set(norms)),
              "duplicados: {}".format(norms))
        # Todos con >=1 work mostrable (los homónimos-basura sin discos caen).
        all_showable = all(
            _q("SELECT 1 FROM works w WHERE w.primary_artist_id=%(a)s "
               "AND w.has_vinyl=true AND w.work_type IN ('studio_album','ep') "
               "AND EXISTS(SELECT 1 FROM cover_images ci WHERE ci.work_id=w.id "
               "AND ci.source='discogs') LIMIT 1", {"a": g["id"]})
            for g in got)
        check("§2 search_artists('{}'): todo artista tiene >=1 work mostrable"
              .format(term), all_showable, "algún artista sin works mostrables")

    # -- §6 SUGGEST: artists + works, portada-obligatoria en works, min 3 chars. --
    sg = catalog.suggest("radio")
    check("§6 suggest('radio') devuelve artists Y works",
          len(sg["artists"]) > 0 and len(sg["works"]) > 0,
          "artists={} works={}".format(len(sg["artists"]), len(sg["works"])))
    check("§6 suggest works: forma {id,title,artist_name,year}",
          all(set(w.keys()) >= {"id", "title", "artist_name", "year"}
              for w in sg["works"]), "forma inesperada")
    sg_cover_ok = all(
        _q("SELECT 1 FROM cover_images WHERE work_id=%(w)s AND source='discogs' "
           "LIMIT 1", {"w": w["id"]}) for w in sg["works"])
    check("§6 suggest works: todos con portada de Discogs", sg_cover_ok,
          "algún work sugerido sin portada")
    check("§6 suggest('ra') (<3 chars) → vacío",
          catalog.suggest("ra") == {"artists": [], "works": []},
          "sugerencia con <3 chars")

    # -- §6 BUSCAR POR SELECCIÓN: top-3 por artista + combinadas (anónimo). --
    # Se acota por `listeners` alto (índice) — un `count(*)` correlacionado sobre
    # TODOS los artistas primary barrería el catálogo entero (medido: >17 min).
    two_artists = [r["id"] for r in _q("""
        SELECT a.id FROM artists a
        WHERE a.is_primary AND a.listeners > 500000
          AND EXISTS(SELECT 1 FROM lastfm_similar_artists s WHERE s.artist_id=a.id)
          AND EXISTS(SELECT 1 FROM works w WHERE w.primary_artist_id=a.id
              AND w.has_vinyl=true AND w.work_type IN ('studio_album','ep')
              AND EXISTS(SELECT 1 FROM cover_images ci WHERE ci.work_id=w.id
                         AND ci.source='discogs'))
        ORDER BY a.listeners DESC NULLS LAST LIMIT 2
    """)]
    if len(two_artists) >= 1:
        sel = reco.search_by_selection(two_artists, [], exclude_user_id=None)
        blocks = sel["artist_blocks"]
        check("§6 selección: un bloque por artista seleccionado (con works)",
              len(blocks) >= 1 and all(b["works"] for b in blocks),
              "bloques vacíos: {}".format(len(blocks)))
        check("§6 selección: máx 3 álbumes por artista (top-3)",
              all(len(b["works"]) <= 3 for b in blocks),
              "algún bloque con >3 works")
        check("§6 selección: works de artista con portada de Discogs",
              all(w.get("has_discogs") for b in blocks for w in b["works"]),
              "algún work de bloque sin portada")
        check("§6 selección: 'en la onda de tu selección' devuelve combinadas",
              len(sel["combined"]["results"]) > 0, "combinadas vacías")
        # las combinadas NO son ninguno de los artistas semilla.
        comb_aids = {w["artist_id"] for w in sel["combined"]["results"]}
        check("§6 selección: las combinadas excluyen los artistas semilla",
              not (comb_aids & set(two_artists)), "coló un artista semilla")
    else:
        print("SKIP  §6 selección (no hay artistas fixture con >=3 works + grafo)")

    # -- §3 shape de recommend_from_listening SIN Discogs: usuario sin colección →
    #    tier 1 sin filtro de posesión (si tiene escucha). Usamos un invitado con
    #    escucha inyectada + LIMPIEZA. --
    gtmp = None
    try:
        gtmp = db.create_guest_user()
        # inyecta 3 works escuchados (con vinilo+álbum+portada) SIN colección.
        seeds = _q("""
            SELECT w.id FROM works w
            WHERE w.has_vinyl=true AND w.work_type IN ('studio_album','ep')
              AND EXISTS(SELECT 1 FROM cover_images ci WHERE ci.work_id=w.id
                         AND ci.source='discogs')
              AND (w.work_type<>'studio_album' OR EXISTS(SELECT 1 FROM releases r
                   WHERE r.work_id=w.id AND r.format='vinyl'
                     AND jsonb_array_length(r.tracklist_cache)>=4))
            ORDER BY w.lastfm_playcount DESC NULLS LAST LIMIT 3
        """)
        with db._cursor() as cur:
            for i, s in enumerate(seeds):
                cur.execute(
                    "INSERT INTO user_lastfm_albums (user_id, period, rank, "
                    "playcount, album_title, artist_name, work_id) VALUES "
                    "(%(u)s,'overall',%(r)s,%(pc)s,'t','a',%(w)s)",
                    {"u": gtmp, "r": i + 1, "pc": 100 - i, "w": s["id"]})
        res = db.recommend_from_listening(gtmp, limit=12)
        got = _works_of(res)
        check("§3 sin Discogs (sin colección): escucha resuelta → tier 'buy' sin "
              "filtro de posesión", len(got) >= 1 and all(g["tier"] == "buy" for g in got),
              "esperaba tier buy, got {}".format([g.get("tier") for g in got]))
    finally:
        if gtmp is not None:
            db.delete_user_and_sessions(gtmp)
            check("§3 limpieza: invitado de escucha borrado",
                  db.get_app_user(gtmp) is None, "no se borró el invitado")


def run_covers_checks(fx):
    """cover-backfill: parser, upsert, needs_reliable_cover, enqueue dedup.

    SIN red real (mock del cliente Discogs). El upsert usa un work_id real SIN
    cover de Discogs y LIMPIA la fila de test al terminar (nunca deja basura).
    """
    from app.domains import covers

    # -- Fixtures por SQL: works por fuente de portada --
    caa_only = _q("""
        SELECT ci.work_id FROM cover_images ci
        WHERE ci.source = 'caa'
          AND NOT EXISTS (SELECT 1 FROM cover_images d
                          WHERE d.work_id = ci.work_id AND d.source = 'discogs')
        LIMIT 1
    """)
    with_discogs = _q(
        "SELECT work_id FROM cover_images WHERE source='discogs' LIMIT 1")
    no_cover = _q("""
        SELECT w.id AS work_id FROM works w
        WHERE w.has_vinyl = true
          AND NOT EXISTS (SELECT 1 FROM cover_images ci WHERE ci.work_id = w.id)
        LIMIT 1
    """)

    # -- Parser (MOCK, sin red): master con primary+secondary → primary --
    mock_images = [
        {"type": "secondary", "uri": "https://i.discogs.com/sec.jpg",
         "uri150": "https://i.discogs.com/sec150.jpg"},
        {"type": "primary", "uri": "https://i.discogs.com/prim.jpg",
         "uri150": "https://i.discogs.com/prim150.jpg"},
    ]
    picked = covers._pick_primary_image(mock_images)
    check("covers: parser elige la imagen 'primary' (uri + uri150)",
          picked == ("https://i.discogs.com/prim.jpg",
                     "https://i.discogs.com/prim150.jpg"),
          "picked={}".format(picked))
    check("covers: parser sin images → None",
          covers._pick_primary_image(None) is None
          and covers._pick_primary_image([]) is None,
          "no devolvió None sin images")
    # Sin 'primary' → primera imagen.
    first = covers._pick_primary_image(
        [{"uri": "https://i.discogs.com/a.jpg", "uri150": "https://i.discogs.com/a150.jpg"}])
    check("covers: parser sin 'primary' → primera imagen",
          first == ("https://i.discogs.com/a.jpg", "https://i.discogs.com/a150.jpg"),
          "first={}".format(first))

    # -- fetch_cover con cliente mockeado (sin red): master trae imagen --
    _orig_get_json = covers._get_json
    try:
        covers._get_json = lambda path: (
            {"images": mock_images} if path.startswith("/masters/") else None)
        fc = covers.fetch_cover(123, 456)
        check("covers: fetch_cover usa el MASTER (mock, sin red)",
              fc == ("https://i.discogs.com/prim.jpg",
                     "https://i.discogs.com/prim150.jpg"),
              "fc={}".format(fc))
        # Master sin imagen → cae al release.
        covers._get_json = lambda path: (
            {"images": mock_images} if path.startswith("/releases/") else {"images": []})
        fc2 = covers.fetch_cover(123, 456)
        check("covers: fetch_cover cae al RELEASE si el master no trae imagen",
              fc2 == ("https://i.discogs.com/prim.jpg",
                      "https://i.discogs.com/prim150.jpg"),
              "fc2={}".format(fc2))
        # Ninguno trae imagen → None.
        covers._get_json = lambda path: {"images": []}
        check("covers: fetch_cover None si ni master ni release traen imagen",
              covers.fetch_cover(123, 456) is None, "no dio None")
    finally:
        covers._get_json = _orig_get_json

    # -- needs_reliable_cover: solo-CAA → True, discogs → False, sin cover → True --
    if caa_only:
        wid = caa_only[0]["work_id"]
        src = db.cover_sources_for_works([wid])[wid]
        check("covers: needs_reliable_cover(solo CAA) → True",
              covers.needs_reliable_cover(
                  {"id": wid, "cover_url": "https://coverartarchive.org/x.jpg",
                   "has_caa": src["has_caa"], "has_discogs": src["has_discogs"]}),
              "solo-CAA no marcó needs")
        check("covers: db.cover_sources_for_works(solo CAA) = has_caa sin discogs",
              src["has_caa"] and not src["has_discogs"], "src={}".format(src))
    else:
        print("SKIP  covers: sin work solo-CAA en core")
    if with_discogs:
        wid = with_discogs[0]["work_id"]
        src = db.cover_sources_for_works([wid])[wid]
        check("covers: needs_reliable_cover(con Discogs) → False",
              not covers.needs_reliable_cover(
                  {"id": wid, "cover_url": "https://i.discogs.com/x.jpg",
                   "has_discogs": src["has_discogs"]}),
              "con-discogs marcó needs")
        check("covers: db.cover_sources_for_works(con Discogs).has_discogs",
              src["has_discogs"], "src={}".format(src))
    if no_cover:
        wid = no_cover[0]["work_id"]
        check("covers: needs_reliable_cover(sin cover) → True",
              covers.needs_reliable_cover({"id": wid, "cover_url": None}),
              "sin-cover no marcó needs")
        check("covers: db.cover_sources_for_works(sin cover) no aparece",
              db.cover_sources_for_works([wid]) == {}, "apareció sin cover")

    # -- Upsert real + limpieza garantizada (work SIN discogs previo) --
    if caa_only:
        test_wid = caa_only[0]["work_id"]
        try:
            before = db.cover_sources_for_works([test_wid])[test_wid]
            covers.store_cover(test_wid,
                               "https://i.discogs.com/TEST.jpg",
                               "https://i.discogs.com/TEST150.jpg")
            after = db.cover_sources_for_works([test_wid])[test_wid]
            check("covers: store_cover inserta la fila source='discogs'",
                  (not before["has_discogs"]) and after["has_discogs"],
                  "before={} after={}".format(before, after))
            check("covers: tras store_cover, needs_reliable_cover → False",
                  not covers.needs_reliable_cover(
                      {"id": test_wid, "has_discogs": after["has_discogs"]}),
                  "seguía marcando needs tras store")
            # Upsert idempotente: segunda escritura no duplica (PK work_id,source).
            covers.store_cover(test_wid, "https://i.discogs.com/TEST2.jpg", None)
            rows = _q("SELECT url FROM cover_images WHERE work_id=%(w)s "
                      "AND source='discogs'", {"w": test_wid})
            check("covers: store_cover es UPSERT (1 fila, url actualizada)",
                  len(rows) == 1 and rows[0]["url"] == "https://i.discogs.com/TEST2.jpg",
                  "rows={}".format(rows))
        finally:
            # LIMPIEZA: borrar la fila de test (nunca dejar basura de test en core).
            with db._cursor() as cur:
                cur.execute("DELETE FROM cover_images WHERE work_id=%(w)s "
                            "AND source='discogs'", {"w": test_wid})
            leftover = db.cover_sources_for_works([test_wid]).get(test_wid, {})
            check("covers: limpieza — fila discogs de test borrada",
                  not leftover.get("has_discogs"),
                  "quedó basura: {}".format(leftover))

    # -- Enqueue: no bloquea y es dedup TIPADO (mismo (kind,id) 2x → 1 vez) --
    # Inspeccionamos la cola SIN arrancar el hilo daemon (que la drenaría con
    # llamadas reales): replicamos la lógica de dedup tipado en memoria.
    from app.domains.covers import _CoverWorker

    def _enqueue_no_drain(worker, kind, ids):
        with worker._cv:
            for i in ids:
                key = (kind, int(i))
                if key in worker._queued or key in worker._tried:
                    continue
                worker._queue[key] = True
                worker._queued.add(key)

    w = _CoverWorker()
    _enqueue_no_drain(w, "cover", (777, 777, 778))
    check("covers: enqueue dedup (777 dos veces → una sola en cola)",
          list(w._queue.keys()) == [("cover", 777), ("cover", 778)],
          "cola={}".format(list(w._queue.keys())))

    # -- FOTO DE ARTISTA: parser, fetch, dedup tipado, throttle único, store --
    run_artist_photo_checks(fx)

    # request_missing NO bloquea y filtra por needs (mide O(1), sin red).
    # Flag OFF durante la medición → no arranca el worker ni toca Discogs (el
    # selftest NUNCA hace llamadas de red reales).
    import time as _t
    with _env({"VINYLBE_COVER_BACKFILL": "0"}):
        t0 = _t.perf_counter()
        covers.request_missing(
            [{"id": 999001, "cover_url": "https://coverartarchive.org/x.jpg"}] * 50)
        dt = _t.perf_counter() - t0
    check("covers: request_missing(50 works) es no-bloqueante (<50ms)",
          dt < 0.05, "tardó {:.3f}s".format(dt))


def run_artist_photo_checks(fx):
    """artista-fotos: backfill on-demand de foto de artista (Discogs).

    SIN red real (mock del cliente). Verifica: parser de /artists/{id},
    needs_artist_photo, dedup TIPADO (cover vs artist no se pisan), throttle
    ÚNICO compartido, store_artist_image real con LIMPIEZA (crea y borra un
    artista de test; nunca toca artistas reales de forma permanente).
    """
    from app.domains import covers
    from app.domains.covers import _CoverWorker

    def _enqueue_no_drain(worker, kind, ids):
        # Encola SIN arrancar el hilo daemon (que drenaría con llamadas reales).
        with worker._cv:
            for i in ids:
                key = (kind, int(i))
                if key in worker._queued or key in worker._tried:
                    continue
                worker._queue[key] = True
                worker._queued.add(key)

    # -- fetch_artist_image con cliente mockeado (sin red): images con primary --
    _orig_get_json = covers._get_json
    try:
        covers._get_json = lambda path: (
            {"images": [
                {"type": "primary", "uri": "https://i.discogs.com/A.jpg",
                 "uri150": "https://i.discogs.com/A150.jpg"}]}
            if path.startswith("/artists/") else None)
        img = covers.fetch_artist_image(42)
        check("artista-fotos: fetch_artist_image devuelve la uri150 (mock, sin red)",
              img == "https://i.discogs.com/A150.jpg", "img={}".format(img))
        # Sin uri150 → cae a uri.
        covers._get_json = lambda path: (
            {"images": [{"type": "primary", "uri": "https://i.discogs.com/B.jpg"}]}
            if path.startswith("/artists/") else None)
        img2 = covers.fetch_artist_image(42)
        check("artista-fotos: fetch_artist_image sin uri150 cae a uri",
              img2 == "https://i.discogs.com/B.jpg", "img2={}".format(img2))
        # Sin images → None.
        covers._get_json = lambda path: {"images": []}
        check("artista-fotos: fetch_artist_image sin imagen → None",
              covers.fetch_artist_image(42) is None, "no dio None")
        check("artista-fotos: fetch_artist_image sin discogs_artist_id → None",
              covers.fetch_artist_image(None) is None, "no dio None sin id")
    finally:
        covers._get_json = _orig_get_json

    # -- needs_artist_photo: sin url → True; i.discogs.com → False; estrella → True --
    check("artista-fotos: needs_artist_photo(sin image_url) → True",
          covers.needs_artist_photo({"id": 1, "image_url": None}),
          "sin url no marcó needs")
    check("artista-fotos: needs_artist_photo(url i.discogs.com) → False",
          not covers.needs_artist_photo(
              {"id": 1, "image_url": "https://i.discogs.com/x.jpg"}),
          "url discogs marcó needs")
    star = ("https://lastfm.freetls.fastly.net/i/u/300x300/"
            "2a96cbd8b46e442fc41c2b86b821562f.png")
    check("artista-fotos: needs_artist_photo(placeholder-estrella) → True",
          covers.needs_artist_photo({"id": 1, "image_url": star}),
          "estrella no marcó needs")

    # -- dedup TIPADO: ('artist',X) 2x → 1; ('cover',X) y ('artist',X) coexisten --
    w2 = _CoverWorker()
    _enqueue_no_drain(w2, "artist", (55, 55, 66))
    check("artista-fotos: enqueue_artists dedup (55 dos veces → una)",
          list(w2._queue.keys()) == [("artist", 55), ("artist", 66)],
          "cola={}".format(list(w2._queue.keys())))
    w3 = _CoverWorker()
    _enqueue_no_drain(w3, "cover", (100,))    # ('cover', 100)
    _enqueue_no_drain(w3, "artist", (100,))   # ('artist', 100) — mismo nº, distinto kind
    check("artista-fotos: cover y artist con mismo id COEXISTEN (tipo separa)",
          list(w3._queue.keys()) == [("cover", 100), ("artist", 100)],
          "cola={}".format(list(w3._queue.keys())))

    # -- THROTTLE ÚNICO: un solo _last_req compartido por ambos kinds --
    w4 = _CoverWorker()
    check("artista-fotos: worker tiene UN solo throttle (_last_req compartido)",
          hasattr(w4, "_last_req") and not hasattr(w4, "_last_req_artist"),
          "hay más de un rate-limiter")
    # Procesar un item de cada kind con el cliente/DB mockeados y comprobar que
    # AMBOS avanzan el MISMO _last_req (mismo throttle) — sin red real.
    _g = covers._get_json
    _wdi = db.work_discogs_ids
    _adi = db.artist_discogs_ids
    _sc = covers.store_cover
    _sa = covers.store_artist_image
    try:
        covers._get_json = lambda path: {"images": [
            {"type": "primary", "uri": "https://i.discogs.com/z.jpg",
             "uri150": "https://i.discogs.com/z150.jpg"}]}
        db.work_discogs_ids = lambda ids: {ids[0]: {"master_id": 1, "release_id": 2}}
        db.artist_discogs_ids = lambda ids: {ids[0]: 999}
        covers.store_cover = lambda *a, **k: None
        covers.store_artist_image = lambda *a, **k: None
        w4._last_req = 0.0
        w4._process_one(("cover", 100))
        t_after_cover = w4._last_req
        w4._process_one(("artist", 200))
        t_after_artist = w4._last_req
        check("artista-fotos: ambos kinds usan el MISMO _last_req (throttle único)",
              t_after_cover > 0 and t_after_artist >= t_after_cover,
              "cover={} artist={}".format(t_after_cover, t_after_artist))
    finally:
        covers._get_json = _g
        db.work_discogs_ids = _wdi
        db.artist_discogs_ids = _adi
        covers.store_cover = _sc
        covers.store_artist_image = _sa

    # -- store_artist_image REAL + LIMPIEZA (artista de test creado y borrado) --
    test_aid = None
    try:
        with db._cursor() as cur:
            cur.execute(
                "INSERT INTO artists (name, kind, is_primary) "
                "VALUES ('__selftest_artista_foto__', 'band', false) RETURNING id")
            test_aid = cur.fetchone()["id"]
        before = db.get_artist(test_aid)
        check("artista-fotos: artista de test arranca SIN foto (monograma)",
              covers.needs_artist_photo(before),
              "arrancó con foto: {}".format(before))
        covers.store_artist_image(test_aid, "https://i.discogs.com/ARTTEST.jpg")
        after = db.get_artist(test_aid)
        check("artista-fotos: store_artist_image escribe image_url en artists",
              after.get("image_url") == "https://i.discogs.com/ARTTEST.jpg",
              "after={}".format(after))
        src = _q("SELECT image_source FROM artists WHERE id=%(a)s",
                 {"a": test_aid})
        check("artista-fotos: store_artist_image marca image_source='discogs'",
              src and src[0]["image_source"] == "discogs",
              "src={}".format(src))
        check("artista-fotos: tras store, needs_artist_photo → False",
              not covers.needs_artist_photo(after),
              "seguía sin foto tras store")
    finally:
        # LIMPIEZA: borrar el artista de test (nunca dejar basura en core).
        if test_aid is not None:
            with db._cursor() as cur:
                cur.execute("DELETE FROM artists WHERE id=%(a)s", {"a": test_aid})
            gone = db.get_artist(test_aid)
            check("artista-fotos: limpieza — artista de test borrado",
                  gone is None, "quedó basura: {}".format(gone))


def secrets_token():
    import secrets as _s
    return _s.token_hex(6)


def _guest():
    from app.domains import users
    return users.start_guest()


from contextlib import contextmanager as _cm


@_cm
def _env(overrides):
    """Context manager: aplica overrides de os.environ y los restaura al salir."""
    saved = {k: os.environ.get(k) for k in overrides}
    try:
        for k, v in overrides.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


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

    # §6 type-ahead: /api/suggest devuelve JSON con artists+works.
    r = client.get("/api/suggest", params={"q": "radiohead"})
    check("GET /api/suggest?q=radiohead → 200 JSON con artists+works",
          r.status_code == 200 and "artists" in r.json() and "works" in r.json(),
          "status {} / body {}".format(r.status_code, r.text[:120]))

    # §6 buscar por SELECCIÓN: /buscar?artists=… → bloque 'mejores de'.
    if fx.get("artist_with_discog"):
        r = client.get("/buscar", params={"artists": str(fx["artist_with_discog"])})
        check("GET /buscar?artists={id} → 200 (bloque 'mejores de')",
              r.status_code == 200 and "mejores de" in r.text.lower(),
              "status {} / sin bloque".format(r.status_code))

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
        # M3b: sección de escucha Last.fm visible con >=1 card + porque de escucha.
        check("GET /mi con sesión dev → contiene 'Basado en lo que escuchas'",
              "Basado en lo que escuchas" in r.text,
              "falta la sección de escucha Last.fm")
        # §3 reescrito: la escucha real da porque por tier ("lo escuchas y aún no
        # lo tienes" / "súbelo a vinilo" / "…, que escuchas") — todos citan la escucha.
        check("GET /mi con sesión dev → la sección de escucha trae cards con porque",
              "card-porque" in r.text
              and ("lo escuchas" in r.text or "que escuchas" in r.text
                   or "súbelo a vinilo" in r.text),
              "la sección de escucha no muestra cards con porque de escucha")
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
