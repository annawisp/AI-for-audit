import asyncio
from pathlib import Path

from app.core.config import get_settings
from tests.asgi_client import app_client


def test_oversized_upload_returns_structured_400_and_removes_partial_file(
    monkeypatch, tmp_path: Path
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_max_bytes", 5)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post("/api/v1/projects", json={"name": "TTP-102"})
            project_id = project_response.json()["project_id"]
            upload_response = await client.post(
                f"/api/v1/projects/{project_id}/documents",
                files={"file": ("large.txt", b"123456", "text/plain")},
            )
            return upload_response

    response = asyncio.run(scenario())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "file_too_large"
    assert list((tmp_path / "uploads").rglob("*large.txt")) == []
