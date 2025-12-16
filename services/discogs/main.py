from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from libs.shared.models import DiscogsRelease, DiscogsStats, ServiceHealth
from libs.shared.utils import create_http_client, log_event
from .discogs_client import DiscogsClient
from pydantic import BaseModel
import logging

logging.basicConfig(level=logging.INFO)

discogs_client = None

class AccessTokenRequest(BaseModel):
    request_token: str
    request_token_secret: str
    verifier: str

class UserCollectionRequest(BaseModel):
    username: str
    page: int = 1
    per_page: int = 50
    access_token: str
    access_token_secret: str



@asynccontextmanager
async def lifespan(app: FastAPI):
    global discogs_client
    discogs_key = os.getenv("DISCOGS_KEY", "")
    discogs_secret = os.getenv("DISCOGS_SECRET", "")
    discogs_client = DiscogsClient(discogs_key, discogs_secret)
    await discogs_client.start()
    log_event("discogs-service", "INFO", "Discogs Service started")
    yield
    await discogs_client.stop()
    log_event("discogs-service", "INFO", "Discogs Service stopped")


app = FastAPI(lifespan=lifespan, title="Discogs Service")

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
        service_name="discogs-service",
        status="healthy" if discogs_client and discogs_client.is_ready() else "unhealthy"
    ).dict()


@app.get("/search")
async def search_release(artist: str = Query(...), title: str = Query(...)):
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    log_event("discogs-service", "INFO", f"Searching for: {artist} - {title}")
    
    response = await discogs_client.search_release(artist, title)
    results = response.get("results", [])
    debug_info = response.get("debug_info", {})
    
    log_event("discogs-service", "INFO", f"Found {len(results)} results for {artist} - {title}")
    return {"releases": results, "total": len(results), "debug_info": debug_info}


@app.get("/search_album_only")
async def search_album_only(q: str = Query(...)):
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    log_event("discogs-service", "INFO", f"Searching for album: {q}")
    
    response = await discogs_client.search_album(q)
    results = response.get("results", [])
    debug_info = response.get("debug_info", {})
    
    log_event("discogs-service", "INFO", f"Found {len(results)} album results for {q}")
    return {"releases": results, "total": len(results), "debug_info": debug_info}


@app.get("/stats/{release_id}")
async def get_marketplace_stats(release_id: int, currency: str = "EUR"):
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    log_event("discogs-service", "INFO", f"Getting stats for release {release_id}")
    
    stats = await discogs_client.get_marketplace_stats(release_id, currency)
    
    log_event("discogs-service", "INFO", f"Stats retrieved for release {release_id}: {stats.get('num_for_sale', 0)} items for sale")
    return stats


@app.get("/sell-list-url/{release_id}")
async def get_sell_list_url(release_id: int):
    if not discogs_client or not discogs_client.is_ready():
        raise HTTPException(status_code=503, detail="Discogs client not ready")
    
    # Get master_id from release_id
    master_id = await discogs_client._get_master_id_from_release(release_id)
    
    # Use master_id if available, otherwise fallback to release_id
    if master_id:
        url = f"https://www.discogs.com/sell/list?master_id={master_id}&currency=EUR&format=Vinyl"
        log_event("discogs-service", "INFO", f"Generated sell list URL for release {release_id} (master_id: {master_id})")
    else:
        url = f"https://www.discogs.com/sell/list?release_id={release_id}&currency=EUR&format=Vinyl"
        log_event("discogs-service", "WARNING", f"Generated sell list URL for release {release_id} (master_id not found)")
    
    return {"release_id": release_id, "url": url}


@app.get("/master-link/{artist}/{album}")
async def get_master_link(artist: str, album: str):
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    log_event("discogs-service", "INFO", f"Fetching master link for: {artist} - {album}")
    
    result = await discogs_client.get_master_link(artist, album)
    
    if result.get("master_id"):
        log_event("discogs-service", "INFO", f"Master found for {artist} - {album}: {result['master_id']}")
    else:
        log_event("discogs-service", "INFO", f"No master found for {artist} - {album}")
    
    return result


