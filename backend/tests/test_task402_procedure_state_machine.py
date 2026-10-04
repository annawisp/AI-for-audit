import asyncio
from pathlib import Path

import pytest

from app.core.config import get_settings
from tests.asgi_client import app_client


def _prepare_test_settings(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))


def test_initialize_procedure_states_from_registry(monkeypatch, tmp_path: Path) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Init"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["total"] == 5
    assert {item["status"] for item in payload["items"]} == {"NOT_STARTED"}
    assert {item["procedure_id"] for item in payload["items"]} == {
        "P-REV-001",
        "P-REV-002",
        "P-REV-003",
        "P-REV-004",
        "P-REV-005",
    }


def test_evaluate_ready_state_from_registry_inputs(monkeypatch, tmp_path: Path) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Ready"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state = next(
                item
                for item in init_response.json()["items"]
                if item["procedure_id"] == "P-REV-001"
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state['state_id']}/evaluate",
                json={"available_inputs": {"document_id": True}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "READY"
    assert payload["source_type"] == "system"
    assert payload["blocked_by"] == []


def test_evaluate_blocks_when_required_input_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Blocked"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state = next(
                item
                for item in init_response.json()["items"]
                if item["procedure_id"] == "P-REV-002"
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state['state_id']}/evaluate",
                json={"available_inputs": {}, "completed_procedures": ["P-REV-001"]},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "BLOCKED"
    assert "document_chunks" in payload["blocked_by"]


def test_contract_only_revenue_risk_evaluates_to_partial(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Partial"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state = next(
                item
                for item in init_response.json()["items"]
                if item["procedure_id"] == "P-REV-004"
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state['state_id']}/evaluate",
                json={"available_inputs": {"contract_extraction_evidence": True}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert response.json()["status"] == "PARTIAL"


def test_ai_cannot_mark_procedure_not_performed(monkeypatch, tmp_path: Path) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Manual Gate"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state_id = init_response.json()["items"][0]["state_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "NOT_PERFORMED",
                    "reason": "AI should not decide this.",
                    "source_type": "capability",
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 422


def test_completed_requires_related_evidence(monkeypatch, tmp_path: Path) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Evidence Gate"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state_id = init_response.json()["items"][0]["state_id"]
            ready_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/evaluate",
                json={"available_inputs": {"document_id": True}},
            )
            transition_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "RUNNING",
                    "reason": "Start execution.",
                    "source_type": "system",
                },
            )
            completed_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "COMPLETED",
                    "reason": "No evidence was linked.",
                    "source_type": "capability",
                },
            )
            return ready_response, transition_response, completed_response

    ready_response, transition_response, completed_response = asyncio.run(scenario())

    assert ready_response.status_code == 200
    assert transition_response.status_code == 200
    assert completed_response.status_code == 422


def test_completed_state_links_evidence_and_records_transitions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Transition Log"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state_id = init_response.json()["items"][0]["state_id"]
            evidence_response = await client.post(
                f"/api/v1/projects/{project_id}/evidence",
                json={
                    "source": "manual:task402-test",
                    "extracted_value": {"ok": True},
                    "conclusion": "Synthetic evidence for TASK-402.",
                },
            )
            evidence_id = evidence_response.json()["evidence_id"]
            await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/evaluate",
                json={"available_inputs": {"document_id": True}},
            )
            await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "RUNNING",
                    "reason": "Start execution.",
                    "source_type": "system",
                },
            )
            completed_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "COMPLETED",
                    "reason": "Capability generated evidence.",
                    "source_type": "capability",
                    "related_evidence_ids": [evidence_id],
                },
            )
            transitions_response = await client.get(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transitions"
            )
            return completed_response, transitions_response

    completed_response, transitions_response = asyncio.run(scenario())

    assert completed_response.status_code == 200
    completed = completed_response.json()
    assert completed["status"] == "COMPLETED"
    assert len(completed["related_evidence_ids"]) == 1

    assert transitions_response.status_code == 200
    transitions = transitions_response.json()["items"]
    assert [item["to_status"] for item in transitions] == [
        "NOT_STARTED",
        "READY",
        "RUNNING",
        "COMPLETED",
    ]
    assert all(item["trace_id"] for item in transitions)


def test_running_can_abstain_with_procedure_level_reason(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-402 Abstained"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state_id = init_response.json()["items"][0]["state_id"]
            await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/evaluate",
                json={"available_inputs": {"document_id": True}},
            )
            await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "RUNNING",
                    "reason": "Start execution.",
                    "source_type": "system",
                },
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "ABSTAINED",
                    "reason": "Evidence is insufficient for reliable judgment.",
                    "source_type": "capability",
                    "abstention_level": "procedure",
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ABSTAINED"
    assert payload["abstention_level"] == "procedure"


@pytest.mark.parametrize("abstention_level", ["field", "node"])
def test_running_can_abstain_with_field_and_node_level_reason(
    monkeypatch,
    tmp_path: Path,
    abstention_level: str,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": f"TASK-402 {abstention_level} Abstention"},
            )
            project_id = project_response.json()["project_id"]
            init_response = await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/initialize",
                json={},
            )
            state_id = init_response.json()["items"][0]["state_id"]
            await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/evaluate",
                json={"available_inputs": {"document_id": True}},
            )
            await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "RUNNING",
                    "reason": "Start execution.",
                    "source_type": "system",
                },
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-states/"
                f"{state_id}/transition",
                json={
                    "to_status": "ABSTAINED",
                    "reason": f"{abstention_level} evidence is insufficient.",
                    "source_type": "capability",
                    "abstention_level": abstention_level,
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ABSTAINED"
    assert payload["abstention_level"] == abstention_level
