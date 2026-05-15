"""Tests for the /health endpoint."""

import pytest
import respx
from httpx import Response

_ALL_HEALTHY = {port: Response(200, json={"status": "healthy"}) for port in (3001, 3002, 3003, 3004, 3005)}


def _mock_all_healthy(mock):
    for port, resp in _ALL_HEALTHY.items():
        mock.get(f"http://127.0.0.1:{port}/health").mock(return_value=resp)


@pytest.mark.asyncio
async def test_health_returns_200(client):
    with respx.mock(assert_all_called=False) as mock:
        _mock_all_healthy(mock)
        resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_health_contains_gateway_key(client):
    with respx.mock(assert_all_called=False) as mock:
        _mock_all_healthy(mock)
        data = (await client.get("/health")).json()
    assert data["gateway"] == "healthy"


@pytest.mark.asyncio
async def test_health_overall_healthy_when_all_services_up(client):
    with respx.mock(assert_all_called=False) as mock:
        _mock_all_healthy(mock)
        data = (await client.get("/health")).json()
    assert data["overall_status"] == "healthy"


@pytest.mark.asyncio
async def test_health_degraded_when_service_down(client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("http://127.0.0.1:3001/health").mock(side_effect=Exception("connection refused"))
        for port in (3002, 3003, 3004, 3005):
            mock.get(f"http://127.0.0.1:{port}/health").mock(
                return_value=Response(200, json={"status": "healthy"})
            )
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_status"] == "degraded"
    assert data["services"]["discogs"]["status"] == "unhealthy"
