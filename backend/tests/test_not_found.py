import asyncio

from tests.asgi_client import app_client


def test_unknown_route_returns_404_without_stopping_service() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            missing = await client.get("/api/v1/does-not-exist")
            health = await client.get("/api/v1/health")
            return missing, health

    missing, health = asyncio.run(scenario())

    assert missing.status_code == 404
    assert missing.json() == {"detail": "Not Found"}
    assert "traceback" not in missing.text.lower()
    assert "/workspace/" not in missing.text.lower()
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
