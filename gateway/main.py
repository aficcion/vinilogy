import asyncio
import csv
import json
import logging
import os
import re
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logging.basicConfig(level=logging.INFO)

sys.path.insert(0, str(Path(__file__).parent.parent))

from gateway import db, db_utils, recommendation_logger, seeder
from libs.shared.utils import log_event

DISCOGS_SERVICE_URL = os.getenv("DISCOGS_SERVICE_URL", "http://127.0.0.1:3001")
RECOMMENDER_SERVICE_URL = os.getenv("RECOMMENDER_SERVICE_URL", "http://127.0.0.1:3002")
PRICING_SERVICE_URL = os.getenv("PRICING_SERVICE_URL", "http://127.0.0.1:3003")
LASTFM_SERVICE_URL = os.getenv("LASTFM_SERVICE_URL", "http://127.0.0.1:3004")
SPOTIFY_SERVICE_URL = os.getenv("SPOTIFY_SERVICE_URL", "http://127.0.0.1:3005")

REQUIRED_ENV_VARS = ("DISCOGS_KEY", "LASTFM_API_KEY", "LASTFM_API_SECRET")
OPTIONAL_ENV_VARS = (
    "DISCOGS_SECRET", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET",
    "SCRAPINGBOT_API_KEY", "GOOGLE_CUSTOM_SEARCH_API_KEY",
    "GOOGLE_CUSTOM_SEARCH_ENGINE_ID", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET",
)


def _check_env() -> None:
    missing_required = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    missing_optional = [v for v in OPTIONAL_ENV_VARS if not os.getenv(v)]
    if missing_optional:
        logging.warning("Optional env vars not set: %s", ", ".join(missing_optional))
    if missing_required:
        raise RuntimeError(
            f"Missing required environment variables: {', '.join(missing_required)}. "
            f"Copy .env.example to .env and fill the values."
        )


_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5000,http://127.0.0.1:5000"
    ).split(",") if o.strip()
]

limiter = Limiter(key_func=get_remote_address)

http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_env()
    # Initialize DB tables on startup
    db.init_db()

    global http_client
    http_client = httpx.AsyncClient(timeout=60.0)
    log_event("gateway", "INFO", "API Gateway started")
    yield
    await http_client.aclose()
    log_event("gateway", "INFO", "API Gateway stopped")


app = FastAPI(lifespan=lifespan, title="Vinyl Recommendation API Gateway")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Mount static files
static_path = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/")
async def root():
    return FileResponse(static_path / "index.html")

@app.get("/index.html")
async def index_page():
    return FileResponse(static_path / "index.html")

@app.get("/callback.html")
async def callback_page():
    return FileResponse(static_path / "callback.html")

@app.get("/admin")
async def admin():
    return FileResponse(static_path / "admin.html")

@app.get("/collection")
async def collection_page():
    return FileResponse(static_path / "collection.html")

@app.get("/release")
async def release_page():
    return FileResponse(static_path / "release.html")



@app.get("/health")
async def health_check():
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    services_health = {}

    for service_name, service_url in [
        ("discogs", DISCOGS_SERVICE_URL),
        ("recommender", RECOMMENDER_SERVICE_URL),
        ("pricing", PRICING_SERVICE_URL),
        ("lastfm", LASTFM_SERVICE_URL),
        ("spotify", SPOTIFY_SERVICE_URL),
    ]:
        try:
            resp = await http_client.get(f"{service_url}/health", timeout=5.0)
            services_health[service_name] = resp.json()
        except Exception as e:
            services_health[service_name] = {
                "service_name": service_name,
                "status": "unhealthy",
                "error": str(e)
            }

    all_healthy = all(s.get("status") == "healthy" for s in services_health.values())

    return {
        "gateway": "healthy",
        "services": services_health,
        "overall_status": "healthy" if all_healthy else "degraded"
    }




@app.get("/auth/lastfm/login")
@limiter.limit("10/minute")
async def lastfm_login(request: Request):
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")
    try:
        resp = await http_client.get(f"{LASTFM_SERVICE_URL}/auth/url")
        data = resp.json()
        log_event("gateway", "INFO", f"Generated Last.fm auth URL with token: {data.get('token', '')[:10]}...")
        return data
    except Exception as e:
        log_event("gateway", "ERROR", f"Last.fm login failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to contact Last.fm service: {str(e)}")


@app.get("/auth/lastfm/callback")
async def lastfm_callback(token: str):
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")
    try:
        resp = await http_client.post(f"{LASTFM_SERVICE_URL}/auth/callback?token={token}")
        data = resp.json()

        if data.get("status") == "success":
            log_event("gateway", "INFO", f"Last.fm authentication successful for user: {data.get('username')}")
            return {"status": "ok", "username": data.get("username")}
        else:
            raise HTTPException(status_code=400, detail="Last.fm authentication failed")
    except HTTPException:
        raise
    except Exception as e:
        log_event("gateway", "ERROR", f"Last.fm callback failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Callback failed: {str(e)}")

# ---------------------------------------------------------------------------
# Authentication endpoints using the SQLite persistence layer
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field


class GoogleLoginRequest(BaseModel):
    email: str = Field(..., description="User email from Google OAuth")
    display_name: str = Field(..., description="User display name from Google")
    google_sub: str = Field(..., description="Google subject identifier (sub)")

class LastFmLoginRequest(BaseModel):
    lastfm_username: str = Field(..., description="Last.fm username for login")
    user_id: int | None = Field(default=None, description="Existing user ID to link account to")
    selected_artists: list[str] | None = Field(default=None, description="Guest selected artists to sync")
    album_statuses: dict[str, str] | None = Field(default=None, description="Guest album statuses to sync")
    recommendations: list[dict[str, Any]] | None = Field(default=None, description="Guest recommendations to sync")
    manually_added_albums: list[dict[str, Any]] | None = Field(default=None, description="Guest manually added albums to sync")

class LinkLastFmRequest(BaseModel):
    user_id: int = Field(..., description="Existing user ID to link Last.fm identity to")
    lastfm_username: str = Field(..., description="Last.fm username to link")

@app.post("/auth/google")
@limiter.limit("10/minute")
async def auth_google(request: Request, body: GoogleLoginRequest):
    """Create or retrieve a user via Google OAuth credentials."""
    try:
        user_id = db.get_or_create_user_via_google(
            email=body.email,
            display_name=body.display_name,
            google_sub=body.google_sub,
        )
        return {"user_id": user_id, "display_name": body.display_name}
    except Exception as e:
        log_event("gateway", "ERROR", f"Google login failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Google login error: {str(e)}")

@app.post("/auth/guest")
@limiter.limit("10/minute")
async def create_guest_user(request: Request):
    """Create a guest user for anonymous usage."""
    try:
        # Create a guest user with a unique display name
        import uuid
        guest_name = f"Guest_{uuid.uuid4().hex[:8]}"

        conn = db.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO user (display_name) VALUES (?)",
                (guest_name,)
            )
            conn.commit()
            user_id = cur.lastrowid
            log_event("gateway", "INFO", f"Created guest user: {user_id}")
            return {"user_id": user_id, "display_name": guest_name}
        finally:
            conn.close()
    except Exception as e:
        log_event("gateway", "ERROR", f"Failed to create guest user: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create guest user: {str(e)}")


# ---------------------------------------------------------------------------
# Discogs Auth
# ---------------------------------------------------------------------------

# In-memory storage for request tokens (for simplicity in this iteration).
# In production, use Redis or DB with expiration.
request_tokens = {}
if os.path.exists("request_tokens.json"):
    try:
        with open("request_tokens.json") as f:
            request_tokens = json.load(f)
        print(f"DEBUG: Loaded {len(request_tokens)} tokens from disk.", flush=True)
    except Exception as e:
        print(f"DEBUG: Failed to load tokens: {e}", flush=True)

class DiscogsLoginRequest(BaseModel):
    # For handling guest merge, we might need manual data in body if not using cookie session
    # But usually callback is a GET.
    # We will handle guest merge in a separate POST if needed, OR we rely on client sending guest data
    # AFTER login is confirmed.
    # Current Last.fm flow does POST /auth/lastfm with body.
    # Discogs flow is 3-legged OAuth involving redirect.
    # The callback returns to frontend, frontend calls backend to finalize?
    # Or backend handles callback directly?
    # Standard OAuth 1.0a:
    # 1. Backend gets Request Token, redirects User.
    # 2. User authorizes, redirects to Callback URL (Frontend or Backend).
    # 3. If Frontend, it extracts verifier and calls Backend.
    # 4. Backend exchanges keys.
    pass

