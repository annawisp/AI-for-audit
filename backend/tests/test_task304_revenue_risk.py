import asyncio
from pathlib import Path

from app.core.config import get_settings
from tests.asgi_client import app_client


def test_revenue_risk_identifies_review_signal_from_contract_evidence(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            evidence_id = await _create_evidence(
                client,
                project_id,
                "capability:contract_extraction",
                {"raw_text": "合同包含多个履约义务，存在验收条件和收入分摊判断。"},
            )
            response = await client.post(
                f"/api/v1/projects/{project_id}/revenue-risk",
                json={"contract_evidence_id": evidence_id},
            )
            list_response = await client.get(f"/api/v1/projects/{project_id}/revenue-risk")
            return response, list_response

    response, list_response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "REQUIRES_REVIEW"
    assert payload["overall_risk_level"] == "HIGH"
    assert payload["coverage"]["contract_evidence"] is True
    assert payload["evidence_id"]
    assert any(signal["signal_id"] == "multiple_obligation_allocation" for signal in payload["risk_signals"])
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1


def test_revenue_risk_accepts_revenue_records_and_creates_evidence(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            response = await client.post(
                f"/api/v1/projects/{project_id}/revenue-risk",
                json={"revenue_records": [{"record_id": "REV-1", "amount": "1000", "recognition_date": "2026-03-31"}]},
            )
            evidence_response = await client.get(f"/api/v1/projects/{project_id}/evidence/{response.json()['evidence_id']}")
            return response, evidence_response

    response, evidence_response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["coverage"]["revenue_record_analysis"] is True
    assert payload["overall_risk_level"] == "LOW"
    assert evidence_response.json()["source"] == "capability:revenue_risk_identification"
    assert evidence_response.json()["extracted_value"]["capability"] == "revenue_risk_identification"


def test_revenue_risk_rejects_wrong_evidence_source(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            evidence_id = await _create_evidence(client, project_id, "manual:test", {"raw_text": "wrong source"})
            return await client.post(
                f"/api/v1/projects/{project_id}/revenue-risk",
                json={"contract_evidence_id": evidence_id},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_contract_evidence_source"


async def _create_project(client):  # type: ignore[no-untyped-def]
    response = await client.post(
        "/api/v1/projects",
        json={"name": "TASK-304", "audit_period_start": "2026-01-01", "audit_period_end": "2026-12-31"},
    )
    return response.json()["project_id"]


async def _create_evidence(client, project_id: str, source: str, extracted_value: dict):  # type: ignore[type-arg,no-untyped-def]
    response = await client.post(
        f"/api/v1/projects/{project_id}/evidence",
        json={
            "source": source,
            "extracted_value": extracted_value,
            "conclusion": "seed evidence",
            "execution_status": "completed",
            "node_status": "ready",
            "judgment_status": "AI_GENERATED",
        },
    )
    return response.json()["evidence_id"]
