import asyncio
import functools
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from libs.shared.models import ServiceHealth
from libs.shared.utils import log_event

from . import db_utils
from .album_aggregator import AlbumAggregator
from .artist_recommendations import (
    get_artist_based_recommendations,
    get_artist_studio_albums,
    get_top_albums_from_discogs_search,
    validate_album_with_discogs,
)
from .scoring_engine import ScoringEngine

SPOTIFY_SERVICE_URL = os.getenv("SPOTIFY_SERVICE_URL", "http://127.0.0.1:3005")
DISCOGS_SERVICE_URL = os.getenv("DISCOGS_SERVICE_URL", "http://127.0.0.1:3001")

scoring_engine = None
album_aggregator = None

progress_state = {
    "current": 0,
    "total": 0,
    "status": "idle",
    "current_artist": ""
}


class ArtistRecommendationRequest(BaseModel):
    artist_names: list[str]
    top_per_artist: int = 3


class CollectionPreferencesRequest(BaseModel):
    user_id: int
    focus_artists: list[str] = []
    strategies: list[str] = ["complete", "upgrade"] # complete, upgrade

class CollectionStatsRequest(BaseModel):
    user_id: int
    username: str

class RecommendationRequest(BaseModel):
    user_id: int
    limit: int = 10
    offset: int = 0
    username: str = None


class CollectionRecommendationRequest(BaseModel):
    username: str
    limit: int = 5


class MergeRecommendationsRequest(BaseModel):
    artist_recommendations: list[dict]
    lastfm_recommendations: list[dict] = []


class SingleArtistRequest(BaseModel):
    artist_name: str
    top_albums: int = 3
    csv_mode: bool = False
    cache_only: bool = False
    user_id: int | None = None
    preview: bool = False  # True = wizard pre-fetch: cache → Spotify (skip heavy Discogs call)



@asynccontextmanager
async def lifespan(app: FastAPI):
    global scoring_engine, album_aggregator
    scoring_engine = ScoringEngine()
    album_aggregator = AlbumAggregator()
    log_event("recommender-service", "INFO", "Recommendation Service started")
    yield
    log_event("recommender-service", "INFO", "Recommendation Service stopped")


app = FastAPI(lifespan=lifespan, title="Recommendation Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return ServiceHealth(
        service_name="recommender-service",
        status="healthy"
    ).dict()


@app.post("/lastfm-albums-recommendations")
async def lastfm_albums_recommendations(albums: list[dict]):
    """Simplified: user.gettopalbums → cache-first → fetch covers on-demand"""
    import asyncio
    import time
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    from . import db_utils

    start_time = time.time()
    log_event("recommender-service", "INFO", f"Processing {len(albums)} Last.fm albums")

    discogs_key = os.getenv("DISCOGS_KEY")
    discogs_secret = os.getenv("DISCOGS_SECRET")

    all_recommendations = []
    cache_hits = 0
    cache_misses = 0
    covers_fetched = 0

    def fetch_from_db(artist_name, album_name, mbid=None):
        """Run DB lookup in thread pool to avoid blocking"""
        return db_utils.get_cached_album(artist_name, album_name, mbid)

    async with httpx.AsyncClient(timeout=5.0) as client:
        with ThreadPoolExecutor(max_workers=3) as executor:
            loop = asyncio.get_event_loop()

            for album_data in albums[:50]:
                try:
                    album_name = album_data.get("name", "").strip()
                    mbid = album_data.get("mbid")
                    artist_data = album_data.get("artist", {})

                    if isinstance(artist_data, str):
                        artist_name = artist_data.strip()
                    else:
                        artist_name = artist_data.get("name", "").strip()

                    playcount = int(album_data.get("playcount", 0))

                    if not album_name or not artist_name:
                        continue

                    cached_album = await loop.run_in_executor(
                        executor, fetch_from_db, artist_name, album_name, mbid
                    )

                    if cached_album:
                        cache_hits += 1
                        all_recommendations.append({
                            "artist_name": artist_name,
                            "album_name": cached_album["title"],
                            "year": cached_album.get("year"),
                            "discogs_master_id": cached_album.get("discogs_master_id"),
                            "discogs_release_id": cached_album.get("discogs_release_id"),
                            "rating": cached_album.get("rating"),
                            "votes": cached_album.get("votes"),
                            "cover_url": cached_album.get("cover_url"),
                            "lastfm_playcount": playcount,
                            "source": "lastfm"
                        })
                    else:
                        cache_misses += 1

                        # Validate with Discogs instead of Spotify
                        try:
                            from .artist_recommendations import validate_album_with_discogs

                            discogs_album = await loop.run_in_executor(
                                executor, validate_album_with_discogs,
                                artist_name, album_name, discogs_key, discogs_secret
                            )

                            if discogs_album:
                                # Album is valid in Discogs, use its data
                                log_event("recommender-service", "INFO",
                                         f"✓ Validated with Discogs: {artist_name} - {album_name}")

                                # Save as partial record with Discogs IDs
                                await loop.run_in_executor(
                                    executor, db_utils.create_basic_album_entry,
                                    artist_name, discogs_album["title"], discogs_album["cover_image"],
                                    mbid, None, None,
                                    discogs_album["discogs_master_id"], discogs_album["discogs_release_id"]
                                )

                                all_recommendations.append({
                                    "artist_name": artist_name,
                                    "album_name": discogs_album["title"],
                                    "year": discogs_album["year"],
                                    "discogs_master_id": discogs_album["discogs_master_id"],
                                    "discogs_release_id": discogs_album["discogs_release_id"],
                                    "rating": None,
                                    "votes": None,
                                    "cover_url": discogs_album["cover_image"],
                                    "lastfm_playcount": playcount,
                                    "source": "lastfm",
                                    "is_partial": 1
                                })
                            else:
                                # Album not found or doesn't pass filters - SKIP IT
                                log_event("recommender-service", "INFO",
                                         f"✗ Skipped (not in Discogs or filtered): {artist_name} - {album_name}")
                        except Exception as e:
                            log_event("recommender-service", "WARNING",
                                     f"Discogs validation failed: {artist_name} - {album_name}: {str(e)}")

                except Exception as e:
                    log_event("recommender-service", "ERROR",
                             f"Album error: {str(e)}")
                    continue

    end_time = time.time()
    total_time = end_time - start_time

    log_event("recommender-service", "INFO",
              f"✓ {len(all_recommendations)} albums processed in {total_time:.2f}s "
              f"(hits: {cache_hits}, new: {cache_misses}, covers: {covers_fetched})")

    return {
        "albums": all_recommendations,
        "total": len(all_recommendations),
        "stats": {
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "covers_fetched": covers_fetched,
            "albums_processed": len(albums[:50]),
            "total_time_seconds": round(total_time, 2)
        }
    }


