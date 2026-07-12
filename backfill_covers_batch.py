"""
Batch de portadas Discogs — REUTILIZA la lógica PROBADA de app.domains.covers
(auth key/secret, master→release fallback) que sí recupera imágenes.

Pre-carga cover_images(source='discogs') para los works con vinilo más populares
sin portada. Resumible (el query excluye los que ya tienen). Rate-limit 1.2s.
Uso: (con .env cargado)  .venv/bin/python backfill_covers_batch.py [LIMIT]
"""
import sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app.domains.covers as cov
import app.db as db

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 200000
RATE_S = 1.2

def log(m): print(time.strftime("%H:%M:%S"), m, flush=True)

def main():
    with db._cursor() as cur:
        cur.execute("""
            SELECT w.id,
                   w.discogs_master_id,
                   (SELECT r.discogs_release_id FROM releases r
                     WHERE r.work_id=w.id AND r.discogs_release_id IS NOT NULL
                     ORDER BY (r.format='vinyl') DESC LIMIT 1) AS release_id
            FROM works w
            WHERE w.has_vinyl AND w.work_type IN ('studio_album','ep')
              AND w.discogs_master_id IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM cover_images c
                              WHERE c.work_id=w.id AND c.source='discogs')
            ORDER BY w.releases_count DESC NULLS LAST
            LIMIT %(lim)s
        """, {"lim": LIMIT})
        targets = cur.fetchall()
    log("objetivo: %d works sin portada (top por popularidad)" % len(targets))
    done = found = 0
    for row in targets:
        time.sleep(RATE_S)
        picked = cov.fetch_cover(row["discogs_master_id"], row["release_id"])
        done += 1
        if picked:
            try:
                db.store_cover_image(row["id"], "discogs", picked[0], picked[1])
                found += 1
            except Exception as e:
                log("fallo guardar %s: %s" % (row["id"], e))
        if done % 100 == 0:
            log("%d/%d — guardadas: %d" % (done, len(targets), found))
    log("FIN: %d procesados, %d portadas guardadas" % (done, found))

if __name__ == "__main__":
    main()
