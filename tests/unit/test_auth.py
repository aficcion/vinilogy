"""Tests for authentication endpoints."""

import pytest


@pytest.mark.asyncio
async def test_create_guest_user_returns_201_shape(client):
    resp = await client.post("/auth/guest")
    assert resp.status_code == 200
    data = resp.json()
    assert "user_id" in data
    assert isinstance(data["user_id"], int)
    assert data["display_name"].startswith("Guest_")


@pytest.mark.asyncio
async def test_create_guest_user_ids_are_unique(client):
    r1 = await client.post("/auth/guest")
    r2 = await client.post("/auth/guest")
    assert r1.json()["user_id"] != r2.json()["user_id"]


@pytest.mark.asyncio
async def test_auth_google_creates_user(client):
    payload = {
        "email": "test@example.com",
        "display_name": "Test User",
        "google_sub": "google-uid-123",
    }
    resp = await client.post("/auth/google", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["display_name"] == "Test User"
    assert isinstance(data["user_id"], int)


@pytest.mark.asyncio
async def test_auth_google_idempotent(client):
    """Same google_sub should return the same user_id."""
    payload = {
        "email": "idempotent@example.com",
        "display_name": "Idempotent User",
        "google_sub": "google-uid-idem",
    }
    r1 = await client.post("/auth/google", json=payload)
    r2 = await client.post("/auth/google", json=payload)
    assert r1.json()["user_id"] == r2.json()["user_id"]


@pytest.mark.asyncio
async def test_auth_google_missing_fields_returns_422(client):
    resp = await client.post("/auth/google", json={"email": "only@email.com"})
    assert resp.status_code == 422
