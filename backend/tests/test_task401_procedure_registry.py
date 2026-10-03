import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.orchestrator.procedure_registry import (
    DEFAULT_REGISTRY_PATH,
    ProcedureRegistryConfigError,
    list_procedures,
    load_procedure_registry,
)
from tests.asgi_client import app_client


def _registry_config() -> dict:
    return json.loads(DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))


def _write_registry_config(tmp_path: Path, config: dict) -> Path:
    config_path = tmp_path / "procedure_registry.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


def test_procedure_registry_lists_core_revenue_procedures() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.get("/api/v1/procedure-registry")

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    procedure_ids = {item["procedure_id"] for item in payload["items"]}
    assert payload["total"] == 5
    assert procedure_ids == {
        "P-REV-001",
        "P-REV-002",
        "P-REV-003",
        "P-REV-004",
        "P-REV-005",
    }


def test_procedure_registry_gets_one_definition() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.get("/api/v1/procedure-registry/P-REV-004")

    response = asyncio.run(scenario())

    assert response.status_code == 200
    procedure = response.json()["procedure"]
    assert procedure["procedure_name"] == "Revenue risk identification"
    assert procedure["capabilities"][0]["capability_id"] == "revenue_risk_identification"
    assert procedure["output_schema"]["evidence_source"] == (
        "capability:revenue_risk_identification"
    )


def test_data_reconciliation_evidence_source_matches_task305_route() -> None:
    procedure = list_procedures()[4]

    assert procedure.procedure_id == "P-REV-005"
    assert procedure.output_schema.evidence_source == (
        "capability:data_reconciliation_anomaly_detection"
    )
    assert procedure.capabilities[0].produces_evidence_source == (
        "capability:data_reconciliation_anomaly_detection"
    )


def test_procedure_registry_unknown_procedure_returns_404() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.get("/api/v1/procedure-registry/P-REV-999")

    response = asyncio.run(scenario())

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "procedure_not_found"


def test_contract_extraction_readiness_is_blocked_without_chunks() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.post(
                "/api/v1/procedure-registry/P-REV-002/readiness",
                json={"available_inputs": {}, "completed_procedures": ["P-REV-001"]},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_status"] == "BLOCKED"
    assert payload["missing_required_inputs"] == ["document_chunks"]
    assert payload["blocked_reason"] == "missing required inputs: document_chunks"


def test_contract_extraction_readiness_requires_upstream_completion() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.post(
                "/api/v1/procedure-registry/P-REV-002/readiness",
                json={"available_inputs": {"document_chunks": True}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_status"] == "BLOCKED"
    assert payload["missing_upstream_dependencies"] == ["P-REV-001"]


def test_revenue_risk_contract_only_is_partial_not_blocked() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.post(
                "/api/v1/procedure-registry/P-REV-004/readiness",
                json={"available_inputs": {"contract_extraction_evidence": True}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_status"] == "PARTIAL"
    assert payload["ready_inputs"] == ["contract_extraction_evidence"]
    assert "revenue_records" in payload["missing_optional_inputs"]


def test_data_reconciliation_without_any_input_is_blocked() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.post(
                "/api/v1/procedure-registry/P-REV-005/readiness",
                json={},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_status"] == "BLOCKED"
    assert "missing at least one input from" in payload["blocked_reason"]


def test_procedure_can_be_marked_not_applicable_without_execution() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.post(
                "/api/v1/procedure-registry/P-REV-005/readiness",
                json={
                    "mark_not_applicable": True,
                    "not_applicable_reason": "No revenue was generated in this period.",
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness_status"] == "NOT_APPLICABLE"
    assert payload["blocked_reason"] is None
    assert payload["explanation"] == "No revenue was generated in this period."


def test_registry_can_add_procedure_from_config_without_core_code_change(
    tmp_path: Path,
) -> None:
    config = _registry_config()
    new_procedure = deepcopy(config["procedures"][0])
    new_procedure["procedure_id"] = "P-REV-900"
    new_procedure["procedure_name"] = "Config-only procedure"
    config["procedures"].append(new_procedure)
    config_path = _write_registry_config(tmp_path, config)

    procedures = list_procedures(config_path)

    assert {procedure.procedure_id for procedure in procedures} >= {
        "P-REV-001",
        "P-REV-900",
    }


def test_registry_rejects_duplicate_procedure_id(tmp_path: Path) -> None:
    config = _registry_config()
    duplicate = deepcopy(config["procedures"][0])
    config["procedures"].append(duplicate)
    config_path = _write_registry_config(tmp_path, config)

    with pytest.raises(ProcedureRegistryConfigError, match="duplicate procedure_id"):
        load_procedure_registry(config_path)


def test_registry_rejects_unknown_capability(tmp_path: Path) -> None:
    config = _registry_config()
    config["procedures"][0]["capabilities"][0]["capability_id"] = "unknown_capability"
    config_path = _write_registry_config(tmp_path, config)

    with pytest.raises(
        ProcedureRegistryConfigError,
        match="references unknown capability",
    ):
        load_procedure_registry(config_path)


def test_registry_rejects_unknown_upstream_dependency(tmp_path: Path) -> None:
    config = _registry_config()
    config["procedures"][1]["upstream_dependencies"] = ["P-REV-999"]
    config_path = _write_registry_config(tmp_path, config)

    with pytest.raises(
        ProcedureRegistryConfigError,
        match="references unknown upstream procedure",
    ):
        load_procedure_registry(config_path)


def test_registry_rejects_invalid_execution_policy_strategy(tmp_path: Path) -> None:
    config = _registry_config()
    config["procedures"][0]["execution_policy"]["readiness_strategy"] = "always_ready"
    config_path = _write_registry_config(tmp_path, config)

    with pytest.raises(
        ProcedureRegistryConfigError,
        match="failed schema validation",
    ):
        load_procedure_registry(config_path)
