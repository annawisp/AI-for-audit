"""TASK-201 Project Context MVP acceptance tests."""

import asyncio
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from pytest import MonkeyPatch

from app.core.config import get_settings
from tests.asgi_client import app_client


def _patch_settings(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))


async def _create_project(client: AsyncClient, **extra: Any) -> str:
    response = await client.post("/api/v1/projects", json={"name": "TASK-201", **extra})
    assert response.status_code == 201
    return response.json()["project_id"]


def _core(report: dict[str, Any], section: str) -> dict[str, Any]:
    return next(item for item in report["core_sections"] if item["section"] == section)


def test_minimal_basic_info_and_contract_can_start_project(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _patch_settings(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with app_client() as client:
            project_id = await _create_project(client)
            response = await client.post(
                f"/api/v1/projects/{project_id}/context",
                json={
                    "payload": {
                        "basic_info": {"entity_name": "华宇科技"},
                        "contracts": [{"title": "销售框架协议", "counterparty": "华东客户"}],
                    },
                    "changed_by": "auditor-zhang",
                    "change_reason": "录入最小上下文",
                },
            )
            assert response.status_code == 201
            assert response.json()["version"] == 1
            assert response.json()["changed_sections"] == ["basic_info", "contracts"]

            readiness = (
                await client.get(f"/api/v1/projects/{project_id}/context/readiness")
            ).json()
            assert readiness["minimal_requirements_met"] is True
            assert readiness["missing_does_not_block"] is True
            assert _core(readiness, "basic_info")["status"] == "provided"
            assert _core(readiness, "contracts")["status"] == "provided"

    asyncio.run(scenario())


def test_missing_extended_data_is_optional_and_non_blocking(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _patch_settings(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with app_client() as client:
            project_id = await _create_project(client)
            response = await client.post(
                f"/api/v1/projects/{project_id}/context",
                json={"payload": {"basic_info": {"entity_name": "华宇科技"}}},
            )
            assert response.status_code == 201

            readiness = (
                await client.get(f"/api/v1/projects/{project_id}/context/readiness")
            ).json()
            assert readiness["minimal_requirements_met"] is True
            assert readiness["missing_does_not_block"] is True
            assert len(readiness["extended_sections"]) == 5
            assert {item["scope"] for item in readiness["extended_sections"]} == {
                "mvp_2_0_optional"
            }
            assert {item["status"] for item in readiness["extended_sections"]} == {
                "not_provided"
            }
            assert _core(readiness, "materiality")["status"] == "not_provided"
            assert _core(readiness, "revenue_model")["status"] == "not_provided"

    asyncio.run(scenario())


def test_context_versions_are_traceable_and_history_is_readable(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    _patch_settings(monkeypatch, tmp_path)

    async def scenario() -> None:
        async with app_client() as client:
            project_id = await _create_project(
                client,
                client_name="华宇科技",
                audit_period_start="2025-01-01",
                audit_period_end="2025-12-31",
            )
            first = await client.post(
                f"/api/v1/projects/{project_id}/context",
                json={
                    "payload": {"basic_info": {"entity_name": "华宇科技"}},
                    "changed_by": "auditor-a",
                    "change_reason": "初始录入",
                },
            )
            second = await client.post(
                f"/api/v1/projects/{project_id}/context",
                json={
                    "payload": {
                        "basic_info": {"entity_name": "华宇科技"},
                        "audit_period": {
                            "start_date": "2025-01-01",
                            "end_date": "2025-12-31",
                        },
                        "materiality": {"overall_amount": 1000000, "currency": "CNY"},
                    },
                    "changed_by": "manager-b",
                    "change_reason": "补充重要性",
                },
            )
            assert first.status_code == 201
            assert second.status_code == 201
            assert second.json()["version"] == 2
            assert second.json()["changed_sections"] == ["materiality"]

            versions = await client.get(f"/api/v1/projects/{project_id}/context/versions")
            assert versions.status_code == 200
            assert [item["version"] for item in versions.json()["items"]] == [2, 1]
            assert versions.json()["items"][0]["is_current"] is True
            assert versions.json()["items"][1]["is_current"] is False

            old_snapshot = await client.get(
                f"/api/v1/projects/{project_id}/context/versions/1"
            )
            assert old_snapshot.status_code == 200
            assert old_snapshot.json()["payload"]["materiality"]["overall_amount"] is None
            assert old_snapshot.json()["changed_by"] == "auditor-a"

    asyncio.run(scenario())