@app.post("/lastfm-recommendations")
async def lastfm_recommendations(artists: list[dict]):
    """
    LEGACY: Generate album recommendations from Last.fm artists using PostgreSQL cache
    Input: [{"name": "Artist Name", "score": 250.5, "playcount": 1234}, ...]
    """
    import time

    from . import artist_recommendations
    start_time = time.time()

    log_event("recommender-service", "INFO", f"Generating Last.fm recommendations for {len(artists)} artists")

    all_albums = []
    cache_hits = 0
    cache_misses = 0

    for artist in artists[:50]:
        artist_name = artist.get("name")
        lastfm_score = artist.get("score", 0)
        lastfm_playcount = artist.get("playcount", 0)

        if not artist_name:
            continue

        cached_albums = artist_recommendations._get_cached_artist_albums(artist_name)

        if cached_albums:
            cache_hits += 1
            for album in cached_albums[:2]:
                all_albums.append({
                    "artist_name": artist_name,
                    "album_name": album.get("title"),
                    "year": album.get("year"),
                    "discogs_master_id": album.get("discogs_master_id"),
                    "discogs_release_id": album.get("discogs_release_id"),
                    "rating": album.get("rating"),
                    "votes": album.get("votes"),
                    "cover_url": album.get("cover_url"),
                    "lastfm_score": lastfm_score,
                    "lastfm_playcount": lastfm_playcount,
                    "source": "lastfm"
                })
        else:
            cache_misses += 1

    end_time = time.time()
    total_time = end_time - start_time

    log_event("recommender-service", "INFO",
              f"Generated {len(all_albums)} Last.fm recommendations in {total_time:.2f}s "
              f"(cache hits: {cache_hits}, misses: {cache_misses})")

    return {
        "albums": all_albums,
        "total": len(all_albums),
        "stats": {
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "artists_processed": len(artists[:50]),
            "total_time_seconds": round(total_time, 2)
        }
    }


@app.post("/score-tracks")
async def score_tracks(tracks: list[dict]):
    import time
    start_time = time.time()

    if not scoring_engine:
        raise HTTPException(status_code=500, detail="Scoring engine not initialized")

    log_event("recommender-service", "INFO", f"Scoring {len(tracks)} tracks")

    scored_tracks = scoring_engine.score_tracks(tracks)

    elapsed = time.time() - start_time
    log_event("recommender-service", "INFO", f"Scored {len(scored_tracks)} tracks in {elapsed:.2f}s")
    return {"scored_tracks": scored_tracks, "total": len(scored_tracks)}


@app.post("/score-artists")
async def score_artists(artists: list[dict]):
    import time
    start_time = time.time()

    if not scoring_engine:
        raise HTTPException(status_code=500, detail="Scoring engine not initialized")

    log_event("recommender-service", "INFO", f"Scoring {len(artists)} artists")

    scored_artists = scoring_engine.score_artists(artists)

    elapsed = time.time() - start_time
    log_event("recommender-service", "INFO", f"Scored {len(scored_artists)} artists in {elapsed:.2f}s")
    return {"scored_artists": scored_artists, "total": len(scored_artists)}


@app.post("/score-lastfm-tracks")
async def score_lastfm_tracks(tracks: list[dict]):
    import time
    start_time = time.time()

    if not scoring_engine:
        raise HTTPException(status_code=500, detail="Scoring engine not initialized")

    log_event("recommender-service", "INFO", f"Scoring {len(tracks)} Last.fm tracks")

    scored_tracks = scoring_engine.score_lastfm_tracks(tracks)

    elapsed = time.time() - start_time
    log_event("recommender-service", "INFO", f"Scored {len(scored_tracks)} Last.fm tracks in {elapsed:.2f}s")
    return {"scored_tracks": scored_tracks, "total": len(scored_tracks)}


@app.post("/score-lastfm-artists")
async def score_lastfm_artists(artists: list[dict]):
    import time
    start_time = time.time()

    if not scoring_engine:
        raise HTTPException(status_code=500, detail="Scoring engine not initialized")

    log_event("recommender-service", "INFO", f"Scoring {len(artists)} Last.fm artists")

    scored_artists = scoring_engine.score_lastfm_artists(artists)

    elapsed = time.time() - start_time
    log_event("recommender-service", "INFO", f"Scored {len(scored_artists)} Last.fm artists in {elapsed:.2f}s")
    return {"scored_artists": scored_artists, "total": len(scored_artists)}


@app.post("/aggregate-albums")
async def aggregate_albums(scored_tracks: list[dict], scored_artists: list[dict]):
    import time
    start_time = time.time()

    if not album_aggregator:
        raise HTTPException(status_code=500, detail="Album aggregator not initialized")

    log_event("recommender-service", "INFO", f"Aggregating albums from {len(scored_tracks)} tracks")

    albums = album_aggregator.aggregate_albums(scored_tracks, scored_artists)

    elapsed = time.time() - start_time
    log_event("recommender-service", "INFO", f"Generated {len(albums)} album recommendations in {elapsed:.2f}s")
    return {"albums": albums, "total": len(albums)}


