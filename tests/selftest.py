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

    if fx["work_top_vinyl"]:
        r = client.get("/obra/{}".format(fx["work_top_vinyl"]))
        check("GET /obra/{id} real → 200", r.status_code == 200,
              "status {}".format(r.status_code))

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
