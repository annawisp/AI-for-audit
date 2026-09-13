import asyncio
from pathlib import Path

from app.core.config import get_settings
from tests.asgi_client import app_client


def test_contract_extraction_creates_single_evidence_from_parsed_chunks(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                b"\n".join(
                    [
                        "甲方：北京客户有限公司".encode(),
                        "乙方：收入科技有限公司".encode(),
                        "合同期间：2026年1月1日至2026年12月31日".encode(),
                        "服务内容：年度软件订阅服务".encode(),
                        "履约义务：按月提供平台访问权限".encode(),
                        "合同金额：人民币100万元".encode(),
                        "付款条件：客户应在验收后30日内付款".encode(),
                        "验收条件：客户完成系统验收确认".encode(),
                        "违约责任：逾期付款按日计收违约金".encode(),
                    ]
                ),
            )
            parse_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            extraction_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={"extractor_type": "rule_based"},
            )
            evidence_id = extraction_response.json()["evidence_id"]
            evidence_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}"
            )
            list_response = await client.get(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction"
            )
            return parse_response, extraction_response, evidence_response, list_response

    parse_response, extraction_response, evidence_response, list_response = asyncio.run(scenario())

    assert parse_response.status_code == 201
    assert extraction_response.status_code == 201
    payload = extraction_response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["evidence_id"] is not None
    assert {field["status"] for field in payload["fields"]} == {"EXTRACTED"}
    assert _field(payload, "transaction_price")["value"] == "人民币100万元"
    assert _field(payload, "transaction_price")["source"]["source_locator"] == "line=6"
    obligations = _field(payload, "performance_obligations")
    assert len(obligations["value"]) == 1
    assert obligations["value"][0]["value"] == "按月提供平台访问权限"
    assert obligations["value"][0]["source"]["source_locator"] == "line=5"
    assert obligations["confidence_basis"]
    assert obligations["extraction_reason"] == "matching_labeled_clause_or_keyword_found"
    assert obligations["extraction_method"] == "rule_based"

    evidence = evidence_response.json()
    assert evidence["source"] == "capability:contract_extraction"
    assert evidence["node_status"] == "ready"
    assert evidence["confidence_level"] == "high"
    assert evidence["extracted_value"]["capability"] == "contract_extraction"
    assert len(evidence["extracted_value"]["fields"]) == 9

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1


def test_contract_extraction_marks_missing_fields_without_blocking_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                "甲方：北京客户有限公司\n乙方：收入科技有限公司\n合同金额：人民币50万元\n".encode(),
            )
            await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            extraction_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={},
            )
            evidence_id = extraction_response.json()["evidence_id"]
            evidence_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}"
            )
            return extraction_response, evidence_response

    extraction_response, evidence_response = asyncio.run(scenario())

    assert extraction_response.status_code == 201
    payload = extraction_response.json()
    assert payload["status"] == "PARTIAL"
    assert _field(payload, "acceptance_terms")["status"] == "MISSING_IN_DOCUMENT"
    assert _field(payload, "acceptance_terms")["abstention_reason"] == (
        "field_not_found_in_available_contract_text"
    )
    assert _field(payload, "acceptance_terms")["confidence_basis"]
    assert evidence_response.json()["node_status"] == "partial"
    assert evidence_response.json()["confidence_level"] == "medium"


def test_contract_extraction_blocks_when_document_has_not_been_parsed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                "甲方：北京客户有限公司\n".encode(),
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "BLOCKED"
    assert payload["evidence_id"] is None
    assert payload["failure_reason"] == "document_not_parsed"
    assert {field["status"] for field in payload["fields"]} == {"ABSTAINED"}
    assert {field["abstention_reason"] for field in payload["fields"]} == {
        "document_not_parsed"
    }


def test_contract_extraction_blocks_when_document_requires_ocr(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                b"%PDF-1.4\n% image only placeholder\n%%EOF",
                filename="scanned.pdf",
                content_type="application/pdf",
            )
            parse_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={"allow_ocr_fallback": True},
            )
            extraction_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={},
            )
            return parse_response, extraction_response

    parse_response, extraction_response = asyncio.run(scenario())

    assert parse_response.status_code == 201
    assert parse_response.json()["status"] == "OCR_REQUIRED"
    assert extraction_response.status_code == 201
    payload = extraction_response.json()
    assert payload["status"] == "BLOCKED"
    assert payload["evidence_id"] is None
    assert payload["failure_reason"] == "document_requires_ocr"
    assert {field["status"] for field in payload["fields"]} == {"ABSTAINED"}
    assert {field["abstention_reason"] for field in payload["fields"]} == {
        "document_requires_ocr"
    }