@app.get("/progress")
async def get_progress():
    return progress_state


@app.post("/artist-recommendations")
async def artist_recommendations(request: ArtistRecommendationRequest):
    import time
    start_time = time.time()
    global progress_state

    discogs_key = os.getenv("DISCOGS_KEY")
    discogs_secret = os.getenv("DISCOGS_SECRET")

    if not discogs_key or not discogs_secret:
        raise HTTPException(status_code=500, detail="Discogs credentials not configured")

    if len(request.artist_names) < 3:
        raise HTTPException(status_code=400, detail="Minimum 3 artists required")

    if len(request.artist_names) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 artists allowed")

    progress_state = {
        "current": 0,
        "total": len(request.artist_names),
        "status": "processing",
        "current_artist": ""
    }

    log_event("recommender-service", "INFO", f"Generating recommendations for {len(request.artist_names)} artists")

    def update_progress(current: int, artist_name: str):
        global progress_state
        progress_state["current"] = current
        progress_state["current_artist"] = artist_name

    try:
        recommendations = await asyncio.to_thread(
            functools.partial(
                get_artist_based_recommendations,
                request.artist_names,
                discogs_key,
                discogs_secret,
                top_per_artist=request.top_per_artist,
                progress_callback=update_progress,
            )
        )

        progress_state["status"] = "completed"

        elapsed = time.time() - start_time
        log_event("recommender-service", "INFO", f"Generated {len(recommendations)} artist-based recommendations in {elapsed:.2f}s")
        return {"recommendations": recommendations, "total": len(recommendations)}
    except Exception as e:
        progress_state["status"] = "error"
        raise e


@app.post("/merge-recommendations")
async def merge_recommendations(request: MergeRecommendationsRequest):
    import time
    start_time = time.time()

    artist_recs = request.artist_recommendations
    lastfm_recs = request.lastfm_recommendations

    log_event("recommender-service", "INFO",
              f"Merging {len(artist_recs)} artist + {len(lastfm_recs)} Last.fm recommendations")

    seen_albums = set()
    merged: list[dict] = []
    max_len = max(len(artist_recs), len(lastfm_recs))

    def get_album_keys(rec: dict) -> list:
        """Returns all possible keys for this album to handle metadata variations"""
        keys = []

        if "album_info" in rec:
            album_info = rec.get("album_info", {})
            album = album_info.get("name", "").lower().strip()
            artists_list = album_info.get("artists", [])
            artist = artists_list[0].get("name", "") if artists_list else ""
            artist = artist.lower().strip()
        else:
            album = rec.get("album_name", "").lower().strip()
            artist = rec.get("artist_name", "").lower().strip()

        fallback_key = f"{artist}::{album}"
        keys.append(fallback_key)

        discogs_master = rec.get("discogs_master_id")
        if discogs_master:
            keys.append(f"master::{discogs_master}")

        return keys

    def is_duplicate(rec: dict) -> bool:
        """Check if album is already seen using any of its keys"""
        rec_keys = get_album_keys(rec)
        return any(key in seen_albums for key in rec_keys)

    def mark_as_seen(rec: dict):
        """Mark all keys for this album as seen"""
        rec_keys = get_album_keys(rec)
        for key in rec_keys:
            seen_albums.add(key)

    for i in range(max_len):
        if i < len(lastfm_recs):
            if not is_duplicate(lastfm_recs[i]):
                mark_as_seen(lastfm_recs[i])
                merged.append(lastfm_recs[i])

        if i < len(artist_recs):
            if not is_duplicate(artist_recs[i]):
                mark_as_seen(artist_recs[i])
                merged.append(artist_recs[i])

    duplicates_removed = (len(artist_recs) + len(lastfm_recs)) - len(merged)
    elapsed = time.time() - start_time
    log_event("recommender-service", "INFO",
              f"Merged into {len(merged)} total recommendations ({duplicates_removed} duplicates removed) in {elapsed:.2f}s")
    return {"recommendations": merged, "total": len(merged)}


