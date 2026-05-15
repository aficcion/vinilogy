"""
Shared fixtures for Vinylbe tests.

Strategy:
- Each test gets an isolated SQLite DB (temp file); tables are created directly.
- Required env vars are injected so _check_env() passes.
- gateway.main.http_client is wired to a real AsyncClient intercepted by respx.
- httpx.ASGITransport is used directly so the FastAPI lifespan is NOT invoked
  (httpx >= 0.20 no longer calls lifespan via AsyncClient(app=...) anyway).
- Routes are registered on the respx mock object (not on the global router) to
  avoid the common pitfall where respx.get() and respx.mock() use different routers.
"""

import sys
from pathlib import Path
from typing import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport, Response

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

REQUIRED_ENV = {
    "DISCOGS_KEY": "test_discogs_key",
    "LASTFM_API_KEY": "test_lastfm_key",
    "LASTFM_API_SECRET": "test_lastfm_secret",
}


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch, tmp_path):
    """Inject env vars and initialise an isolated SQLite DB for every test."""
    for key, val in REQUIRED_ENV.items():
        monkeypatch.setenv(key, val)

    db_file = tmp_path / "test_vinylbe.db"
    monkeypatch.setenv("VINYLBE_DB_PATH", str(db_file))

    import gateway.db as gdb
    monkeypatch.setattr(gdb, "DB_PATH", str(db_file))
    gdb.init_db()  # create tables in the temp file right now

    yield


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """
    Async test client backed by ASGITransport (no lifespan).
    gateway.main.http_client is manually set so outbound calls to microservices
    can be intercepted by respx. Routes MUST be registered on the mock object
    (the `as mock:` alias), not via bare respx.get() which uses a different router.
    """
    import gateway.main as gm
    from gateway.main import app

    outbound = httpx.AsyncClient(timeout=10.0)
    gm.http_client = outbound

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await outbound.aclose()
        gm.http_client = None
