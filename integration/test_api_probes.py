from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from adapters.api.app import build_app
from adapters.api.auth import RequestAuth


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_health_survives_an_unavailable_database_and_errors_are_redacted(anyio_backend):
    store = Mock()
    store.engine.connect.side_effect = OperationalError(None, None, RuntimeError("private DSN"))
    api = build_app(RequestAuth(Mock(), "https://web.example"), store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="https://web.example") as client:
        health = await client.get("/api/v1/health")
        assert health.status_code == 200 and health.json() == {"status": "ok"}
        ready = await client.get("/api/v1/ready")
        assert ready.status_code == 503
        assert ready.headers["content-type"] == "application/problem+json"
        assert ready.json()["request_id"] == ready.headers["x-request-id"]
        assert ready.json()["code"] == "database_unavailable"
        assert "private DSN" not in ready.text
        protected = await client.get("/api/v1/me")
        assert protected.status_code == 401 and protected.headers["www-authenticate"] == "Bearer"
        assert protected.headers["content-type"] == "application/problem+json"