@app.post("/collection-recommendations")
async def collection_recommendations(request: CollectionRecommendationRequest):
    import asyncio
    import time
    from concurrent.futures import ThreadPoolExecutor

    import httpx

    start_time = time.time()

    discogs_key = os.getenv("DISCOGS_KEY")
    discogs_secret = os.getenv("DISCOGS_SECRET")

    if not discogs_key or not discogs_secret:
        raise HTTPException(status_code=500, detail="Discogs credentials not configured")

    log_event("recommender-service", "INFO", f"Generating collection-based recommendations for user: {request.username}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Fetch User Collection
        try:
            resp = await client.post(
                f"{DISCOGS_SERVICE_URL}/user/collection",
                json={
                    "username": request.username,
                    "page": 1,
                    "per_page": 100, # Initial fetch, might need pagination logic for huge collections
                    "access_token": "", # Using app auth
                    "access_token_secret": ""
                }
            )
            resp.raise_for_status()
            collection_data = resp.json()
            releases = collection_data.get("releases", [])
        except Exception as e:
            log_event("recommender-service", "ERROR", f"Failed to fetch collection: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch collection: {str(e)}")

        if not releases:
            return {"recommendations": [], "total": 0, "message": "No releases found in collection"}

        # 2. Analyze Collection
        # owned_map: Artist -> {AlbumTitle: [Formats]}
        owned_map = {}
        all_artists = set()

        # upgrade_candidates: list of {"artist": str, "album": str, "formats": list}
        upgrade_candidates = []

        for item in releases:
            basic_info = item.get("basic_information", {})
            title = basic_info.get("title", "")
            artists = basic_info.get("artists", [])

            if not artists:
                continue

            artist_name = artists[0].get("name", "")
            # Clean artist name (remove " (2)", etc.)
            import re
            clean_artist = re.sub(r'\s*\(\d+\)$', '', artist_name)

            formats = [f.get("name", "") for f in basic_info.get("formats", [])]
            descriptions = []
            for f in basic_info.get("formats", []):
                descriptions.extend(f.get("descriptions", []))

            full_format_list = formats + descriptions

            # Filter out Singles/Maxis/EPs/Compilations - User Upgrade Request
            # Check desc list against excluded types
            excluded_types = ["single", "maxi-single", "ep", "mini-album", "compilation"]
            is_excluded = any(d.lower() in excluded_types for d in [desc.lower() for desc in descriptions])

            # Also check basic format string if it says "Single" or "Compilation"
            formats_lower = [f.lower() for f in formats]
            if "single" in formats_lower or "compilation" in formats_lower:
                is_excluded = True

            if is_excluded:
                continue

            # Normalize to lowercase for checking
            full_formats_lower = [f.lower() for f in full_format_list]

            has_vinyl = any("vinyl" in f or "lp" in f for f in full_formats_lower)

            if clean_artist not in owned_map:
                owned_map[clean_artist] = {}

            owned_map[clean_artist][title] = full_format_list
            all_artists.add(clean_artist)

            if not has_vinyl:
                upgrade_candidates.append({
                    "artist": clean_artist,
                    "album": title,
                    "current_formats": list(set(formats)) # Show main formats like "CD", "Cassette"
                })

        recommendations = []

        # 3. Generate Format Upgrades (Max 5)
        # Randomly shuffle candidates to vary recommendations
        import random
        random.shuffle(upgrade_candidates)

        log_event("recommender-service", "INFO", f"Found {len(upgrade_candidates)} potential upgrade candidates")

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=5) as executor:

            # Helper for thread-safe execution
            def check_upgrade(candidate):
                artist = candidate["artist"]
                album = candidate["album"]

                # Check Discogs directly (or via local DB check inside validate_album_with_discogs wrapper if we had one)
                # But here we call validate_album_with_discogs which calls API.
                # Ideally we check DB first.

                # DB Check logic (simplified here using db_utils if possible, otherwise rely on helper)
                cached = db_utils.get_cached_album(artist, album)
                if cached:
                    return {
                        "album_name": cached["title"],
                        "artist_name": cached["artist_name"],
                        "year": cached.get("year"),
                        "rating": cached.get("rating"),
                        "votes": cached.get("votes"),
                        "discogs_master_id": cached.get("discogs_master_id"),
                        "image_url": cached.get("cover_url"),
                        "source": "collection_upgrade",
                        "current_formats": candidate["current_formats"]
                    }

                # Discogs Fallback
                valid_data = validate_album_with_discogs(artist, album, discogs_key, discogs_secret)
                if valid_data:
                    # Save partial
                     db_utils.create_basic_album_entry(
                        artist_name=artist,
                        album_name=valid_data["title"],
                        cover_url=valid_data["cover_image"],
                        discogs_release_id=valid_data["discogs_release_id"],
                        discogs_master_id=valid_data["discogs_master_id"]
                    )

                     return {
                        "album_name": valid_data["title"],
                        "artist_name": artist,
                        "year": valid_data["year"],
                        "rating": None,
                        "votes": None,
                        "discogs_master_id": valid_data["discogs_master_id"],
                        "image_url": valid_data["cover_image"],
                        "source": "collection_upgrade",
                        "current_formats": candidate["current_formats"],
                        "is_partial": 1
                    }
                return None

            # Run checks in parallel
            display_upgrades = []
            futures = [executor.submit(check_upgrade, c) for c in upgrade_candidates[:50]] # Check top 50 candidates

            for future in futures:
                res = future.result()
                if res:
                    display_upgrades.append(res)
                    if len(display_upgrades) >= 10: # Limit to 10 upgrades
                        break

            recommendations.extend(display_upgrades)

            # 4. Generate Discography Completion
            # Pick random collected artists
            collected_list = list(all_artists)
            random.shuffle(collected_list)
            selected_artists = collected_list[:request.limit]

            log_event("recommender-service", "INFO", f"Checking discography completion for: {selected_artists}")

            def check_completion(artist):
                # 1. Get Top Popular Albums (Want+Have) from Discogs Search
                # db_utils check is implicit if we wrapped it, but get_top_albums_from_discogs_search is purely search.
                # We should enhance this to check DB first ideally, but per plan: Priority DB -> Discogs.

                # Let's try DB first for this artist
                cached_albums = get_artist_studio_albums(artist, discogs_key, discogs_secret, top_n=5, cache_only=True)

                candidates = []
                if cached_albums:
                    for alb in cached_albums:
                         candidates.append({
                             "title": alb.title,
                             "year": alb.year,
                             "cover_image": alb.cover_image,
                             "discogs_master_id": alb.discogs_master_id,
                             "discogs_release_id": alb.discogs_release_id,
                             "rating": alb.rating,
                             "votes": alb.votes,
                             "is_db": True
                         })
                else:
                    # Fallback to Search
                    search_results = get_top_albums_from_discogs_search(artist, discogs_key, discogs_secret, limit=5)
                    for alb in search_results:
                        candidates.append({
                            "title": alb["title"],
                            "year": alb["year"],
                            "cover_image": alb["cover_image"],
                            "discogs_master_id": alb["discogs_master_id"],
                            "discogs_release_id": alb["discogs_release_id"],
                            "rating": None,
                            "votes": alb["score"], # Use score as pseudo-votes
                            "is_db": False
                        })

                completion_recs = []
                import unicodedata
                def normalize(s):
                    return ''.join(c for c in unicodedata.normalize('NFD', s)
                                 if unicodedata.category(c) != 'Mn').lower().replace(' ', '')

                owned_titles_norm = {normalize(t) for t in owned_map.get(artist, {}).keys()}

                for alb in candidates:
                    alb_norm = normalize(alb["title"])
                    if alb_norm in owned_titles_norm:
                        continue

                    # Save if new
                    if not alb.get("is_db"):
                         db_utils.create_basic_album_entry(
                            artist_name=artist,
                            album_name=alb["title"],
                            cover_url=alb["cover_image"],
                            discogs_release_id=alb["discogs_release_id"],
                            discogs_master_id=alb["discogs_master_id"]
                        )

                    completion_recs.append({
                        "album_name": alb["title"],
                        "artist_name": artist,
                        "year": alb["year"],
                        "rating": alb["rating"],
                        "votes": alb["votes"],
                        "discogs_master_id": alb["discogs_master_id"],
                        "image_url": alb["cover_image"],
                        "source": "discography_completion",
                        "is_partial": 1 if not alb.get("is_db") else 0
                    })

                return completion_recs

            completion_futures = [executor.submit(check_completion, a) for a in selected_artists]
            for future in completion_futures:
                res = future.result()
                if res:
                    # Take top 1 per artist to ensure variety
                    recommendations.extend(res[:1])

    elapsed = time.time() - start_time
    log_event("recommender-service", "INFO", f"Generated {len(recommendations)} collection recommendations in {elapsed:.2f}s")

    return {"recommendations": recommendations, "total": len(recommendations)}





