import asyncio
from pathlib import Path

from app.core.config import get_settings
from tests.asgi_client import app_client


def test_revenue_recognition_completes_contract_level_without_revenue_records(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, contract_evidence_id = await _create_contract_evidence(
                client,
                [
                    "甲方：北京客户有限公司",
                    "乙方：收入科技有限公司",
                    "合同期间：2026年1月1日至2026年12月31日",
                    "服务内容：年度软件订阅服务",
                    "履约义务：按月提供平台访问权限",
                    "合同金额：人民币100万元",
                    "付款条件：客户应在验收后30日内付款",
                    "验收条件：无需验收",
                    "特殊条款：无特殊条款",
                ],
            )
            recognition_response = await client.post(
                f"/api/v1/projects/{project_id}/revenue-recognition",
                json={"contract_evidence_id": contract_evidence_id},
            )
            evidence_id = recognition_response.json()["evidence_id"]
            evidence_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}"
            )
            list_response = await client.get(f"/api/v1/projects/{project_id}/revenue-recognition")
            return recognition_response, evidence_response, list_response

    recognition_response, evidence_response, list_response = asyncio.run(scenario())

    assert recognition_response.status_code == 201
    payload = recognition_response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["evidence_id"] is not None
    assert payload["coverage"]["contract_level_analysis"] is True
    assert payload["coverage"]["revenue_record_analysis"] is False
    assert "Revenue detail records were not provided." in payload["limitations"]
    assert "amount-level reconciliation" in payload["impact"]
    assert _node(payload, "revenue_record_reconciliation")["status"] == "ABSTAINED"
    assert _node(payload, "revenue_timing_assessment")["status"] == "COMPLETED"

    evidence = evidence_response.json()
    assert evidence["source"] == "capability:revenue_recognition_analysis"
    assert evidence["node_status"] == "ready"
    assert evidence["judgment_status"] == "AI_GENERATED"
    assert evidence["extracted_value"]["capability"] == "revenue_recognition_analysis"

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1


def test_revenue_recognition_requires_review_for_multiple_obligations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, contract_evidence_id = await _create_contract_evidence(
                client,
                [
                    "甲方：北京客户有限公司",
                    "乙方：收入科技有限公司",
                    "合同期间：2026年度",
                    "服务内容：软件订阅和上线实施服务",
                    "履约义务：提供软件订阅服务",
                    "履约义务：提供上线实施服务",
                    "合同金额：人民币100万元",
                    "付款条件：分两期付款",
                    "验收条件：上线后验收",
                    "特殊条款：无特殊条款",
                ],
            )
            recognition_response = await client.post(
                f"/api/v1/projects/{project_id}/revenue-recognition",
                json={"contract_evidence_id": contract_evidence_id},
            )
            evidence_id = recognition_response.json()["evidence_id"]
            evidence_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}"
            )
            return recognition_response, evidence_response

    recognition_response, evidence_response = asyncio.run(scenario())

    assert recognition_response.status_code == 201
    payload = recognition_response.json()
    assert payload["status"] == "REQUIRES_REVIEW"
    obligation_node = _node(payload, "performance_obligation_assessment")
    assert obligation_node["status"] == "REQUIRES_REVIEW"
    assert obligation_node["review_reason"] == "multiple_obligations_without_allocation_basis"
    assert "One or more analysis nodes require manual review." in payload["limitations"]
    assert evidence_response.json()["judgment_status"] == "PENDING_REVIEW"
    assert evidence_response.json()["node_status"] == "partial"


def test_revenue_recognition_uses_optional_revenue_records_without_requiring_them(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, contract_evidence_id = await _create_contract_evidence(
                client,
                [
                    "甲方：北京客户有限公司",
                    "乙方：收入科技有限公司",
                    "合同期间：2026年度",
                    "服务内容：年度软件订阅服务",
                    "履约义务：按月提供平台访问权限",
                    "合同金额：人民币100万元",
                    "付款条件：客户按季度付款",
                    "验收条件：无需验收",
                    "特殊条款：无特殊条款",
                ],
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/revenue-recognition",
                json={
                    "contract_evidence_id": contract_evidence_id,
                    "revenue_records": [
                        {
                            "record_id": "REV-1",
                            "recognition_date": "2026-03-31",
                            "amount": "250000",
                        }
                    ],
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["coverage"]["revenue_record_analysis"] is True
    assert _node(payload, "revenue_record_reconciliation")["status"] == "COMPLETED"
    assert "Revenue detail records were not provided." not in payload["limitations"]


def test_revenue_recognition_marks_incomplete_revenue_records_partial(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, contract_evidence_id = await _create_contract_evidence(
                client,
                [
                    "甲方：北京客户有限公司",
                    "乙方：收入科技有限公司",
                    "合同期间：2026年度",
                    "服务内容：年度软件订阅服务",
                    "履约义务：按月提供平台访问权限",
                    "合同金额：人民币100万元",
                    "付款条件：客户按季度付款",
                    "验收条件：无需验收",
                    "特殊条款：无特殊条款",
                ],
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/revenue-recognition",
                json={
                    "contract_evidence_id": contract_evidence_id,
                    "revenue_records": [{"record_id": "REV-1", "amount": "250000"}],
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    record_node = _node(payload, "revenue_record_reconciliation")
    assert record_node["status"] == "PARTIAL"
    assert record_node["review_reason"] == "revenue_records_incomplete"
    assert payload["status"] == "COMPLETED"


def test_revenue_recognition_rejects_wrong_evidence_source(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post("/api/v1/projects", json={"name": "TASK-303"})
            project_id = project_response.json()["project_id"]
            evidence_response = await client.post(
                f"/api/v1/projects/{project_id}/evidence",
                json={
                    "source": "manual:test",
                    "extracted_value": {"sample": True},
                    "conclusion": "Manual evidence.",
                    "execution_status": "completed",
                    "node_status": "ready",
                    "judgment_status": "AI_GENERATED",
                },
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/revenue-recognition",
                json={"contract_evidence_id": evidence_response.json()["evidence_id"]},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_contract_evidence_source"


def test_revenue_recognition_rejects_unavailable_llm_analyzer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, contract_evidence_id = await _create_contract_evidence(
                client,
                ["甲方：北京客户有限公司", "履约义务：提供软件订阅服务"],
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/revenue-recognition",
                json={"contract_evidence_id": contract_evidence_id, "analyzer_type": "llm"},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "analyzer_not_available"


async def _create_contract_evidence(client, lines: list[str]):  # type: ignore[no-untyped-def]
    project_response = await client.post(
        "/api/v1/projects",
        json={
            "name": "TASK-303",
            "audit_period_start": "2026-01-01",
            "audit_period_end": "2026-12-31",
        },
    )
    project_id = project_response.json()["project_id"]
    upload_response = await client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": ("contract.txt", "\n".join(lines).encode(), "text/plain")},
    )
    document_id = upload_response.json()["document_id"]
    await client.post(f"/api/v1/projects/{project_id}/documents/{document_id}/parse", json={})
    extraction_response = await client.post(
        f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
        json={},
    )
    return project_id, extraction_response.json()["evidence_id"]


def _node(payload: dict, node_name: str) -> dict:  # type: ignore[type-arg]
    return next(node for node in payload["nodes"] if node["node_name"] == node_name)