@app.get("/search-album")
async def search_album_cover(artist: str = Query(...), album: str = Query(...)):
    """
    Simplified search that returns only the cover URL for an album
    Used by Last.fm recommendations to populate basic album entries
    """
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    log_event("discogs-service", "INFO", f"Searching cover for: {artist} - {album}")
    
    try:
        response = await discogs_client.search_release(artist, album)
        results = response.get("results", [])
        
        if results:
            cover_url = results[0].get("cover_image") or results[0].get("thumb")
            log_event("discogs-service", "INFO", f"Cover found for {artist} - {album}")
            return {"cover_url": cover_url, "found": True}
        else:
            log_event("discogs-service", "INFO", f"No cover found for {artist} - {album}")
            return {"cover_url": None, "found": False}
    except Exception as e:
        log_event("discogs-service", "ERROR", f"Error searching cover: {str(e)}")
        return {"cover_url": None, "found": False, "error": str(e)}


@app.get("/master-tracklist/{master_id}")
async def get_master_tracklist(master_id: int):
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    log_event("discogs-service", "INFO", f"Fetching tracklist for master: {master_id}")
    
    result = await discogs_client.get_master_tracklist(master_id)
    
    if result.get("tracklist"):
        log_event("discogs-service", "INFO", f"Tracklist found for master {master_id}: {len(result['tracklist'])} tracks")
    else:
        log_event("discogs-service", "INFO", f"No tracklist found for master {master_id}")
    
    return result


@app.get("/release-tracklist/{release_id}")
async def get_release_tracklist(release_id: int):
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    log_event("discogs-service", "INFO", f"Fetching tracklist for release: {release_id}")
    
    result = await discogs_client.get_release_tracklist(release_id)
    
    if result.get("tracklist"):
        log_event("discogs-service", "INFO", f"Tracklist found for release {release_id}: {len(result['tracklist'])} tracks")
    else:
        log_event("discogs-service", "INFO", f"No tracklist found for release {release_id}")
    
    return result


# ---------------------------------------------------------------------------
# OAuth Endpoints
# ---------------------------------------------------------------------------

@app.get("/auth/url")
async def get_auth_url(callback_url: str):
    """
    Get Request Token and Authorize URL.
    """
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    try:
        request_token_data = await discogs_client.get_request_token(callback_url)
        request_token = request_token_data.get('oauth_token')
        
        auth_url = discogs_client.get_authorize_url(request_token)
        
        return {
            "oauth_token": request_token_data.get('oauth_token'),
            "oauth_token_secret": request_token_data.get('oauth_token_secret'),
            "auth_url": auth_url
        }
    except Exception as e:
        log_event("discogs-service", "ERROR", f"Auth URL generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/auth/access_token")
async def get_access_token(request: AccessTokenRequest):
    """
    Exchange Request Token for Access Token.
    """
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    try:
        print(f"DEBUG [discogs-service]: Exchanging token {request.request_token} with secret {request.request_token_secret} and verifier {request.verifier}", flush=True)
        access_token_data = await discogs_client.get_access_token(
            request.request_token, 
            request.request_token_secret, 
            request.verifier
        )
        return access_token_data
    except Exception as e:
        log_event("discogs-service", "ERROR", f"Access Token exchange failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/auth/identity")
async def get_identity(token: str, secret: str):
    """
    Get Identity of the user.
    """
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
    
    try:
        identity = await discogs_client.get_identity(token, secret)
        return identity
    except Exception as e:
        log_event("discogs-service", "ERROR", f"Identity fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/user/collection")
async def get_collection(request: UserCollectionRequest):
    """
    Get user collection (this might need user-specific client instance or simple public fetch).
    Since user collection is public usually, we can fetch it with app credentials if username is known,
    OR use the user credentials if it's private.
    However, our `get_user_collection` in client uses the main app client.
    For typical use cases, app credentials work for public collections.
    If we strictly need user authentication to see private folders, we would need to reinstantiate the client 
    or pass auth headers dynamically. The current `discogs_client` uses app auth (key/secret).
    
    The `get_user_collection` method in `DiscogsClient` uses `_get_auth_params` which appends APP key/secret.
    This works for public collections.
    """
    if not discogs_client:
        raise HTTPException(status_code=500, detail="Discogs client not initialized")
        
    try:
        # Currently fetching public collection
        collection = await discogs_client.get_user_collection(
            request.username, 
            request.page, 
            request.per_page
        )
        return collection
    except Exception as e:
        log_event("discogs-service", "ERROR", f"Collection fetch failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