@app.post("/artist-single-recommendation")
async def artist_single_recommendation(request: SingleArtistRequest):
    import time
    start_time = time.time()

    discogs_key = os.getenv("DISCOGS_KEY")
    discogs_secret = os.getenv("DISCOGS_SECRET")

    if not discogs_key or not discogs_secret:
        raise HTTPException(status_code=500, detail="Discogs credentials not configured")

    log_event("recommender-service", "INFO", f"Generating recommendations for artist: {request.artist_name} (User: {request.user_id}, preview={request.preview})")

    # --- PREVIEW MODE: wizard pre-fetch — cache first, then Spotify (saves Discogs quota) ---
    if request.preview:
        # 1. Check local cache first (free)
        cached_albums = await asyncio.to_thread(
            functools.partial(
                get_artist_studio_albums,
                request.artist_name, discogs_key, discogs_secret,
                top_n=request.top_albums, cache_only=True,
            )
        )
        if cached_albums:
            log_event("recommender-service", "INFO", f"✓ Preview cache HIT for {request.artist_name}")
            return {
                "recommendations": [
                    {
                        "album_name": a.title,
                        "artist_name": a.artist_name,
                        "year": a.year,
                        "image_url": a.cover_image,
                        "discogs_master_id": a.discogs_master_id or a.discogs_release_id,
                        "source": "artist_based",
                    }
                    for a in cached_albums
                ],
                "total": len(cached_albums),
                "artist_name": request.artist_name,
            }

        # 2. Spotify (high quota, single call)
        log_event("recommender-service", "INFO", f"Preview cache MISS for {request.artist_name}, trying Spotify")
        try:
            return await _generate_spotify_recommendations(request.artist_name, request.top_albums, request.user_id)
        except Exception as e:
            log_event("recommender-service", "WARN", f"Spotify preview failed for {request.artist_name}: {e}")
            return {"recommendations": [], "total": 0, "artist_name": request.artist_name}

    # --- MODE A: Full User Context (Upgrade + Complete) ---
    if request.user_id:
        try:
            generated_recs = []

            # 1. Fetch User Collection data for this artist (for Ownership/Upgrade check)
            conn = db_utils.get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT title, internal_category, artist, release_type 
                FROM user_collection_discogs 
                WHERE user_id = ? AND artist = ?
            """, (request.user_id, request.artist_name))
            owned_items = cur.fetchall()
            conn.close()

            # Analyze ownership
            owned_titles_norm = set() # Normalized titles of ANY format
            owned_vinyl_keys = set() # Normalized (artist, title) of VINYLS
            candidates_for_upgrade = [] # CD items to upgrade

            import re
            import unicodedata
            def normalize_title(s):
                if not s: return ""
                try:
                    s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
                except: pass
                s = s.lower().replace("'", "").replace('"', "")
                return re.sub(r'[^a-z0-9]', '', s)

            for item in owned_items:
                title_norm = normalize_title(item['title'])
                owned_titles_norm.add(title_norm)

                cat = (item['internal_category'] or "").lower()
                is_vinyl = "vinyl" in cat or "lp" in cat

                if is_vinyl:
                    owned_vinyl_keys.add(title_norm)
                elif (item['release_type'] or "Other") == "Album":
                    # Candidate for upgrade if not owned as vinyl
                    candidates_for_upgrade.append({
                        "title": item['title'],
                        "norm": title_norm
                    })

            # 2. Fetch Discography (Cache -> Discogs Search Only) used to be Cache -> MB -> Discogs
            # As per user request: DB + Single Discogs Call (No MB)
            discography = await asyncio.to_thread(
                functools.partial(
                    get_artist_studio_albums,
                    request.artist_name, discogs_key, discogs_secret,
                    top_n=50, use_mb=False, cache_only=False,
                )
            )


            # --- UPGRADE STRATEGY ---
            for cand in candidates_for_upgrade:
                # If we don't already own the vinyl
                if cand['norm'] not in owned_vinyl_keys:
                    # Look for match in discography
                    match = next((alb for alb in discography if normalize_title(alb.title) == cand['norm']), None)
                    if match:
                         generated_recs.append({
                             "album_name": match.title,
                             "artist_name": request.artist_name,
                             "cover_url": match.cover_image,
                             "source": "collection_upgrade",
                             "image_url": match.cover_image,
                             "reason": "Upgrade CD to Vinyl",
                             "year": match.year,
                             "discogs_master_id": match.discogs_master_id
                         })
                         # Mark as found so we don't suggest it again in Completion
                         owned_vinyl_keys.add(cand['norm'])

            # --- COMPLETION STRATEGY ---
            completion_count = 0
            added_titles_norm = set() # Track added titles to prevent duplicates in current response

            for album in discography:
                if completion_count >= request.top_albums:
                    break

                t_norm = normalize_title(album.title)

                # Check if already owned OR already added in this batch
                # Also check against owned_vinyl_keys just in case an Upgrade was already added for this title
                if t_norm not in owned_titles_norm and t_norm not in added_titles_norm and t_norm not in owned_vinyl_keys:
                    generated_recs.append({
                        "album_name": album.title,
                        "artist_name": request.artist_name,
                        "cover_url": album.cover_image,
                        "source": "discography_completion",
                        "image_url": album.cover_image,
                        "year": album.year
                    })
                    added_titles_norm.add(t_norm)
                    completion_count += 1

            # 3. Persist
            saved_count = db_utils.save_recommendations_batch(request.user_id, generated_recs)
            log_event("recommender-service", "INFO", f"Saved {saved_count} recommendations for {request.artist_name}")

            if generated_recs:
                return {
                    "recommendations": generated_recs,
                    "total": len(generated_recs),
                    "saved": saved_count,
                    "artist_name": request.artist_name
                }

            # Discogs found nothing for this user — fall through to Spotify fallback
            log_event("recommender-service", "INFO",
                      f"No Discogs albums for {request.artist_name} (user context), trying Spotify fallback")

        except Exception as e:
            log_event("recommender", "ERROR", f"Single artist generation failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # --- MODE B: Legacy / Simple (No User Context) ---
    try:
        # 1. Try to get from DB (Cache Only)
        albums = await asyncio.to_thread(
            functools.partial(
                get_artist_studio_albums,
                request.artist_name,
                discogs_key,
                discogs_secret,
                top_n=request.top_albums,
                csv_mode=request.csv_mode,
                cache_only=True,
            )
        )

        if albums:
            # CACHE HIT
            recommendations = []
            for album in albums:
                rec = {
                    "album_name": album.title,
                    "artist_name": album.artist_name,
                    "year": album.year,
                    "rating": album.rating,
                    "votes": album.votes,
                    "discogs_master_id": album.discogs_master_id or album.discogs_release_id,
                    "discogs_type": album.discogs_type,
                    "image_url": album.cover_image or "https://via.placeholder.com/300x300?text=No+Cover",
                    "source": "artist_based"
                }
                recommendations.append(rec)

            elapsed = time.time() - start_time
            log_event("recommender-service", "INFO", f"✓ Cache HIT for {request.artist_name}")
            return {"recommendations": recommendations, "total": len(recommendations), "artist_name": request.artist_name}

        # CACHE MISS — try live Discogs search
        log_event("recommender-service", "INFO", f"○ Cache MISS for {request.artist_name}. Using Discogs Search.")

        discogs_albums = await asyncio.to_thread(
            functools.partial(
                get_top_albums_from_discogs_search,
                request.artist_name,
                discogs_key,
                discogs_secret,
                limit=request.top_albums,
            )
        )

        if discogs_albums:
            recommendations = []
            for album in discogs_albums:
                db_utils.create_basic_album_entry(
                    artist_name=album["artist_name"],
                    album_name=album["title"],
                    cover_url=album["cover_image"],
                    discogs_master_id=album["discogs_master_id"],
                    discogs_release_id=album["discogs_release_id"]
                )
                rec = {
                    "album_name": album["title"],
                    "artist_name": album["artist_name"],
                    "year": album["year"],
                    "rating": None,
                    "votes": None,
                    "discogs_master_id": album["discogs_master_id"] or album["discogs_release_id"],
                    "discogs_type": "master" if album["discogs_master_id"] else "release",
                    "image_url": album["cover_image"] or "https://via.placeholder.com/300x300?text=No+Cover",
                    "source": "artist_based_partial",
                    "is_partial": 1
                }
                recommendations.append(rec)
            elapsed = time.time() - start_time
            return {"recommendations": recommendations, "total": len(recommendations), "artist_name": request.artist_name}

        # Discogs returned nothing — fall back to Spotify
        log_event("recommender-service", "INFO",
                  f"Discogs returned 0 results for {request.artist_name}, trying Spotify fallback")

    except Exception as e:
        log_event("recommender-service", "ERROR", f"Discogs search failed for {request.artist_name}: {str(e)}")
        log_event("recommender-service", "INFO", f"Falling back to Spotify for {request.artist_name}")

    # --- SPOTIFY FALLBACK (Discogs returned nothing or errored) ---
    try:
        return await _generate_spotify_recommendations(request.artist_name, request.top_albums, request.user_id)
    except Exception as e:
        log_event("recommender-service", "WARN",
                  f"Spotify fallback also failed for {request.artist_name}: {str(e)}")
        return {"recommendations": [], "total": 0, "artist_name": request.artist_name}


async def _generate_spotify_recommendations(artist_name: str, top_albums: int, user_id: int = None):
    """Helper to generate recommendations using Spotify (fast fallback)"""
    import time

    import httpx

    from . import db_utils

    start_time = time.time()
    log_event("recommender-service", "INFO", f"Generating Spotify recommendations for: {artist_name}")

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Search artist to get ID
        search_resp = await client.get(
            f"{SPOTIFY_SERVICE_URL}/search/artists",
            params={"q": artist_name, "limit": 1}
        )
        search_data = search_resp.json()
        artists = search_data.get("artists", [])

        if not artists:
            raise HTTPException(status_code=404, detail="Artist not found on Spotify")

        artist = artists[0]
        spotify_artist_id = artist["id"]
        artist_name = artist["name"]  # Use canonical name

        # 2. Get top albums
        albums_resp = await client.get(
            f"{SPOTIFY_SERVICE_URL}/artist/{spotify_artist_id}/albums",
            params={"limit": top_albums + 5}  # Fetch a few more to filter
        )
        albums_data = albums_resp.json()
        spotify_albums = albums_data.get("albums", [])

        recommendations = []

        # 3. Process albums (check cache or create partial)
        for album in spotify_albums[:top_albums]:
            # Check cache
            cached = db_utils.get_cached_album(
                artist_name,
                album["name"],
                spotify_id=album["id"]
            )

            if cached:
                # Use cached data (might be full or partial)
                rec = {
                    "album_name": cached["title"],
                    "artist_name": cached["artist_name"],
                    "year": cached.get("year"),
                    "rating": cached.get("rating"),
                    "votes": cached.get("votes"),
                    "discogs_master_id": cached.get("discogs_master_id"),
                    "image_url": cached.get("cover_url"),
                    "spotify_id": cached.get("spotify_id"),
                    "is_partial": cached.get("is_partial", 0),
                    "source": "spotify"
                }
            else:
                # Create partial entry
                db_utils.create_basic_album_entry(
                    artist_name,
                    album["name"],
                    cover_url=album["image_url"],
                    spotify_id=album["id"],
                    artist_spotify_id=spotify_artist_id
                )

                rec = {
                    "album_name": album["name"],
                    "artist_name": artist_name,
                    "year": album.get("release_date")[:4] if album.get("release_date") else None,
                    "rating": None,
                    "votes": None,
                    "image_url": album["image_url"],
                    "spotify_id": album["id"],
                    "is_partial": 1,
                    "source": "spotify"
                }

            recommendations.append(rec)

        elapsed = time.time() - start_time
        log_event("recommender-service", "INFO",
                 f"Generated {len(recommendations)} Spotify recommendations for {artist_name} in {elapsed:.2f}s")

        return {
            "recommendations": recommendations,
            "total": len(recommendations),
            "artist_name": artist_name
        }


@app.post("/collection/stats")
async def collection_stats(request: CollectionStatsRequest):
    """Analyze collection and return stats + top artists"""
    try:
        conn = db_utils.get_db_connection()
        try:
            cur = conn.cursor()

            # 1. Format Stats
            # Extract format from 'release_data' JSON or assume CD if not vinyl/cassette?
            # Ideally we check 'release_data'. But for specific Upgrade logic we rely on 'internal_category' if updated correctly,
            # OR we parse real time.
            # Let's rely on querying user_collection_discogs.

            # Count total items
            cur.execute("SELECT count(*) FROM user_collection_discogs WHERE user_id = ?", (request.user_id,))
            total_items = cur.fetchone()['count(*)']

            # Count by internal_category if reliable, or just "Vinyl" check
            # For stats display we want "Vinyl", "CD", "Other"
            # Since we iterate loosely in main logic, let's do a group by artist first for focus.

            # 2. Top Artists
            # Get artists with > 1 item
            cur.execute("""
                SELECT artist, count(*) as count 
                FROM user_collection_discogs 
                WHERE user_id = ? 
                AND artist NOT LIKE 'Various%'
                AND artist NOT LIKE 'Varios%'
                GROUP BY artist 
                HAVING count > 1 
                ORDER BY count DESC 
                LIMIT 50
            """, (request.user_id,))

            top_artists = [{"name": row["artist"], "count": row["count"]} for row in cur.fetchall()]

            return {
                "total_items": total_items,
                "top_artists": top_artists,
                "user_id": request.user_id
            }

        finally:
            conn.close()
    except Exception as e:
        log_event("recommender-service", "ERROR", f"Stats fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/collection/preferences")
async def save_preferences(request: CollectionPreferencesRequest):
    """Save use focus preferences"""
    import json
    try:
        success = db_utils.save_user_preferences(
            request.user_id,
            json.dumps(request.focus_artists),
            json.dumps(request.strategies)
        )
        if success:
             return {"status": "success", "message": "Preferences saved"}
        else:
             raise HTTPException(status_code=500, detail="Failed to save preferences")
    except Exception as e:
        log_event("recommender-service", "ERROR", f"Pref save failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/collection/generate")
async def generate_targeted_recommendations(request: CollectionPreferencesRequest):
    """
    Generate recommendations based on saved preferences (or passed ones) and PERSIST them.
    This replaces the random lottery.
    """
    import asyncio
    import os

    try:
        conn = db_utils.get_db_connection()

        # 1. Determine scope
        focus_artists = request.focus_artists
        if not focus_artists:
            # Fallback to Top 10 if not provided
             cur = conn.cursor()
             cur.execute("""
                SELECT artist FROM user_collection_discogs 
                WHERE user_id = ? 
                GROUP BY artist 
                ORDER BY count(*) DESC 
                LIMIT 10
            """, (request.user_id,))
             focus_artists = [row["artist"] for row in cur.fetchall()]
             conn.close()

        if not focus_artists:
            log_event("recommender", "WARNING", "No focus artists found (empty collection?), skipping generation.")
            return {"count": 0, "status": "no_data"}

        # 2. Re-use logic from collection_recommendations but restrictive
        # We need to instantiate a request object that mimics CollectionRecommendationRequest
        # but focused.

        # NOTE: To reuse code effectively, we should refactor `collection_recommendations` logic to a helper function.
        # For now, I will create a focused version here that calls the same helpers.

        generated_recs = []

        # A. UPGRADES (If 'upgrade' in strategies)
        if "upgrade" in request.strategies:
            log_event("recommender", "INFO", f"Generating UPGRADES for {len(focus_artists)} artists")

            # Fetch candidates only for these artists
            conn = db_utils.get_db_connection()
            cur = conn.cursor()
            placeholders = ','.join(['?'] * len(focus_artists))
            query = f"""
                SELECT title, internal_category, artist, release_type 
                FROM user_collection_discogs 
                WHERE user_id = ? AND artist IN ({placeholders})
            """
            params = [request.user_id] + focus_artists
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            conn.close()

            # 1. Identify all albums currently owned on Vinyl to prevent redundancy
            owned_vinyl_keys = set()
            for row in rows:
                cat = (row['internal_category'] or "").lower()
                if "vinyl" in cat or "lp" in cat:
                    # Key: (artist, title) - normalized
                    k = (row['artist'].strip().lower(), row['title'].strip().lower())
                    owned_vinyl_keys.add(k)

            candidates = []
            seen_candidates = set() # To avoid duplicates

            # Group candidates by artist for batch processing
            artist_candidates = {} # artist -> [candidates]

            for row in rows:
                category = (row['internal_category'] or "").lower()
                release_type = (row['release_type'] or "Other")

                # STRICT UPGRADE POLICY: Only Albums
                if release_type != "Album":
                    continue

                # Is this item itself a Vinyl?
                is_vinyl = "vinyl" in category or "lp" in category

                if not is_vinyl:
                    artist = row['artist'].strip()
                    title = row['title'].strip()

                    # Check if we already own a Vinyl version of this album
                    key_norm = (artist.lower(), title.lower())

                    if key_norm in owned_vinyl_keys:
                        continue

                    if key_norm in seen_candidates:
                        continue

                    seen_candidates.add(key_norm)

                    if artist not in artist_candidates:
                        artist_candidates[artist] = []

                    artist_candidates[artist].append({
                        "artist": artist,
                        "album": title,
                        "current_formats": [row['internal_category']]
                    })

            # Helper for robust title matching (local scope)
            import re
            import unicodedata
            def match_title(target, source):
                def norm(s):
                    if not s: return ""
                    try:
                        s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
                    except: pass
                    s = s.lower().replace("'", "").replace('"', "")
                    return re.sub(r'[^a-z0-9]', '', s)
                return norm(target) == norm(source)

            # Process each artist ONCE
            upgrades = []
            for artist, cand_list in artist_candidates.items():
                try:
                    # Fetch Vinyl Discography (Cache -> MB -> Discogs)
                    log_event("recommender", "INFO", f"[UPGRADE] Batch fetching vinyls for {artist}")

                    # Use get_artist_studio_albums which handles caching
                    # Returns list of StudioAlbum objects
                    vinyls_objs = await asyncio.to_thread(
                        functools.partial(
                            get_artist_studio_albums,
                            artist,
                            os.getenv("DISCOGS_KEY"),
                            os.getenv("DISCOGS_SECRET"),
                            top_n=100,
                            cache_only=False,
                            use_mb=False,
                        )
                    )

                    # Convert to list of dicts for matching logic
                    vinyls = []
                    for v in vinyls_objs:
                         vinyls.append({
                             "title": v.title,
                             "cover_image": v.cover_image,
                             "year": v.year,
                             "discogs_master_id": v.discogs_master_id
                         })

                    # Match in-memory
                    for cand in cand_list:
                        candidate_title = cand['album']

                        # Find match in fetched vinyls
                        match = next((v for v in vinyls if match_title(candidate_title, v['title'])), None)

                        if match:
                             # It exists as Vinyl!
                             upgrades.append({
                                "album_name": match["title"],
                                "artist_name": artist,
                                "cover_url": match["cover_image"],
                                "source": "collection_upgrade",
                                "image_url": match["cover_image"],
                                "reason": "Upgrade CD to Vinyl",
                                "year": match["year"],
                                "discogs_master_id": match["discogs_master_id"]
                             })
                except Exception as e:
                    log_event("recommender", "ERROR", f"[UPGRADE] Error processing batch for {artist}: {e}")

            # Take top 50
            generated_recs.extend(upgrades[:50])

        # B. COMPLETION (If 'complete' in strategies)
        if "complete" in request.strategies:
            log_event("recommender", "INFO", f"Generating COMPLETIONS for {len(focus_artists)} artists")
            discogs_key = os.getenv("DISCOGS_KEY")
            discogs_secret = os.getenv("DISCOGS_SECRET")

            import unicodedata

            # Helper to normalize for comparison (local definition to avoid dependency issues)
            def normalize_title(s):
                if not s: return ""
                try:
                    s = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
                except: pass
                s = s.lower().replace("'", "").replace('"', "")
                import re
                return re.sub(r'[^a-z0-9]', '', s)

            for artist in focus_artists:
                # Reuse existing logic: get_artist_studio_albums -> filter owned -> return top missing
                try:
                    # Increased limit from 5 to 50 to ensure we find albums the user DOESN'T have
                    results = await asyncio.to_thread(
                        functools.partial(
                            get_top_albums_from_discogs_search,
                            artist, discogs_key, discogs_secret, limit=50,
                        )
                    )

                    conn = db_utils.get_db_connection()
                    cur = conn.cursor()
                    # Check what we already have for this artist
                    cur.execute("SELECT title FROM user_collection_discogs WHERE user_id=? AND artist=?", (request.user_id, artist))

                    owned_titles_norm = set()
                    for row in cur.fetchall():
                        owned_titles_norm.add(normalize_title(row['title']))

                    conn.close()

                    filtered = []
                    for res in results:
                        # Normalize API title to compare
                        t_norm = normalize_title(res['title'])
                        if t_norm in owned_titles_norm:
                            continue
                        filtered.append(res)

                    # Take top 3 missing albums per artist
                    for res in filtered[:3]:
                        generated_recs.append({
                            "album_name": res["title"],
                            "artist_name": artist,
                            "cover_url": res["cover_image"],
                            "source": "discography_completion",
                            "image_url": res["cover_image"]
                        })
                except Exception as e:
                    log_event("recommender", "ERROR", f"Completion check failed for {artist}: {e}")
                    continue

        # 3. Persist
        saved_count = db_utils.save_recommendations_batch(request.user_id, generated_recs)

        return {
            "status": "success",
            "generated": len(generated_recs),
            "saved": saved_count,
            "recommendations": generated_recs # Return so frontend can show immediately
        }

    except Exception as e:
        log_event("recommender", "ERROR", f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