def test_contract_extraction_collects_multiple_performance_obligations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                "\n".join(
                    [
                        "甲方：北京客户有限公司",
                        "乙方：收入科技有限公司",
                        "合同期间：2026年度",
                        "服务内容：软件订阅和实施服务",
                        "履约义务：提供软件订阅服务",
                        "履约义务：提供上线实施服务",
                        "合同金额：人民币100万元",
                        "付款条件：分两期付款",
                        "验收条件：上线后验收",
                        "违约责任：逾期付款承担违约金",
                    ]
                ).encode(),
            )
            await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    obligations = _field(response.json(), "performance_obligations")
    assert obligations["status"] == "EXTRACTED"
    assert [item["value"] for item in obligations["value"]] == [
        "提供软件订阅服务",
        "提供上线实施服务",
    ]
    assert [item["source"]["source_locator"] for item in obligations["value"]] == [
        "line=5",
        "line=6",
    ]


def test_contract_extraction_marks_not_applicable_field(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                "\n".join(
                    [
                        "甲方：北京客户有限公司",
                        "乙方：收入科技有限公司",
                        "合同期间：2026年度",
                        "服务内容：软件订阅服务",
                        "履约义务：提供软件订阅服务",
                        "合同金额：人民币100万元",
                        "付款条件：分期付款",
                        "验收条件：客户线上确认",
                        "特殊条款：无特殊条款",
                    ]
                ).encode(),
            )
            await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    special_terms = _field(response.json(), "special_terms")
    assert special_terms["status"] == "NOT_APPLICABLE"
    assert special_terms["abstention_reason"] == "field_not_applicable_to_contract"
    assert special_terms["source"]["source_locator"] == "line=9"


def test_contract_extraction_requires_review_for_conflicting_evidence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                "\n".join(
                    [
                        "甲方：北京客户有限公司",
                        "乙方：收入科技有限公司",
                        "合同期间：2026年度",
                        "服务内容：软件订阅服务",
                        "履约义务：提供软件订阅服务",
                        "合同金额：人民币100万元",
                        "合同金额：人民币120万元",
                        "付款条件：分期付款",
                        "验收条件：客户线上确认",
                        "违约责任：逾期付款承担违约金",
                    ]
                ).encode(),
            )
            await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            extraction_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={},
            )
            evidence_id = extraction_response.json()["evidence_id"]
            evidence_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}"
            )
            return extraction_response, evidence_response

    extraction_response, evidence_response = asyncio.run(scenario())

    assert extraction_response.status_code == 201
    payload = extraction_response.json()
    assert payload["status"] == "REQUIRES_REVIEW"
    amount = _field(payload, "transaction_price")
    assert amount["status"] == "CONFLICTING_EVIDENCE"
    assert [item["value"] for item in amount["value"]] == ["人民币100万元", "人民币120万元"]
    assert amount["confidence_level"] == "low"
    assert evidence_response.json()["judgment_status"] == "PENDING_REVIEW"
    assert evidence_response.json()["confidence_level"] == "low"


def test_contract_extraction_rejects_unavailable_llm_extractor(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_contract(
                client,
                "甲方：北京客户有限公司\n".encode(),
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/contract-extraction",
                json={"extractor_type": "llm"},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "extractor_not_available"


async def _upload_contract(
    client,
    content: bytes,
    *,
    filename: str = "contract.txt",
    content_type: str = "text/plain",
):  # type: ignore[no-untyped-def]
    project_response = await client.post("/api/v1/projects", json={"name": "TASK-302"})
    project_id = project_response.json()["project_id"]
    upload_response = await client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": (filename, content, content_type)},
    )
    return project_id, upload_response.json()["document_id"]


def _field(payload: dict, field_name: str) -> dict:  # type: ignore[type-arg]
    return next(field for field in payload["fields"] if field["field_name"] == field_name)
