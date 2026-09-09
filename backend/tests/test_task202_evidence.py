import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.evidence.adapter import (
    AiJudgmentResult,
    ContractExtractionResult,
    RuleEvaluationResult,
    ai_judgment_to_evidence,
    contract_extraction_to_evidence,
    rule_result_to_evidence,
)
from tests.asgi_client import app_client


def test_evidence_object_can_be_created_updated_and_read_by_version(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-202 Evidence Project"},
            )
            project_id = project_response.json()["project_id"]

            create_response = await client.post(
                f"/api/v1/projects/{project_id}/evidence",
                json={
                    "source": "manual:test-case",
                    "extracted_value": {"amount": 1200, "currency": "CNY"},
                    "conclusion": "Sample evidence only; no audit conclusion.",
                    "execution_status": "completed",
                    "node_status": "ready",
                    "judgment_status": "AI_GENERATED",
                    "confidence": 0.76,
                    "model_confidence": 0.71,
                    "confidence_level": "medium",
                    "confidence_basis": "Synthetic test evidence.",
                },
            )
            evidence_id = create_response.json()["evidence_id"]

            pending_response = await client.patch(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}/status",
                json={"judgment_status": "PENDING_REVIEW"},
            )
            confirm_response = await client.patch(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}/status",
                json={
                    "judgment_status": "CONFIRMED",
                    "node_status": "completed",
                    "reviewer": "pm-reviewer",
                },
            )
            version_one_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}/versions/1"
            )
            latest_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}"
            )

            return (
                create_response,
                pending_response,
                confirm_response,
                version_one_response,
                latest_response,
            )

    (
        create_response,
        pending_response,
        confirm_response,
        version_one_response,
        latest_response,
    ) = asyncio.run(scenario())

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["judgment_status"] == "AI_GENERATED"
    assert created["node_status"] == "ready"
    assert created["object_version"] == 1

    assert pending_response.status_code == 200
    assert pending_response.json()["judgment_status"] == "PENDING_REVIEW"
    assert pending_response.json()["object_version"] == 2

    assert confirm_response.status_code == 200
    updated = confirm_response.json()
    assert updated["judgment_status"] == "CONFIRMED"
    assert updated["node_status"] == "completed"
    assert updated["reviewer"] == "pm-reviewer"
    assert updated["object_version"] == 3

    assert version_one_response.status_code == 200
    assert version_one_response.json()["judgment_status"] == "AI_GENERATED"
    assert version_one_response.json()["object_version"] == 1

    assert latest_response.status_code == 200
    assert latest_response.json()["judgment_status"] == "CONFIRMED"
    assert latest_response.json()["object_version"] == 3


def test_final_evidence_review_status_requires_reviewer(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post("/api/v1/projects", json={"name": "Review Gate"})
            project_id = project_response.json()["project_id"]
            create_response = await client.post(
                f"/api/v1/projects/{project_id}/evidence",
                json={
                    "source": "manual:test-case",
                    "extracted_value": {"sample": True},
                    "judgment_status": "PENDING_REVIEW",
                },
            )
            evidence_id = create_response.json()["evidence_id"]
            return await client.patch(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}/status",
                json={"judgment_status": "REJECTED"},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 422


def test_unknown_procedure_returns_controlled_400(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "Procedure Gate"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/evidence",
                json={
                    "procedure_id": "P202",
                    "source": "manual:test-case",
                    "extracted_value": {"sample": True},
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "procedure_not_found"


def test_final_judgment_status_cannot_return_to_ai_generated(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post("/api/v1/projects", json={"name": "State Machine"})
            project_id = project_response.json()["project_id"]
            create_response = await client.post(
                f"/api/v1/projects/{project_id}/evidence",
                json={
                    "source": "manual:test-case",
                    "extracted_value": {"sample": True},
                    "judgment_status": "PENDING_REVIEW",
                },
            )
            evidence_id = create_response.json()["evidence_id"]
            confirm_response = await client.patch(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}/status",
                json={
                    "judgment_status": "CONFIRMED",
                    "reviewer": "pm-reviewer",
                },
            )
            rollback_response = await client.patch(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}/status",
                json={"judgment_status": "AI_GENERATED"},
            )
            return confirm_response, rollback_response

    confirm_response, rollback_response = asyncio.run(scenario())

    assert confirm_response.status_code == 200
    assert rollback_response.status_code == 400
    assert rollback_response.json()["detail"]["code"] == "invalid_judgment_transition"


def test_capability_outputs_can_be_converted_to_evidence_create_payloads() -> None:
    contract_evidence = contract_extraction_to_evidence(
        ContractExtractionResult(
            document_id="doc-1",
            field_name="contract_amount",
            extracted_value="120000.00",
            source_location="page=1",
            confidence=0.86,
            confidence_basis="Amount appears near the contract total label.",
        )
    )
    rule_evidence = rule_result_to_evidence(
        RuleEvaluationResult(
            procedure_id=None,
            rule_id="revenue-cutoff-sample",
            observed_value={"delivery_date": "2026-01-02"},
            conclusion="Delivery date is after period end.",
            confidence_basis="Rule evaluation uses structured sample fields.",
        )
    )
    ai_evidence = ai_judgment_to_evidence(
        AiJudgmentResult(
            procedure_id=None,
            prompt_name="contract_revenue_terms",
            extracted_value={"revenue_terms": "acceptance-based"},
            conclusion="AI-generated draft; reviewer must confirm.",
            model_confidence=0.67,
            confidence_basis="Model answer references acceptance clause.",
        )
    )

    assert contract_evidence.source.startswith("contract_extraction:")
    assert contract_evidence.judgment_status == "AI_GENERATED"
    assert contract_evidence.confidence_level == "high"
    assert rule_evidence.source == "rule:revenue-cutoff-sample"
    assert rule_evidence.judgment_status == "PENDING_REVIEW"
    assert ai_evidence.source == "ai_judgment:contract_revenue_terms"
    assert ai_evidence.model_confidence == 0.67