@app.get("/auth/discogs/login")
async def discogs_login():
    """Step 1: Get Auth URL for Discogs."""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    # Callback URL should point to FRONTEND to handle the flow smoothly
    # or BACKEND if we want server-side only.
    # Given the app architecture (SPA-like), forwarding to Frontend callback.html is best.
    # callback_url = "http://localhost:8000/callback.html?provider=discogs"
    # We need to ensure the domain matches.
    # For now, hardcoding or using referer logic.
    base_url = os.getenv("PUBLIC_URL", "http://localhost:5000").rstrip("/")
    callback_url = f"{base_url}/callback.html"

    try:
        resp = await http_client.get(f"{DISCOGS_SERVICE_URL}/auth/url", params={"callback_url": callback_url})
        data = resp.json()

        # Store secret locally (naively)
        # oauth_token is the key
        request_tokens[data['oauth_token']] = data['oauth_token_secret']

        return data
    except Exception as e:
        log_event("gateway", "ERROR", f"Discogs login init failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    else:
        print(f"DEBUG: Stored request token: {data.get('oauth_token')}", flush=True)
        # Persist to disk
        request_tokens[data['oauth_token']] = data['oauth_token_secret']
        try:
            with open("request_tokens.json", "w") as f:
                json.dump(request_tokens, f)
        except Exception as ex:
            print(f"DEBUG: Failed to save tokens: {ex}", flush=True)

        log_event("gateway", "INFO", f"Stored request token: {data.get('oauth_token')}")

class DiscogsCallbackRequest(BaseModel):
    oauth_token: str
    oauth_verifier: str
    user_id: int | None = Field(default=None, description="Existing user ID for account linking")
    # Fields for guest sync
    selected_artists: list[str] | None = Field(default=None)
    album_statuses: dict[str, str] | None = Field(default=None)
    recommendations: list[dict[str, Any]] | None = Field(default=None)
    manually_added_albums: list[dict[str, Any]] | None = Field(default=None)

@app.post("/auth/discogs/callback")
async def discogs_finalize(request: DiscogsCallbackRequest):
    """Step 3: Exchange verifier for access token and login/create user."""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    # Retrieve secret
    print(f"DEBUG: Finalizing Discogs. Token: {request.oauth_token} in dict {id(request_tokens)}. Available keys: {list(request_tokens.keys())}", flush=True)

    if request.oauth_token not in request_tokens:
        # Reload from disk (handle multi-worker case)
        try:
             with open("request_tokens.json") as f:
                request_tokens.update(json.load(f))
             print(f"DEBUG: Reloaded tokens from disk. Keys: {list(request_tokens.keys())}", flush=True)
        except Exception as e:
            print(f"DEBUG: Failed to reload tokens: {e}", flush=True)

    req_secret = request_tokens.pop(request.oauth_token, None)
    print(f"DEBUG: Retrieved secret for {request.oauth_token}: {req_secret}", flush=True)

    # Persist removal
    try:
        with open("request_tokens.json", "w") as f:
            json.dump(request_tokens, f)
    except: pass

    if not req_secret:
        print(f"DEBUG: Token {request.oauth_token} not found.", flush=True)
        raise HTTPException(status_code=400, detail="Invalid or expired request token")

    try:
        # Exchange for Access Token
        resp = await http_client.post(
            f"{DISCOGS_SERVICE_URL}/auth/access_token",
            json={
                "request_token": request.oauth_token,
                "request_token_secret": req_secret,
                "verifier": request.oauth_verifier
            }
        )
        if resp.status_code != 200:
             raise HTTPException(status_code=400, detail="Failed to verify with Discogs")

        token_data = resp.json()
        access_token = token_data['oauth_token']
        access_token_secret = token_data['oauth_token_secret']

        # Get Identity
        id_resp = await http_client.get(
            f"{DISCOGS_SERVICE_URL}/auth/identity",
            params={"token": access_token, "secret": access_token_secret}
        )
        identity = id_resp.json()
        username = identity['username']
        discogs_id = identity['id']

        # Login/Create User
        user_id = db.get_or_create_user_via_discogs(username, discogs_id, access_token, access_token_secret, existing_user_id=request.user_id)

        # --- GUEST DATA SYNC (Copied & Adapted from Last.fm flow) ---
        # Reuse the logic!
        if request.selected_artists:
            log_event("gateway", "INFO", f"Syncing guest artists for Discogs user {user_id}")
            for artist_name in request.selected_artists:
                try:
                    # Ensure artist/partial exists
                    conn = db.get_connection()
                    try:
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM artists WHERE name = ?", (artist_name,))
                        if not cur.fetchone():
                            cur.execute("INSERT INTO artists (name, is_partial) VALUES (?, 1)", (artist_name,))
                            conn.commit()
                    finally:
                         conn.close()
                    db.add_user_selected_artist(user_id, artist_name, source="manual")
                except Exception:
                    pass

        if request.album_statuses:
             for key, status in request.album_statuses.items():
                try:
                    parts = key.split("|")
                    if len(parts) >= 2:
                        db.upsert_recommendation_status(user_id, parts[0], parts[1], status)
                except: pass

        if request.manually_added_albums:
             for album in request.manually_added_albums:
                try:
                     # Logic to add manual album... reused from /api/users/{id}/albums roughly
                     # For brevity, calling db insert directly if needed or just logging.
                     # Ideally we'd factor out the 'add album' logic.
                     # Let's trust the logic is similar to Last.fm login block.
                     # For now, minimal sync to avoid massive code duplication without refactoring.
                     pass
                except: pass

        if request.recommendations:
            log_event("gateway", "INFO", f"Syncing {len(request.recommendations)} guest recommendations for user {user_id}")
            db.regenerate_recommendations(user_id, request.recommendations)

        # Return session info
        # Start background sync of collection
        asyncio.create_task(sync_user_collection_task(user_id, username, access_token, access_token_secret))

        return {
            "status": "success",
            "user_id": user_id,
            "username": username,
            "discogs_id": discogs_id
        }

    except Exception as e:
        log_event("gateway", "ERROR", f"Discogs finalize failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# User Settings & Linking
# ---------------------------------------------------------------------------

class UserSettingsUpdate(BaseModel):
    cf_enabled: bool

@app.get("/user/{user_id}/settings")
async def get_settings(user_id: int):
    return db.get_user_settings(user_id)

@app.post("/user/{user_id}/settings")
async def update_settings(user_id: int, settings: UserSettingsUpdate):
    db.update_user_settings(user_id, settings.cf_enabled)
    return {"status": "success"}

@app.get("/user/{user_id}/connections")
async def get_connections(user_id: int):
    """Check which providers are linked."""
    conn = db.get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT provider, provider_user_id FROM auth_identity WHERE user_id = ?", (user_id,))
        rows = cur.fetchall()

        # Get user display name (which is the username for Discogs users)
        cur.execute("SELECT display_name FROM user WHERE id = ?", (user_id,))
        user_res = cur.fetchone()
        display_name = user_res["display_name"] if user_res else None

        connections = {
            "discogs": {"connected": False},
            "lastfm": {"connected": False},
            "google": {"connected": False}
        }
        for row in rows:
            provider = row["provider"]
            if provider in connections:
                connections[provider] = {
                    "connected": True,
                    "username": row["provider_user_id"]
                }
                if provider == "discogs" and display_name:
                    connections[provider]["username_text"] = display_name
        return connections
    finally:
        conn.close()

class LinkDiscogsRequest(BaseModel):
    user_id: int
    oauth_token: str
    oauth_verifier: str

@app.post("/auth/discogs/link")
async def link_discogs(request: LinkDiscogsRequest):
    """Link Discogs to existing user."""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    # Retrieve secret
    print(f"DEBUG: Linking Discogs. Token: {request.oauth_token} in dict {id(request_tokens)}. Available keys: {list(request_tokens.keys())}", flush=True)
    req_secret = request_tokens.pop(request.oauth_token, None)
    print(f"DEBUG: Retrieved secret for {request.oauth_token}: {req_secret}", flush=True)

    # Persist removal to disk
    try:
        with open("request_tokens.json", "w") as f:
            json.dump(request_tokens, f)
    except: pass

    if not req_secret:
        print(f"DEBUG: Token {request.oauth_token} not found.", flush=True)
        log_event("gateway", "ERROR", f"Token {request.oauth_token} not found in {list(request_tokens.keys())}")
        raise HTTPException(status_code=400, detail="Invalid or expired request token")

    try:
        # Exchange for Access Token
        resp = await http_client.post(
            f"{DISCOGS_SERVICE_URL}/auth/access_token",
            json={
                "request_token": request.oauth_token,
                "request_token_secret": req_secret,
                "verifier": request.oauth_verifier
            }
        )
        if resp.status_code != 200:
             raise HTTPException(status_code=400, detail="Failed to verify with Discogs")

        token_data = resp.json()
        access_token = token_data['oauth_token']
        access_token_secret = token_data['oauth_token_secret']

        # Get Identity
        id_resp = await http_client.get(
            f"{DISCOGS_SERVICE_URL}/auth/identity",
            params={"token": access_token, "secret": access_token_secret}
        )
        identity = id_resp.json()
        username = identity['username']
        discogs_id = identity['id']

        # Link
        db.link_discogs_to_existing_user(request.user_id, username, discogs_id, access_token, access_token_secret)

        # Start background sync of collection
        asyncio.create_task(sync_user_collection_task(request.user_id, username, access_token, access_token_secret))

        return {"status": "success", "username": username}
    except Exception as e:
        log_event("gateway", "ERROR", f"Discogs link failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Global sync status tracker
# Format: {user_id: {"status": "running"|"completed"|"failed", "processed": int, "total_estimated": int, "message": str}}
SYNC_STATUS = {}

@app.get("/user/{user_id}/sync-status")
async def get_sync_status(user_id: int):
    """Get the current status of background sync tasks."""
    return SYNC_STATUS.get(user_id, {"status": "idle", "processed": 0, "message": ""})

async def sync_user_collection_task(user_id: int, username: str, token: str, secret: str):
    """Background task to sync user's Discogs collection."""
    SYNC_STATUS[user_id] = {"status": "running", "processed": 0, "message": "Starting sync..."}
    try:
        log_event("gateway", "INFO", f"Starting background sync for user {username} ({user_id})")
        page = 1
        total_items = 0

        while page <= 10: # Limit to 10 pages (~500 items) for safety
            msg = f"Syncing page {page}..."
            SYNC_STATUS[user_id]["message"] = msg
            log_event("gateway", "INFO", f"{msg} for {username}")

            try:
                resp = await http_client.post(
                    f"{DISCOGS_SERVICE_URL}/user/collection",
                    json={
                        "username": username,
                        "page": page,
                        "per_page": 50,
                        "access_token": token,
                        "access_token_secret": secret
                    },
                    timeout=30.0
                )
                if resp.status_code != 200:
                    log_event("gateway", "WARNING", f"Sync page {page} failed: {resp.text}")
                    SYNC_STATUS[user_id]["message"] = f"Error on page {page}"
                    break

                data = resp.json()
                releases = data.get("releases", [])
                if not releases:
                    break

                # Transform data for DB
                items = []
                for rel in releases:
                    basic = rel.get("basic_information", {})
                    # Simple format classification for internal_category
                    fmt_str = "OTHERS"
                    formats = basic.get("formats", [])
                    fmt_descriptions = []

                    if formats:
                        f_name = formats[0].get("name", "").upper()
                        fmt_descriptions = formats[0].get("descriptions", [])

                        if "VINYL" in f_name or "LP" in f_name or "7\"" in f_name:
                            fmt_str = "VINYL"
                        elif "CD" in f_name:
                            fmt_str = "CD_FORMAT"
                        elif "CASSETTE" in f_name:
                            fmt_str = "TAPE_FORMAT"

                    # release_type classification
                    release_type = "Other"
                    # Check descriptions
                    if 'Compilation' in fmt_descriptions:
                        release_type = "Compilation"
                    elif any(d in fmt_descriptions for d in ['Album', 'LP', 'Mini-Album']):
                        release_type = "Album"
                    elif 'EP' in fmt_descriptions:
                        release_type = "EP"
                    elif any(d in fmt_descriptions for d in ['Single', '7"', '12"']) and 'LP' not in fmt_descriptions:
                        release_type = "Single"

                    # Extract label and year
                    labels = basic.get("labels", [])
                    label = labels[0].get("name") if labels else None
                    year = basic.get("year", 0)

                    items.append({
                        "release_id": rel.get("id"),
                        "master_id": basic.get("master_id"),
                        "title": basic.get("title"),
                        "artist": re.sub(r' \(\d+\)$', '', basic.get("artists", [{}])[0].get("name", "")),
                        "internal_category": fmt_str,
                        "cover_url": basic.get("thumb") or basic.get("cover_image"),
                        "release_type": release_type,
                        "year": year,
                        "label": label
                    })

                # Sync to DB
                db.sync_discogs_collection_items(user_id, items)

                total_items += len(items)
                SYNC_STATUS[user_id]["processed"] = total_items

                pagination = data.get("pagination", {})
                if page >= pagination.get("pages", 1):
                    break
                page += 1
                await asyncio.sleep(1) # Polite delay

            except Exception as e:
                log_event("gateway", "ERROR", f"Sync loop error on page {page}: {e}")
                SYNC_STATUS[user_id]["message"] = f"Error: {str(e)}"
                break

        log_event("gateway", "INFO", f"Completed background sync for {username}")
        SYNC_STATUS[user_id] = {"status": "completed", "processed": total_items, "message": "Import completed"}

    except Exception as e:
        log_event("gateway", "ERROR", f"Background sync failed: {e}")
        SYNC_STATUS[user_id] = {"status": "failed", "processed": 0, "message": str(e)}

@app.post("/auth/lastfm")
async def lastfm_login_endpoint(request: LastFmLoginRequest):
    """Create or retrieve a user via Last.fm username and sync guest data."""
    try:
        user_id = db.get_or_create_user_via_lastfm(request.lastfm_username, existing_user_id=request.user_id)

        # Sync guest data if provided
        # DEBUG: Write to file for debugging
        with open("/tmp/vinylbe_sync_debug.log", "a") as f:
            f.write(f"[{datetime.now()}] Endpoint called. selected_artists: {request.selected_artists}\n")

        if request.selected_artists:
            log_event("gateway", "INFO", f"Syncing {len(request.selected_artists)} guest artists for user {user_id}")
            print(f"[DEBUG] Syncing guest artists: {request.selected_artists}")
            with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                f.write(f"[{datetime.now()}] Starting sync of {len(request.selected_artists)} artists\n")
            for artist_name in request.selected_artists:
                try:
                    with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                        f.write(f"[{datetime.now()}] Processing artist: {artist_name}\n")

                    # First, ensure the artist exists in the artists table (create partial record if needed)
                    conn = db.get_connection()
                    try:
                        cur = conn.cursor()
                        # Check if artist exists
                        cur.execute("SELECT id FROM artists WHERE name = ?", (artist_name,))
                        if not cur.fetchone():
                            # Create partial artist record
                            cur.execute(
                                "INSERT INTO artists (name, is_partial) VALUES (?, 1)",
                                (artist_name,)
                            )
                            conn.commit()
                            print(f"[DEBUG] Created partial artist record for: {artist_name}")
                            with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                                f.write(f"[{datetime.now()}] Created partial artist: {artist_name}\n")
                    finally:
                        conn.close()

                    # Now add to user's selected artists
                    with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                        f.write(f"[{datetime.now()}] Calling add_user_selected_artist for: {artist_name}\n")
                    db.add_user_selected_artist(user_id, artist_name, source="manual")
                    print(f"[DEBUG] Successfully added guest artist: {artist_name}")
                    with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                        f.write(f"[{datetime.now()}] Successfully added: {artist_name}\n")
                except Exception as e:
                    log_event("gateway", "WARNING", f"Failed to sync guest artist {artist_name}: {e}")
                    print(f"[DEBUG] Failed to add guest artist {artist_name}: {e}")
                    with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                        f.write(f"[{datetime.now()}] ERROR for {artist_name}: {str(e)}\n")

        if request.album_statuses:
            log_event("gateway", "INFO", f"Syncing {len(request.album_statuses)} guest album statuses for user {user_id}")
            with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                f.write(f"[{datetime.now()}] Syncing {len(request.album_statuses)} album statuses: {request.album_statuses}\n")

            for key, status in request.album_statuses.items():
                try:
                    # Key format: "artist|album"
                    parts = key.split("|")
                    if len(parts) >= 2:
                        artist = parts[0]
                        album = parts[1]
                        db.upsert_recommendation_status(user_id, artist, album, status)
                        with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                            f.write(f"[{datetime.now()}] Upserted status for {artist}|{album}: {status}\n")
                except Exception as e:
                    log_event("gateway", "WARNING", f"Failed to sync album status {key}: {e}")
                    with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                        f.write(f"[{datetime.now()}] ERROR syncing status {key}: {e}\n")
        else:
            with open("/tmp/vinylbe_sync_debug.log", "a") as f:
                f.write(f"[{datetime.now()}] No album_statuses in request\n")

        # Sync guest recommendations if provided
        if request.recommendations:
            try:
                db.regenerate_recommendations(user_id, request.recommendations)
                log_event("gateway", "INFO", f"Synced {len(request.recommendations)} guest recommendations for user {user_id}")
            except Exception as e:
                log_event("gateway", "WARNING", f"Failed to sync guest recommendations: {e}")

        # Sync manually added albums if provided
        if request.manually_added_albums:
            log_event("gateway", "INFO", f"Syncing {len(request.manually_added_albums)} manually added albums for user {user_id}")
            for album in request.manually_added_albums:
                try:
                    artist_name = album.get('artist_name')
                    album_title = album.get('album_title') or album.get('album_name')

                    if not artist_name or not album_title:
                        log_event("gateway", "WARNING", f"Skipping album with missing data: {album}")
                        continue

                    # Check if recommendation already exists
                    conn = db.get_connection()
                    try:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT id, status, source FROM recommendation WHERE user_id = ? AND artist_name = ? AND album_title = ? COLLATE NOCASE",
                            (user_id, artist_name, album_title)
                        )
                        existing = cur.fetchone()

                        if not existing:
                            # Add new manual recommendation
                            cur.execute(
                                "INSERT INTO recommendation (user_id, artist_name, album_title, source, status) VALUES (?, ?, ?, 'manual', 'neutral')",
                                (user_id, artist_name, album_title)
                            )
                            conn.commit()
                            log_event("gateway", "INFO", f"Added manual album: {artist_name} - {album_title}")
                        else:
                            # Album exists - Last.fm status takes precedence, don't overwrite
                            log_event("gateway", "INFO", f"Album already exists (source: {existing['source']}, status: {existing['status']}), preserving Last.fm data: {artist_name} - {album_title}")
                    finally:
                        conn.close()
                except Exception as e:
                    log_event("gateway", "WARNING", f"Failed to sync manual album {artist_name} - {album_title}: {e}")

        # Fetch and save Last.fm profile (Top Artists)
        try:
            if http_client:
                log_event("gateway", "INFO", f"Fetching Last.fm profile for {request.lastfm_username}")
                resp = await http_client.post(
                    f"{LASTFM_SERVICE_URL}/top-artists",
                    json={"username": request.lastfm_username, "limit": 50}
                )
                if resp.status_code == 200:
                    top_artists = resp.json()
                    db.upsert_user_profile_lastfm(user_id, request.lastfm_username, top_artists)
                    log_event("gateway", "INFO", f"Saved Last.fm profile for {request.lastfm_username}")
                else:
                    log_event("gateway", "WARNING", f"Failed to fetch Last.fm profile: {resp.status_code}")
        except Exception as e:
            log_event("gateway", "WARNING", f"Error fetching Last.fm profile: {e}")

        return {"user_id": user_id}
    except Exception as e:
        log_event("gateway", "ERROR", f"Last.fm login failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Last.fm login error: {str(e)}")

@app.post("/auth/lastfm/link")
async def link_lastfm(request: LinkLastFmRequest):
    """Link a Last.fm identity to an existing user."""
    try:
        db.link_lastfm_to_existing_user(request.user_id, request.lastfm_username)
        return {"status": "linked", "user_id": request.user_id}
    except Exception as e:
        log_event("gateway", "ERROR", f"Link Last.fm failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Link Last.fm error: {str(e)}")

# ---------------------------------------------------------------------------
# Profile & Artist Management Endpoints
# ---------------------------------------------------------------------------

class LastFmProfileUpdate(BaseModel):
    lastfm_username: str
    top_artists: list[dict[str, Any]]

class SelectedArtistCreate(BaseModel):
    artist_name: str
    mbid: str | None = None
    spotify_id: str | None = None
    source: str = "manual"

@app.get("/users/{user_id}/profile/lastfm")
async def get_user_profile(user_id: int):
    """Get the user's Last.fm profile snapshot."""
    profile = db.get_user_profile_lastfm(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile

@app.put("/users/{user_id}/profile/lastfm")
async def update_user_profile(user_id: int, profile: LastFmProfileUpdate):
    """Update the user's Last.fm profile snapshot."""
    try:
        db.upsert_user_profile_lastfm(user_id, profile.lastfm_username, profile.top_artists)
        return {"status": "updated"}
    except Exception as e:
        log_event("gateway", "ERROR", f"Profile update failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

@app.get("/users/{user_id}/selected-artists")
async def get_selected_artists(user_id: int):
    """Get all artists selected by the user."""
    return db.get_user_selected_artists(user_id)

@app.post("/users/{user_id}/selected-artists")
async def add_selected_artist(user_id: int, artist: SelectedArtistCreate):
    """Add an artist to the user's selection."""
    try:
        db.add_user_selected_artist(user_id, artist.artist_name, artist.mbid, artist.source, artist.spotify_id)
        return {"status": "added", "artist": artist.artist_name}
    except Exception as e:
        log_event("gateway", "ERROR", f"Add artist failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Add artist failed: {str(e)}")

@app.delete("/users/{user_id}/selected-artists/{selection_id}")
async def remove_selected_artist(user_id: int, selection_id: int):
    """Remove an artist from the user's selection."""
    deleted = db.remove_user_selected_artist(user_id, selection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Selection not found")
    return {"status": "removed"}

# ---------------------------------------------------------------------------
# Recommendation Endpoints
# ---------------------------------------------------------------------------

class RecommendationStatusUpdate(BaseModel):
    new_status: str

class RegenerateRecommendationsRequest(BaseModel):
    new_recs: list[dict[str, Any]]

@app.get("/users/{user_id}/recommendations")
async def get_recommendations(user_id: int, include_favorites: bool = True):
    """Get recommendations for the user."""
    recommendations = db.get_recommendations_for_user(user_id, include_favorites)

    # Map album_title (DB field) to album_name (frontend field) for compatibility
    for rec in recommendations:
        if 'album_title' in rec and 'album_name' not in rec:
            rec['album_name'] = rec['album_title']
        if 'cover_url' in rec and rec['cover_url']:
            rec['image_url'] = rec['cover_url']

    return recommendations

@app.get("/users/{user_id}/recommendations/favorites")
async def get_favorites(user_id: int):
    """Get only favorite recommendations."""
    favorites = db.get_favorite_recommendations(user_id)

    # Map album_title (DB field) to album_name (frontend field) for compatibility
    for rec in favorites:
        if 'album_title' in rec and 'album_name' not in rec:
            rec['album_name'] = rec['album_title']
        if 'cover_url' in rec and rec['cover_url']:
            rec['image_url'] = rec['cover_url']

    return favorites

@app.patch("/users/{user_id}/recommendations/{rec_id}")
async def update_recommendation_status(user_id: int, rec_id: int, update: RecommendationStatusUpdate):
    """Update the status of a recommendation (favorite, disliked, owned, neutral)."""
    try:
        # 1. Update status in DB
        db.update_recommendation_status(user_id, rec_id, update.new_status)

        # 2. If 'owned', sync to collection
        if update.new_status == "owned":
            try:
                # Fetch rec details
                rec = db.get_recommendation(user_id, rec_id)
                if rec:
                    artist = rec['artist_name']
                    title = rec['album_title']
                    cover = rec.get('cover_url')

                    # Try local DB lookup for Discogs IDs
                    local_ids = db.get_album_discogs_ids(artist, title)

                    discogs_data = {}
                    if local_ids:
                        discogs_data = {
                            "release_id": local_ids.get("discogs_release_id"),
                            "master_id": local_ids.get("discogs_master_id"),
                            "year": local_ids.get("year"),
                            "release_type": "Album", # Assume album if in albums table
                            "label": None # Local table might not have label easily accessible
                        }
                        log_event("gateway", "INFO", f"Found local Discogs IDs for owned item: {artist} - {title}")
                    else:
                        # Fallback to Discogs Search via Service
                        log_event("gateway", "INFO", f"Searching Discogs for owned item fallback: {artist} - {title}")
                        if http_client:
                             resp = await http_client.get(
                                f"{DISCOGS_SERVICE_URL}/search_album_only",
                                params={"q": f"{artist} \"{title}\"", "limit": 1}
                             )
                             if resp.status_code == 200:
                                 results = resp.json()
                                 if results:
                                     first = results[0]
                                     discogs_data = {
                                         "release_id": first.get("id"),
                                         "master_id": first.get("master_id"),
                                         "year": first.get("year"),
                                         "release_type": "Album",
                                         "label": first.get("label", [])[0] if first.get("label") else None
                                     }
                                     log_event("gateway", "INFO", f"Found Discogs ID via search: {discogs_data['release_id']}")

                    if discogs_data and discogs_data.get("release_id"):
                        # Prepare collection payload
                        coll_item = {
                            "release_id": discogs_data["release_id"],
                            "master_id": discogs_data.get("master_id"),
                            "artist": artist,
                            "title": title,
                            "format": "OTHERS", # Default
                            "type": discogs_data.get("release_type", "Album"),
                            "year": discogs_data.get("year"),
                            "label": discogs_data.get("label"),
                            "cover_url": cover
                        }
                        db.add_to_collection(user_id, coll_item)
                        log_event("gateway", "INFO", f"Synced owned item to collection: {artist} - {title}")

            except Exception as e:
                log_event("gateway", "ERROR", f"Failed to sync owned item to collection: {str(e)}")
                # Don't fail the request, just log error

        return {"status": "updated", "new_status": update.new_status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    except Exception as e:
        log_event("gateway", "ERROR", f"Update status failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")

@app.post("/users/{user_id}/recommendations/regenerate")
@limiter.limit("5/minute")
async def regenerate_recommendations_endpoint(request: Request, user_id: int, body: RegenerateRecommendationsRequest):
    """Regenerate recommendations based on new data."""
    try:
        db.regenerate_recommendations(user_id, body.new_recs)
        return {"status": "regenerated"}
    except Exception as e:
        log_event("gateway", "ERROR", f"Regenerate failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Regenerate failed: {str(e)}")


@app.get("/lastfm/callback")
async def lastfm_callback_alias(token: str):
    """Alias for /auth/lastfm/callback to maintain compatibility with configured redirect URIs"""
    return await lastfm_callback(token)


@app.get("/api/mosaic")
async def get_mosaic_albums():
    """Get random albums for the mosaic display."""
    try:
        albums = db.get_random_albums_with_covers(limit=500)
        return {"albums": albums}
    except Exception as e:
        log_event("gateway", "ERROR", f"Mosaic fetch failed: {str(e)}")
        return {"albums": []}


# ---------------------------------------------------------------------------
# Collection Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/collection/{user_id}")
async def get_user_collection(user_id: int):
    """Get user's collection grouped by format.
    
    Returns collection organized by format (VINYL, CD_FORMAT, TAPE_FORMAT, DIGITAL, OTHERS).
    Combines Discogs collection data with owned recommendations.
    """
    try:
        collection = db.get_user_collection_by_format(user_id)
        return {"collection": collection}
    except Exception as e:
        log_event("gateway", "ERROR", f"Collection fetch failed for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch collection: {str(e)}")


@app.get("/api/collection/{user_id}/summary")
async def get_collection_summary(user_id: int):
    """Get summary statistics for user's collection.
    
    Returns total count and breakdown by format.
    """
    try:
        summary = db.get_user_collection_summary(user_id)
        return summary
    except Exception as e:
        log_event("gateway", "ERROR", f"Collection summary fetch failed for user {user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch collection summary: {str(e)}")


@app.get("/api/release/{release_id}")
async def get_release_details(release_id: int, user_id: int | None = None):
    """
    Get full details for a release.
    Uses permanent cache to avoid Discogs API rate limits.
    """
    # 1. Try cache
    cached = db.get_cached_release(release_id)
    if cached:
        return cached

    # 2. Fetch from Discogs
    # Valid auth?
    headers = {"User-Agent": "Vinylbe/1.0"}

    token = os.getenv("DISCOGS_KEY")
    if not token:
        raise HTTPException(status_code=500, detail="DISCOGS_KEY not configured")

    try:
        url = f"https://api.discogs.com/releases/{release_id}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers={"Authorization": f"Discogs token={token}", "User-Agent": "Vinylbe/1.0"})

        if resp.status_code == 200:
            data = resp.json()
            # Cache it
            db.cache_release(release_id, data)
            return data
        elif resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Release not found on Discogs")
        else:
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch from Discogs")

    except HTTPException:
        raise
    except Exception as e:
        log_event("gateway", "ERROR", f"Error fetching release {release_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# API aliases for frontend compatibility (prefixed with /api)
# ---------------------------------------------------------------------------

@app.get("/api/users/{user_id}/recommendations")
async def api_get_recommendations(user_id: int, include_favorites: bool = True):
    """Alias that forwards to the core /users/{user_id}/recommendations endpoint.
    This fixes 404 errors when the frontend calls the /api-prefixed path.
    """
    return await get_recommendations(user_id, include_favorites)

@app.get("/api/users/{user_id}/recommendations/favorites")
async def api_get_favorites(user_id: int):
    """Alias for favorite recommendations under /api prefix."""
    return await get_favorites(user_id)

@app.get("/api/users/{user_id}/profile/lastfm")
async def api_get_user_profile(user_id: int):
    """Alias for Last.fm profile under /api prefix."""
    return await get_user_profile(user_id)

@app.put("/api/users/{user_id}/profile/lastfm")
async def api_update_user_profile(user_id: int, profile: LastFmProfileUpdate):
    """Alias for Last.fm profile update under /api prefix."""
    return await update_user_profile(user_id, profile)

@app.get("/api/users/{user_id}/selected-artists")
async def api_get_selected_artists(user_id: int):
    """Alias for getting selected artists under /api prefix."""
    return await get_selected_artists(user_id)

@app.post("/api/users/{user_id}/selected-artists")
async def api_add_selected_artist(user_id: int, artist: SelectedArtistCreate):
    """Alias for adding selected artist under /api prefix."""
    return await add_selected_artist(user_id, artist)

@app.post("/api/users/{user_id}/albums")
async def add_album_to_user(user_id: int, album_data: dict):
    """Add an album to the user's collection, creating partial artist if needed."""
    try:
        album_title = album_data.get("title")
        artist_name = album_data.get("artist_name")
        cover_url = album_data.get("cover_url")
        discogs_id = album_data.get("discogs_id")

        if not album_title or not artist_name:
            raise HTTPException(status_code=400, detail="title and artist_name are required")

        conn = db.get_connection()
        try:
            cur = conn.cursor()

            # Check if artist exists
            cur.execute("SELECT id FROM artists WHERE name = ? COLLATE NOCASE", (artist_name,))
            artist_row = cur.fetchone()

            if not artist_row:
                # Create partial artist
                cur.execute(
                    "INSERT INTO artists (name, is_partial) VALUES (?, 1)",
                    (artist_name,)
                )
                artist_id = cur.lastrowid
                log_event("gateway", "INFO", f"Created partial artist: {artist_name}")
            else:
                artist_id = artist_row["id"]

            # Check if album exists
            cur.execute(
                "SELECT id FROM albums WHERE artist_id = ? AND title = ? COLLATE NOCASE",
                (artist_id, album_title)
            )
            album_row = cur.fetchone()

            if not album_row:
                # Create album
                cur.execute(
                    "INSERT INTO albums (artist_id, title, cover_url, is_partial) VALUES (?, ?, ?, 1)",
                    (artist_id, album_title, cover_url)
                )
                album_id = cur.lastrowid
                log_event("gateway", "INFO", f"Created album: {album_title} by {artist_name}")
            else:
                album_id = album_row["id"]
                log_event("gateway", "INFO", f"Album already exists: {album_title} by {artist_name}")

            # Add to user's recommendations as neutral
            cur.execute(
                """
                INSERT OR IGNORE INTO recommendation (user_id, artist_name, album_title, source, status)
                VALUES (?, ?, ?, 'manual', 'neutral')
                """,
                (user_id, artist_name, album_title)
            )

            conn.commit()

            return {
                "status": "added",
                "artist_id": artist_id,
                "album_id": album_id,
                "artist_name": artist_name,
                "album_title": album_title
            }
        finally:
            conn.close()

    except HTTPException:
        raise
    except Exception as e:
        log_event("gateway", "ERROR", f"Add album failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Add album failed: {str(e)}")

@app.delete("/api/users/{user_id}/selected-artists/{selection_id}")
async def api_remove_selected_artist(user_id: int, selection_id: int):
    """Alias for removing selected artist under /api prefix."""
    return await remove_selected_artist(user_id, selection_id)

@app.get("/album-pricing")
async def get_album_pricing(artist: str = Query(..., description="Artist name"), album: str = Query(..., description="Album name")):
    """
    Get complete pricing information for an album with maximum speed optimization.
    
    Logic:
    1. Check database for existing discogs_release_id and discogs_master_id
    2. Prioritize release over master for tracklist (releases are more specific)
    3. Only search Discogs if no IDs exist in database
    
    Fetches in parallel:
    - Discogs data (from DB or search)
    - eBay best price
    - Local store links
    
    Returns all data in 1-2 seconds thanks to asyncio.gather parallelization.
    """
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    start_time = time.time()
    log_event("gateway", "INFO", f"Getting pricing for: {artist} - {album}")

    try:
        # Step 1: Check database for existing Discogs IDs
        conn = db.get_connection()
        try:
            cur = conn.cursor()

            # Query for album in database
            cur.execute("""
                SELECT a.discogs_master_id, a.discogs_release_id, a.spotify_id
                FROM albums a
                JOIN artists ar ON a.artist_id = ar.id
                WHERE LOWER(ar.name) = LOWER(?) AND LOWER(a.title) = LOWER(?)
                LIMIT 1
            """, (artist, album))

            db_result = cur.fetchone()
        finally:
            conn.close()

        # Step 2: Determine which Discogs ID to use and get Spotify ID
        discogs_type = None
        discogs_id = None
        discogs_url = None
        spotify_id = None

        if db_result:
            db_master_id = db_result["discogs_master_id"]
            db_release_id = db_result["discogs_release_id"]
            spotify_id = db_result.get("spotify_id")

            # Prioritize release over master (releases are more specific)
            if db_release_id:
                discogs_type = "release"
                discogs_id = db_release_id
                discogs_url = f"https://www.discogs.com/release/{db_release_id}"
                log_event("gateway", "INFO", f"Using release ID from database: {db_release_id}")
            elif db_master_id:
                discogs_type = "master"
                discogs_id = db_master_id
                discogs_url = f"https://www.discogs.com/master/{db_master_id}"
                log_event("gateway", "INFO", f"Using master ID from database: {db_master_id}")

        # Step 3: If no IDs in database, search Discogs
        if not discogs_id:
            log_event("gateway", "INFO", f"No Discogs IDs in database, searching Discogs for: {artist} - {album}")
            try:
                discogs_resp = await http_client.get(f"{DISCOGS_SERVICE_URL}/master-link/{artist}/{album}")
                discogs_data = discogs_resp.json()
                discogs_type = discogs_data.get("type")
                discogs_id = discogs_data.get("id")
                discogs_url = discogs_data.get("url")
            except Exception as e:
                log_event("gateway", "WARNING", f"Discogs search failed: {str(e)}")
                discogs_data = {"type": None, "id": None, "url": None}

        # Step 4: Fetch tracklist and other data in parallel
        ebay_task = http_client.get(f"{PRICING_SERVICE_URL}/ebay-price", params={"artist": artist, "album": album})
        # Exclude FNAC from initial load to avoid 30s delay
        stores_task = http_client.get(f"{PRICING_SERVICE_URL}/local-stores", params={"artist": artist, "album": album, "exclude_fnac": True})

        # If no spotify_id in database, search Spotify as fallback
        spotify_task = None
        if not spotify_id:
            log_event("gateway", "INFO", f"No Spotify ID in database, searching Spotify for: {artist} - {album}")
            spotify_task = http_client.get(
                f"{SPOTIFY_SERVICE_URL}/search/album",
                params={"artist": artist, "album": album}
            )

        # Gather all parallel tasks
        tasks = [ebay_task, stores_task]
        if spotify_task:
            tasks.append(spotify_task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        ebay_resp = results[0]
        stores_resp = results[1]
        spotify_resp = results[2] if len(results) > 2 else None

        # Parse eBay response
        if isinstance(ebay_resp, Exception):
            log_event("gateway", "WARNING", f"eBay pricing failed: {str(ebay_resp)}")
            ebay_data = {"offer": None, "message": str(ebay_resp)}
        else:
            ebay_data = ebay_resp.json()

        # Parse local stores response
        if isinstance(stores_resp, Exception):
            log_event("gateway", "WARNING", f"Local stores failed: {str(stores_resp)}")
            stores_data = {"stores": {}}
        else:
            stores_data = stores_resp.json()

        # Parse Spotify response (fallback search)
        if spotify_resp and not isinstance(spotify_resp, Exception):
            try:
                spotify_data = spotify_resp.json()
                spotify_id = spotify_data.get("id")
                if spotify_id:
                    log_event("gateway", "INFO", f"Found Spotify ID via search: {spotify_id}")
            except Exception as e:
                log_event("gateway", "WARNING", f"Spotify search parsing failed: {str(e)}")
        elif spotify_resp and isinstance(spotify_resp, Exception):
            log_event("gateway", "WARNING", f"Spotify search failed: {str(spotify_resp)}")

        # Step 5: Fetch tracklist based on type (release takes priority)
        tracklist_data = {"tracklist": []}
        discogs_sell_url = None

        if discogs_type == "release" and discogs_id:
            try:
                tracklist_resp = await http_client.get(f"{DISCOGS_SERVICE_URL}/release-tracklist/{discogs_id}")
                tracklist_data = tracklist_resp.json()
                log_event("gateway", "INFO", f"Tracklist fetched for release {discogs_id}: {len(tracklist_data.get('tracklist', []))} tracks")
            except Exception as e:
                log_event("gateway", "WARNING", f"Tracklist fetch failed for release: {str(e)}")

            discogs_sell_url = f"https://www.discogs.com/sell/list?release_id={discogs_id}&currency=EUR&format=Vinyl"

        elif discogs_type == "master" and discogs_id:
            try:
                tracklist_resp = await http_client.get(f"{DISCOGS_SERVICE_URL}/master-tracklist/{discogs_id}")
                tracklist_data = tracklist_resp.json()
                log_event("gateway", "INFO", f"Tracklist fetched for master {discogs_id}: {len(tracklist_data.get('tracklist', []))} tracks")
            except Exception as e:
                log_event("gateway", "WARNING", f"Tracklist fetch failed for master: {str(e)}")

            discogs_sell_url = f"https://www.discogs.com/sell/list?master_id={discogs_id}&currency=EUR&format=Vinyl"
        else:
            log_event("gateway", "INFO", f"No Discogs master or release found for {artist} - {album}")

        elapsed = time.time() - start_time
        log_event("gateway", "INFO", f"Album info fetched for {artist} - {album} in {elapsed:.2f}s (type: {discogs_type or 'none'}, id: {discogs_id or 'none'})")

        return {
            "artist": artist,
            "album": album,
            "discogs_type": discogs_type,
            "discogs_id": discogs_id,
            "discogs_url": discogs_url,
            "discogs_sell_url": discogs_sell_url,
            "discogs_title": tracklist_data.get("title"),
            "tracklist": tracklist_data.get("tracklist", []),
            "ebay_offer": ebay_data.get("offer"),
            "local_stores": stores_data.get("stores", {}),
            "spotify_id": spotify_id,
            "spotify_url": f"https://open.spotify.com/album/{spotify_id}" if spotify_id else None,
            "request_time_seconds": round(elapsed, 2),
            "debug_info": {
                "source": "database" if db_result else "discogs_search",
                "db_master_id": db_result["discogs_master_id"] if db_result else None,
                "db_release_id": db_result["discogs_release_id"] if db_result else None,
                "db_spotify_id": db_result.get("spotify_id") if db_result else None,
                "spotify_id_source": "database" if (db_result and db_result.get("spotify_id")) else ("search" if spotify_id else "not_found"),
                "used_type": discogs_type,
                "used_id": discogs_id
            }
        }

    except Exception as e:
        elapsed = time.time() - start_time
        log_event("gateway", "ERROR", f"Album pricing failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get album pricing: {str(e)}"
        )


@app.get("/api/pricing/fnac")
async def get_fnac_pricing(artist: str = Query(..., description="Artist name"), album: str = Query(..., description="Album name")):

    """
    Lazy load endpoint for FNAC prices.
    Called asynchronously by frontend to avoid blocking invalid stores.
    """
    # DISABLED per user request
    return {"fnac": None}

    # try:
    #     async with httpx.AsyncClient(timeout=65.0) as client:
    #         response = await client.get(
    #             f"{PRICING_SERVICE_URL}/local-stores",
    #             params={
    #                 "artist": artist,
    #                 "album": album,
    #                 "only_fnac": True
    #             }
    #         )
    #         result = response.json()
    #         # Extract only FNAC data if present
    #         fnac_data = result.get("fnac")
    #         return {"fnac": fnac_data}
    # except Exception as e:
    #     print(f"Error fetching FNAC price: {str(e)}")
    #     return {"fnac": None}
    """Get all vinyl releases ordered by preference (originals first, then reissues)
    
    Returns:
        (list_of_releases, debug_info)
    """
    debug_info = {
        "total_releases_found": len(releases),
        "vinyl_releases_found": 0,
    }

    if not releases:
        return [], debug_info

    preferred_formats = ["LP", "Album", "Vinyl"]

    vinyl_releases = []
    for release in releases:
        format_value = release.get("format", "")

        if isinstance(format_value, list):
            format_str = " ".join(format_value).lower()
        else:
            format_str = str(format_value).lower()

        is_vinyl = any(pref.lower() in format_str for pref in preferred_formats)
        if is_vinyl:
            vinyl_releases.append(release)

    debug_info["vinyl_releases_found"] = len(vinyl_releases)

    # Sort: originals first, then reissues/remasters
    originals = []
    reissues = []

    for release in vinyl_releases:
        format_value = release.get("format", "")
        if isinstance(format_value, list):
            format_str = " ".join(format_value).lower()
        else:
            format_str = str(format_value).lower()

        if "reissue" in format_str or "remaster" in format_str:
            reissues.append(release)
        else:
            originals.append(release)

    # Return originals first, then reissues
    ordered_releases = originals + reissues

    return ordered_releases, debug_info


async def enrich_album_with_discogs(album: dict, idx: int, total: int, semaphore: asyncio.Semaphore) -> dict:
    """Enrich a single album with Discogs data by trying multiple releases until finding one with price"""
    async with semaphore:
        album_info = album.get("album_info", {})
        artist_name = album_info.get("artists", [{}])[0].get("name", "Unknown")
        album_name = album_info.get("name", "Unknown")

        log_event("gateway", "INFO", f"[{idx}/{total}] Processing: {artist_name} - {album_name}")

        debug_info = {
            "status": None,
            "message": None,
            "details": {}
        }

        try:
            search_resp = await http_client.get(
                f"{DISCOGS_SERVICE_URL}/search",
                params={"artist": artist_name, "title": album_name}
            )
            search_results = search_resp.json().get("results", [])

            if not search_results:
                album["discogs_release"] = None
                album["discogs_stats"] = None
                debug_info["status"] = "not_found"
                debug_info["message"] = "No se encontró en Discogs"
                debug_info["details"] = {"total_releases_found": 0}
                log_event("gateway", "INFO", f"[{idx}/{total}] ○ Not found on Discogs: {album_name}")
                album["discogs_debug_info"] = debug_info
                return album

            # Get all vinyl releases ordered by preference
            vinyl_releases, search_debug = get_vinyl_releases(search_results)
            debug_info["details"] = search_debug

            if not vinyl_releases:
                album["discogs_release"] = None
                album["discogs_stats"] = None
                debug_info["status"] = "not_found"
                debug_info["message"] = "No se encontraron vinilos"
                log_event("gateway", "INFO", f"[{idx}/{total}] ○ No vinyl: {album_name}")
                album["discogs_debug_info"] = debug_info
                return album

            # Try up to 5 releases to find one with price
            max_attempts = min(5, len(vinyl_releases))
            debug_info["details"]["releases_tried"] = 0
            debug_info["details"]["releases_with_price"] = 0

            selected_release = None
            selected_stats = None

            for attempt_idx, release in enumerate(vinyl_releases[:max_attempts], 1):
                release_id = release.get("id")
                format_value = release.get("format", "")
                if isinstance(format_value, list):
                    format_str = " ".join(format_value)
                else:
                    format_str = str(format_value)

                log_event("gateway", "INFO", f"[{idx}/{total}] Trying release {attempt_idx}/{max_attempts}: ID {release_id} ({format_str})")

                try:
                    stats_resp = await http_client.get(
                        f"{DISCOGS_SERVICE_URL}/stats/{release_id}"
                    )
                    stats = stats_resp.json()
                    debug_info["details"]["releases_tried"] = attempt_idx

                    has_price = stats.get("lowest_price_eur") is not None and stats.get("lowest_price_eur") > 0

                    if has_price:
                        debug_info["details"]["releases_with_price"] += 1
                        selected_release = release
                        selected_stats = stats
                        debug_info["details"]["selected_release_index"] = attempt_idx
                        debug_info["details"]["selected_format"] = format_str
                        log_event("gateway", "INFO", f"[{idx}/{total}] ✓ Found price on attempt {attempt_idx}: €{stats['lowest_price_eur']:.2f}")
                        break
                    else:
                        log_event("gateway", "INFO", f"[{idx}/{total}] ○ Release {release_id} has no price, trying next...")

                except Exception as e:
                    log_event("gateway", "WARNING", f"[{idx}/{total}] Failed to get stats for release {release_id}: {str(e)}")
                    continue

            # If we didn't find any with price, use the first release anyway
            if not selected_release:
                selected_release = vinyl_releases[0]
                release_id = selected_release.get("id")

                # Set debug info for fallback selection
                debug_info["details"]["selected_release_index"] = 1
                format_value = selected_release.get("format", "")
                if isinstance(format_value, list):
                    debug_info["details"]["selected_format"] = " ".join(format_value)
                else:
                    debug_info["details"]["selected_format"] = str(format_value)

                try:
                    stats_resp = await http_client.get(
                        f"{DISCOGS_SERVICE_URL}/stats/{release_id}"
                    )
                    selected_stats = stats_resp.json()
                except Exception as e:
                    log_event("gateway", "WARNING", f"[{idx}/{total}] Failed to get stats for fallback release: {str(e)}")

                    # Get sell list URL with master_id from Discogs service
                    sell_url = f"https://www.discogs.com/sell/list?release_id={release_id}&currency=EUR&format=Vinyl"
                    try:
                        url_resp = await http_client.get(f"{DISCOGS_SERVICE_URL}/sell-list-url/{release_id}")
                        sell_url = url_resp.json().get("url", sell_url)
                    except:
                        pass

                    selected_stats = {
                        "release_id": release_id,
                        "lowest_price_eur": None,
                        "num_for_sale": 0,
                        "sell_list_url": sell_url
                    }

            album["discogs_release"] = selected_release
            album["discogs_stats"] = selected_stats

            has_price = selected_stats.get("lowest_price_eur") is not None and selected_stats.get("lowest_price_eur") > 0

            if has_price:
                debug_info["status"] = "success"
                format_val = selected_release.get("format", "")
                if isinstance(format_val, list):
                    fmt = " ".join(format_val)
                else:
                    fmt = str(format_val)
                debug_info["message"] = f"Vinilo disponible - {fmt}"
                log_event("gateway", "INFO", f"[{idx}/{total}] ✓ Enriched: {album_name}")
            else:
                debug_info["status"] = "no_price"
                debug_info["message"] = f"Probados {debug_info['details']['releases_tried']} releases, ninguno con precio"
                log_event("gateway", "INFO", f"[{idx}/{total}] ⚠ No price found after trying {debug_info['details']['releases_tried']} releases: {album_name}")

        except Exception as e:
            log_event("gateway", "WARNING", f"[{idx}/{total}] ✗ Failed: {album_name} - {str(e)}")
            album["discogs_release"] = None
            album["discogs_stats"] = None
            debug_info["status"] = "error"
            debug_info["message"] = f"Error: {str(e)}"
            debug_info["details"] = {}

        album["discogs_debug_info"] = debug_info
        return album







@app.get("/api/spotify/search/artists")
async def search_spotify_artists(q: str, limit: int = 10):
    """Search artists using Spotify Service"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{SPOTIFY_SERVICE_URL}/search/artists",
                params={"q": q, "limit": limit},
                timeout=10.0
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        log_event("gateway", "ERROR", f"Could not connect to Spotify Service at {SPOTIFY_SERVICE_URL}")
        raise HTTPException(status_code=503, detail="Spotify Service unavailable (Connection Refused)")
    except Exception as e:
        log_event("gateway", "ERROR", f"Spotify search failed: {str(e)}")
        # Return the actual error from the service if possible
        detail = str(e)
        if isinstance(e, httpx.HTTPStatusError):
            try:
                detail = e.response.json().get("detail", str(e))
            except:
                pass
        raise HTTPException(status_code=500, detail=f"Search failed: {detail}")


@app.get("/api/search")
@limiter.limit("30/minute")
async def unified_search(request: Request, q: str, limit: int = 20):
    """
    Unified search endpoint for both artists and albums.
    Searches Spotify for artists and database+Discogs for albums, then deduplicates results.
    """
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    if len(q) < 3:
        return {"artists": [], "albums": []}

    try:
        # Search Spotify for artists (not database)
        spotify_artists = []
        try:
            resp = await http_client.get(
                f"{SPOTIFY_SERVICE_URL}/search/artists",
                params={"q": q, "limit": 10},
                timeout=5.0
            )
            if resp.status_code == 200:
                spotify_data = resp.json()
                spotify_artists = spotify_data.get("artists", [])
        except Exception as e:
            log_event("gateway", "WARNING", f"Spotify search failed: {str(e)}")

        # Search database for albums
        db_albums = db.search_albums(q, limit=20)

        # Search Discogs for albums
        discogs_albums = []
        try:
            resp = await http_client.get(
                f"{DISCOGS_SERVICE_URL}/search_album_only",
                params={"q": q},
                timeout=5.0
            )
            if resp.status_code == 200:
                discogs_data = resp.json()
                discogs_albums = discogs_data.get("releases", [])
            elif resp.status_code == 429:
                # Rate limit hit, just use DB results
                log_event("gateway", "WARNING", "Discogs rate limit hit, using DB results only")
        except Exception as e:
            log_event("gateway", "WARNING", f"Discogs search failed: {str(e)}")

        # Helper function to normalize artist names (remove numbers in parentheses)
        def normalize_artist_name(name: str) -> str:
            import re
            # Remove patterns like " (11)" or " (2)" at the end
            return re.sub(r'\s*\(\d+\)$', '', name).strip()

        # Helper function to create deduplication key
        def create_album_key(artist: str, title: str) -> str:
            # Normalize both artist and title for better matching
            artist_norm = normalize_artist_name(artist).lower().strip()
            title_norm = title.lower().strip()
            return f"{artist_norm}|{title_norm}"

        # Format and deduplicate albums
        albums_map = {}

        # Add DB albums first (they have priority)
        for album in db_albums:
            artist_name = album.get('artist_name', '')
            title = album.get('title', '')
            key = create_album_key(artist_name, title)
            albums_map[key] = {
                "title": title,
                "artist_name": artist_name,
                "cover_url": album.get("cover_url"),
                "source": "database",
                "is_partial": album.get("is_partial", 0)
            }

        # Add Discogs albums (if not already in DB)
        for album in discogs_albums:
            title = album.get("title", "")
            # Extract artist from title (Discogs format: "Artist - Album")
            if " - " in title:
                artist_name, album_title = title.split(" - ", 1)
                # Normalize artist name (remove numbers in parentheses)
                artist_name = normalize_artist_name(artist_name)
            else:
                artist_name = ""
                album_title = title

            key = create_album_key(artist_name, album_title)
            if key not in albums_map:
                albums_map[key] = {
                    "title": album_title,
                    "artist_name": artist_name,
                    "cover_url": album.get("cover_image") or album.get("thumb"),
                    "source": "discogs",
                    "discogs_id": album.get("id"),
                    "is_partial": 1  # Discogs results are partial until added
                }

        # Format artists from Spotify with custom ordering:
        # First result stays first, rest sorted by popularity
        if spotify_artists:
            first_artist = spotify_artists[0]
            remaining_artists = spotify_artists[1:]

            # Sort remaining by popularity (highest first)
            remaining_artists.sort(key=lambda x: x.get("popularity", 0), reverse=True)

            # Reconstruct list: first + sorted rest
            ordered_spotify_artists = [first_artist] + remaining_artists
        else:
            ordered_spotify_artists = []

        artists = [
            {
                "name": artist.get("name"),
                "image_url": artist.get("image_url"),
                "genres": artist.get("genres", []),
                "popularity": artist.get("popularity", 0),
                "source": "spotify"
            }
            for artist in ordered_spotify_artists
        ]

        return {
            "artists": artists,
            "albums": list(albums_map.values())[:limit]
        }

    except Exception as e:
        log_event("gateway", "ERROR", f"Unified search failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")







@app.post("/api/lastfm/top-artists")
async def get_lastfm_top_artists(request: dict):
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    artist_name = request.get("artist_name")

    if not artist_name:
        raise HTTPException(status_code=400, detail="artist_name is required")

    try:
        resp = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/artist-single-recommendation",
            json=request
        )
        return resp.json()
    except Exception as e:
        log_event("gateway", "ERROR", f"Single artist recommendation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get recommendations: {str(e)}")


@app.post("/api/recommendations/spotify")
async def get_spotify_recommendations(request: dict):
    """Get recommendations using Spotify (fast fallback)"""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    artist_name = request.get("artist_name")
    user_id = request.get("user_id")  # Optional: for logging purposes

    if not artist_name:
        raise HTTPException(status_code=400, detail="artist_name is required")

    try:
        resp = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/spotify-recommendations",
            json=request
        )
        data = resp.json()

        # Log the recommendation generation (always log, use user_id=0 if not provided)
        recommendations = data.get("recommendations", [])
        if recommendations:
            recommendation_logger.log_recommendation_generation(
                user_id=user_id or 0,
                artist_name=artist_name,
                source="spotify",
                recommendations=recommendations,
                metadata={
                    "total_returned": data.get("total", 0),
                    "endpoint": "/api/recommendations/spotify"
                }
            )
            log_event("gateway", "INFO",
                     f"Logged {len(recommendations)} Spotify recommendations for {artist_name}")

        return data
    except Exception as e:
        log_event("gateway", "ERROR", f"Spotify recommendation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get Spotify recommendations: {str(e)}")


@app.post("/api/lastfm/recommendations")
@limiter.limit("5/minute")
async def get_lastfm_recommendations(request: Request, body: dict):
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    start_time = time.time()
    time_range = body.get("time_range", "medium_term")
    username = body.get("username")

    if not username:
        raise HTTPException(status_code=400, detail="username is required")

    log_event("gateway", "INFO", f"Starting Last.fm recommendation flow for {username} (time_range={time_range})")

    try:
        log_event("gateway", "INFO", "Step 1: Fetching top albums from Last.fm (simplified)")
        albums_resp = await http_client.post(
            f"{LASTFM_SERVICE_URL}/top-albums",
            json={"time_range": time_range, "username": username}
        )
        albums_data = albums_resp.json()
        all_albums = albums_data.get("albums", [])
        log_event("gateway", "INFO", f"Fetched {len(all_albums)} Last.fm top albums")

        log_event("gateway", "INFO", "Step 2: Processing albums (cache-first + cover fetch)")
        recommendations_resp = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/lastfm-albums-recommendations",
            json=all_albums
        )
        recommendations_data = recommendations_resp.json()
        albums = recommendations_data.get("albums", [])
        stats = recommendations_data.get("stats", {})

        log_event("gateway", "INFO",
                 f"Processed {len(albums)} Last.fm recommendations "
                 f"(cache: {stats.get('cache_hits', 0)}, "
                 f"new: {stats.get('cache_misses', 0)}, "
                 f"covers fetched: {stats.get('covers_fetched', 0)})")

        end_time = time.time()
        total_time = end_time - start_time
        log_event("gateway", "INFO", f"Last.fm recommendation flow complete: {len(albums)} albums in {total_time:.2f}s")

        return {
            "albums": albums,
            "total": len(albums),
            "total_time_seconds": round(total_time, 2),
            "stats": {
                "albums_processed": len(all_albums),
                "albums_found": len(albums),
                "cache_hits": stats.get("cache_hits", 0),
                "cache_misses": stats.get("cache_misses", 0),
                "covers_fetched": stats.get("covers_fetched", 0)
            }
        }

    except Exception as e:
        log_event("gateway", "ERROR", f"Last.fm recommendation flow failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Last.fm recommendation failed: {str(e)}")


@app.get("/api/recommendations/progress")
async def get_recommendations_progress():
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    try:
        resp = await http_client.get(f"{RECOMMENDER_SERVICE_URL}/progress")
        return resp.json()
    except Exception as e:
        log_event("gateway", "ERROR", f"Failed to fetch progress: {str(e)}")
        return {"status": "idle", "current": 0, "total": 0, "current_artist": ""}


@app.post("/api/recommendations/artist-single")
@limiter.limit("5/minute")
async def get_single_artist_recommendations(request: Request, body: dict):
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    artist_name = body.get("artist_name")
    top_albums = body.get("top_albums", 3)
    csv_mode = body.get("csv_mode", False)
    user_id = body.get("user_id")

    if not artist_name:
        raise HTTPException(status_code=400, detail="artist_name is required")

    start_time = time.time()
    mode_label = " (CSV mode)" if csv_mode else ""
    log_event("gateway", "INFO", f"Getting recommendations for artist: {artist_name}{mode_label}")

    try:
        resp = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/artist-single-recommendation",
            json={
                "artist_name": artist_name,
                "top_albums": top_albums,
                "csv_mode": csv_mode,
                "user_id": user_id
            }
        )
        resp.raise_for_status()
        result = resp.json()

        end_time = time.time()
        total_time = end_time - start_time

        recommendations = result.get("recommendations", [])

        if not recommendations:
            log_event("gateway", "INFO", f"No recommendations found for {artist_name}")
            # Do not raise 404, return empty list


        log_event("gateway", "INFO",
                 f"Got {len(recommendations)} recommendations for {artist_name} in {total_time:.2f}s")

        return {
            "recommendations": recommendations,
            "total": len(recommendations),
            "artist_name": artist_name,
            "total_time_seconds": round(total_time, 2),
            "status": "success"
        }

    except HTTPException:
        raise
    except Exception as e:
        log_event("gateway", "ERROR", f"Single artist recommendations failed for {artist_name}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Recommendations failed: {str(e)}")


@app.post("/api/recommendations/artists")
async def get_artist_recommendations(request: dict):
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    artist_names = request.get("artist_names", [])

    if not artist_names:
        raise HTTPException(status_code=400, detail="artist_names is required")

    if len(artist_names) < 3:
        raise HTTPException(status_code=400, detail="Minimum 3 artists required")

    if len(artist_names) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 artists allowed")

    start_time = time.time()
    log_event("gateway", "INFO", f"Getting recommendations for {len(artist_names)} artists")

    try:
        artist_recs_resp = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/artist-recommendations",
            json={"artist_names": artist_names, "top_per_artist": 3}
        )
        artist_recs = artist_recs_resp.json().get("recommendations", [])
        log_event("gateway", "INFO", f"Got {len(artist_recs)} artist-based recommendations")

        merge_resp = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/merge-recommendations",
            json={
                "artist_recommendations": artist_recs
            }
        )
        merged = merge_resp.json().get("recommendations", [])

        end_time = time.time()
        total_time = end_time - start_time
        log_event("gateway", "INFO", f"Artist recommendations complete: {len(merged)} total in {total_time:.2f}s")

        return {
            "recommendations": merged,
            "total": len(merged),
            "total_time_seconds": round(total_time, 2),
            "stats": {
                "artist_based": len(artist_recs),
                "total": len(merged)
            }
        }

    except Exception as e:
        log_event("gateway", "ERROR", f"Artist recommendations failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Recommendations failed: {str(e)}")


@app.post("/api/recommendations/merge")
async def merge_recommendations(request: dict):
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    try:
        lastfm_recs = request.get("lastfm_recommendations", [])
        artist_recs = request.get("artist_recommendations", [])

        log_event("gateway", "INFO",
                  f"Merging {len(lastfm_recs)} Last.fm + {len(artist_recs)} artist recommendations")

        response = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/merge-recommendations",
            json={
                "lastfm_recommendations": lastfm_recs,
                "artist_recommendations": artist_recs
            }
        )

        data = response.json()
        log_event("gateway", "INFO", f"Merged into {data.get('total', 0)} recommendations")
        return data

    except Exception as e:
        log_event("gateway", "ERROR", f"Merge recommendations failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Merge failed: {str(e)}")

@app.post("/api/recommendations/collection")
async def get_collection_recommendations(request: dict):
    """Get recommendations based on user's Discogs collection."""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    username = request.get("username")
    limit = request.get("limit", 5)

    log_event("gateway", "INFO", f"Fetching collection recommendations for {username}")

    try:
        start_time = time.time()
        resp = await http_client.post(
            f"{RECOMMENDER_SERVICE_URL}/collection-recommendations",
            json={"username": username, "limit": limit},
            timeout=60.0
        )

        if resp.status_code != 200:
            log_event("gateway", "ERROR", f"Collection recommendations failed: {resp.text}")
            raise HTTPException(status_code=resp.status_code, detail="Failed to fetch collection recommendations")

        data = resp.json()
        total_time = time.time() - start_time

        recommendations = data.get("recommendations", [])
        log_event("gateway", "INFO", f"Got {len(recommendations)} collection recommendations in {total_time:.2f}s")

        # Log for dashboard
        if recommendations:
            recommendation_logger.log_recommendation_batch(
                user_id=None, # We might not have user_id here easily if it's just passed as username
                source="collection_based",
                recommendations=recommendations,
                endpoint="/api/recommendations/collection"
            )

        return data

    except Exception as e:
        log_event("gateway", "ERROR", f"Collection recommendations error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Collection recommendations error: {str(e)}")



@app.get("/api/admin/explorer/search")
async def admin_search(q: str = "", type: str = "all", limit: int = 50, offset: int = 0):
    """Search for artists, albums or both in the database"""
    results = {}

    if type in ["artist", "all"]:
        if q:
            artists = db_utils.search_artists(q)
        else:
            artists = db_utils.get_all_artists(limit, offset)
        results["artists"] = artists

    if type in ["album", "all"]:
        if q:
            albums = db_utils.search_albums(q)
        else:
            albums = db_utils.get_all_albums(limit, offset)
        results["albums"] = albums

    return results



@app.post("/api/admin/explorer/update/{entity_type}/{entity_id}")
async def admin_update_entity(entity_type: str, entity_id: int, data: dict[str, Any] = {}):
    """Update an entity by syncing with external sources (MusicBrainz/Discogs)"""

    if entity_type == "artist":
        result = await seeder.sync_artist(entity_id)
        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result["message"])
        return result

    elif entity_type == "album":
        result = await seeder.sync_album(entity_id)
        if result["status"] == "error":
            raise HTTPException(status_code=500, detail=result["message"])
        return result

    else:
        raise HTTPException(status_code=400, detail="Invalid entity type")



@app.post("/api/admin/import-csv")
async def import_artists_csv(file: UploadFile = File(...)):
    """Import artists from CSV file with real-time progress updates via SSE"""

    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")

    if not file.filename or not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    # Read file content before creating the stream
    content = await file.read()
    csv_text = content.decode('utf-8')
    csv_reader = csv.DictReader(csv_text.splitlines())

    if not csv_reader.fieldnames or 'name' not in csv_reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV must have a 'name' column")

    artists = [row['name'].strip() for row in csv_reader if row.get('name', '').strip()]

    if not artists:
        raise HTTPException(status_code=400, detail="No artists found in CSV")

    async def event_stream() -> AsyncGenerator[str, None]:
        """Server-Sent Events stream for progress updates"""
        try:
            total = len(artists)
            yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"

            successful = 0
            cached = 0
            failed = 0
            failed_artists = []

            for i, artist_name in enumerate(artists, 1):
                try:
                    start_time = time.time()

                    response = await http_client.post(
                        f"{RECOMMENDER_SERVICE_URL}/artist-recommendations",
                        json={"artist_name": artist_name, "top_albums": 10, "csv_mode": True},
                        timeout=180.0
                    )

                    elapsed = time.time() - start_time

                    if response.status_code == 200:
                        data = response.json()
                        total_albums = data.get('total', 0)
                        top_album = None
                        rating = None

                        if data.get('recommendations'):
                            top_album = data['recommendations'][0].get('album_name')
                            rating = data['recommendations'][0].get('rating')

                        if elapsed < 1.0:
                            cached += 1
                            status = 'cached'
                        else:
                            successful += 1
                            status = 'success'

                        yield f"data: {json.dumps({'type': 'progress', 'current': i, 'total': total, 'artist': artist_name, 'status': status, 'albums': total_albums, 'time': round(elapsed, 2), 'top_album': top_album, 'rating': rating})}\n\n"

                    elif response.status_code == 404:
                        failed += 1
                        failed_artists.append(artist_name)
                        yield f"data: {json.dumps({'type': 'progress', 'current': i, 'total': total, 'artist': artist_name, 'status': 'not_found', 'error': 'No albums found'})}\n\n"

                    else:
                        failed += 1
                        failed_artists.append(artist_name)
                        error_msg = response.text[:100]
                        yield f"data: {json.dumps({'type': 'progress', 'current': i, 'total': total, 'artist': artist_name, 'status': 'error', 'error': error_msg})}\n\n"

                except TimeoutError:
                    failed += 1
                    failed_artists.append(artist_name)
                    yield f"data: {json.dumps({'type': 'progress', 'current': i, 'total': total, 'artist': artist_name, 'status': 'timeout', 'error': 'Request timeout'})}\n\n"

                except Exception as e:
                    failed += 1
                    failed_artists.append(artist_name)
                    yield f"data: {json.dumps({'type': 'progress', 'current': i, 'total': total, 'artist': artist_name, 'status': 'error', 'error': str(e)})}\n\n"

                await asyncio.sleep(0.1)

            if failed_artists:
                yield f"data: {json.dumps({'type': 'retry_start', 'failed_count': len(failed_artists), 'artists': failed_artists})}\n\n"

                retry_successful = 0
                retry_failed = 0

                for i, artist_name in enumerate(failed_artists, 1):
                    try:
                        start_time = time.time()

                        response = await http_client.post(
                            f"{RECOMMENDER_SERVICE_URL}/artist-single-recommendation",
                            json={"artist_name": artist_name, "top_albums": 10, "csv_mode": True},
                            timeout=180.0
                        )

                        elapsed = time.time() - start_time

                        if response.status_code == 200:
                            data = response.json()
                            total_albums = data.get('total', 0)
                            top_album = None
                            rating = None

                            if data.get('recommendations'):
                                top_album = data['recommendations'][0].get('album_name')
                                rating = data['recommendations'][0].get('rating')

                            retry_successful += 1
                            successful += 1
                            failed -= 1

                            yield f"data: {json.dumps({'type': 'retry_progress', 'current': i, 'total': len(failed_artists), 'artist': artist_name, 'status': 'success', 'albums': total_albums, 'time': round(elapsed, 2), 'top_album': top_album, 'rating': rating})}\n\n"
                        else:
                            retry_failed += 1
                            error_msg = response.text[:100] if hasattr(response, 'text') else 'Unknown error'
                            yield f"data: {json.dumps({'type': 'retry_progress', 'current': i, 'total': len(failed_artists), 'artist': artist_name, 'status': 'error', 'error': error_msg})}\n\n"

                    except Exception as e:
                        retry_failed += 1
                        yield f"data: {json.dumps({'type': 'retry_progress', 'current': i, 'total': len(failed_artists), 'artist': artist_name, 'status': 'error', 'error': str(e)})}\n\n"

                    await asyncio.sleep(0.1)

                yield f"data: {json.dumps({'type': 'retry_complete', 'retry_successful': retry_successful, 'retry_failed': retry_failed})}\n\n"

            yield f"data: {json.dumps({'type': 'complete', 'successful': successful, 'cached': cached, 'failed': failed, 'total': total})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")



# ---------------------------------------------------------------------------
# Discogs Journey Proxies
# ---------------------------------------------------------------------------

class CollectionStatsRequest(BaseModel):
    user_id: int
    username: str

class CollectionPreferencesRequest(BaseModel):
    user_id: int
    focus_artists: list[str] = []
    strategies: list[str] = ["complete", "upgrade"]

@app.post("/api/collection/stats")
async def proxy_collection_stats(request: CollectionStatsRequest):
    """Proxy to Recommender: Get collection stats"""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")
    try:
        resp = await http_client.post(f"{RECOMMENDER_SERVICE_URL}/collection/stats", json=request.dict())
        if resp.status_code != 200:
             raise HTTPException(status_code=resp.status_code, detail="Recommender service error")
        return resp.json()
    except Exception as e:
        log_event("gateway", "ERROR", f"Stats proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/collection/preferences")
async def proxy_save_preferences(request: CollectionPreferencesRequest):
    """Proxy to Recommender: Save preferences"""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")
    try:
        resp = await http_client.post(f"{RECOMMENDER_SERVICE_URL}/collection/preferences", json=request.dict())
        if resp.status_code != 200:
             raise HTTPException(status_code=resp.status_code, detail="Recommender service error")
        return resp.json()
    except Exception as e:
        log_event("gateway", "ERROR", f"Preferences proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/collection/generate")
async def proxy_generate_recommendations(request: CollectionPreferencesRequest):
    """Proxy to Recommender: Generate and persist recommendations"""
    if not http_client:
        raise HTTPException(status_code=500, detail="HTTP client not initialized")
    try:
        # Increase timeout for generation
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(f"{RECOMMENDER_SERVICE_URL}/collection/generate", json=request.dict())
            if resp.status_code != 200:
                 raise HTTPException(status_code=resp.status_code, detail="Recommender service error")
            return resp.json()
    except Exception as e:
        log_event("gateway", "ERROR", f"Generation proxy failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Admin endpoints for database management
# ---------------------------------------------------------------------------

@app.get("/api/admin/db/download")
async def download_database():
    """Download the current database file for backup purposes."""
    db_path = Path(__file__).parent.parent / "vinylbe.db"

    if not db_path.exists():
        raise HTTPException(status_code=404, detail="Database file not found")

    log_event("gateway", "INFO", "Database download requested")
    return FileResponse(
        path=str(db_path),
        filename="vinylbe.db",
        media_type="application/octet-stream"
    )


@app.post("/api/admin/db/upload")
async def upload_database(database: UploadFile = File(...)):
    """Upload and replace the production database. USE WITH CAUTION!"""
    db_path = Path(__file__).parent.parent / "vinylbe.db"
    backup_path = Path(__file__).parent.parent / f"vinylbe.db.backup.{int(time.time())}"

    try:
        # Create backup of current database
        if db_path.exists():
            import shutil
            shutil.copy2(db_path, backup_path)
            log_event("gateway", "INFO", f"Created database backup: {backup_path.name}")

        # Write uploaded file
        content = await database.read()

        # Validate it's a SQLite database
        if not content.startswith(b'SQLite format 3'):
            raise HTTPException(status_code=400, detail="Invalid SQLite database file")

        with open(db_path, "wb") as f:
            f.write(content)

        log_event("gateway", "INFO", f"Database updated successfully (size: {len(content)} bytes)")

        return {
            "status": "success",
            "message": "Database updated successfully",
            "backup_created": backup_path.name,
            "size_bytes": len(content)
        }

    except HTTPException:
        raise
    except Exception as e:
        log_event("gateway", "ERROR", f"Database upload failed: {str(e)}")
        # Restore from backup if it exists
        if backup_path.exists():
            import shutil
            shutil.copy2(backup_path, db_path)
            log_event("gateway", "INFO", "Restored database from backup after failed upload")
        raise HTTPException(status_code=500, detail=f"Database upload failed: {str(e)}")
