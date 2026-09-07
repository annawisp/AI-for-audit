import asyncio

from tests.asgi_client import app_client


def test_health_check_returns_service_metadata() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.get("/api/v1/health")

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "AI for Audit",
        "version": "0.1.0",
        "environment": "test",
    }
    assert response.headers["X-Trace-ID"]


def test_health_check_preserves_caller_trace_id() -> None:
    trace_id = "test-trace-001"

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.get("/api/v1/health", headers={"X-Trace-ID": trace_id})

    response = asyncio.run(scenario())

    assert response.headers["X-Trace-ID"] == trace_id
