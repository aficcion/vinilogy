"""Tests for the unified search endpoint."""

import pytest
import respx
from httpx import Response


@pytest.mark.asyncio
async def test_search_requires_min_3_chars(client):
    resp = await client.get("/api/search", params={"q": "ab"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["artists"] == []
    assert data["albums"] == []


@pytest.mark.asyncio
async def test_search_returns_artists_and_albums_keys(client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://127.0.0.1:3005/search/artists").mock(
            return_value=Response(200, json={"artists": [{"name": "Radiohead", "id": "1"}]})
        )
        resp = await client.get("/api/search", params={"q": "radio"})
        assert resp.status_code == 200
        data = resp.json()
        assert "artists" in data
        assert "albums" in data


@pytest.mark.asyncio
async def test_search_empty_query_returns_empty(client):
    resp = await client.get("/api/search", params={"q": ""})
    # Either 200 with empty or 422 — not 500
    assert resp.status_code in (200, 422)


@pytest.mark.asyncio
async def test_search_spotify_down_still_returns_200(client):
    """Search should degrade gracefully if Spotify service is unavailable."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://127.0.0.1:3005/search/artists").mock(
            side_effect=Exception("Spotify down")
        )
        resp = await client.get("/api/search", params={"q": "pink floyd"})
        assert resp.status_code == 200
