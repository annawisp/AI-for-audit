import asyncio
from pathlib import Path

from app.capabilities.data_reconciliation import run_data_reconciliation
from app.core.config import get_settings
from app.schemas.data_reconciliation import ReconciliationRecord
from tests.asgi_client import app_client


def test_task305_complete_data_creates_evidence_and_links(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            contract_evidence_id = await _create_contract_evidence(client, project_id)
            response = await client.post(
                f"/api/v1/projects/{project_id}/data-reconciliation",
                json={
                    "contract_evidence_id": contract_evidence_id,
                    "audit_period_start": "2026-01-01",
                    "audit_period_end": "2026-12-31",
                    "revenue_records": [_record("REV-1")],
                    "receivable_records": [_record("AR-1")],
                    "cash_receipt_records": [_record("CASH-1")],
                },
            )
            evidence_id = response.json()["evidence_id"]
            evidence_response = await client.get(
                f"/api/v1/projects/{project_id}/evidence/{evidence_id}"
            )
            list_response = await client.get(
                f"/api/v1/projects/{project_id}/data-reconciliation"
            )
            return response, evidence_response, list_response

    response, evidence_response, list_response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["matched_links"]
    first_link = payload["matched_links"][0]
    assert first_link["link_method"]
    assert first_link["link_confidence"]
    assert "source_record_id" in first_link
    assert "target_record_id" in first_link
    assert "match_status" in first_link

    evidence = evidence_response.json()
    assert evidence["source"] == "capability:data_reconciliation_anomaly_detection"
    assert evidence["extracted_value"]["capability"] == "data_reconciliation"
    assert list_response.json()["total"] == 1


def test_task305_missing_cash_is_not_provided_not_generic_insufficient(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            return await client.post(
                f"/api/v1/projects/{project_id}/data-reconciliation",
                json={
                    "revenue_records": [_record("REV-1")],
                    "receivable_records": [_record("AR-1")],
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    cash_node = _node(payload, "revenue_cash_matching")
    assert cash_node["status"] == "NOT_PROVIDED"
    assert any("Cash receipt records were not provided" in item for item in payload["limitations"])


def test_task305_unmatched_records_are_explicitly_unmatched(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            return await client.post(
                f"/api/v1/projects/{project_id}/data-reconciliation",
                json={
                    "revenue_records": [_record("REV-1", invoice_number="INV-1")],
                    "receivable_records": [
                        _record(
                            "AR-1",
                            invoice_number="INV-2",
                            contract_reference="CON-2",
                            customer_name="OTHER",
                            amount="9999",
                        )
                    ],
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    revenue_ar_node = _node(payload, "revenue_receivable_matching")
    assert revenue_ar_node["unmatched_count"] == 1
    assert any(
        exception["status"] == "UNMATCHED"
        for exception in revenue_ar_node["exceptions"]
    )


def test_task305_anomaly_signal_is_not_audit_conclusion(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            return await client.post(
                f"/api/v1/projects/{project_id}/data-reconciliation",
                json={
                    "revenue_records": [
                        _record("REV-1", amount="-1000"),
                        _record("REV-2", amount="1000"),
                        _record("REV-3", amount="1000"),
                    ],
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    anomaly_node = _node(payload, "anomaly_detection")
    assert anomaly_node["exceptions"]
    for exception in anomaly_node["exceptions"]:
        assert exception.get("is_audit_conclusion") is False
        assert exception.get("recommended_follow_up")


def test_task305_rejects_wrong_contract_evidence_source(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id = await _create_project(client)
            evidence_id = await _create_evidence(
                client,
                project_id,
                "manual:test",
                {"fields": []},
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/data-reconciliation",
                json={"contract_evidence_id": evidence_id},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_contract_evidence_source"


def test_task406_does_not_reuse_one_receivable_for_two_revenue_records() -> None:
    result = run_data_reconciliation(
        project={"name": "TASK-406"},
        contract_evidence=None,
        revenue_recognition_evidence=None,
        revenue_risk_evidence=None,
        revenue_records=[
            _reconciliation_record("REV-1"),
            _reconciliation_record("REV-2"),
        ],
        receivable_records=[_reconciliation_record("AR-1")],
        cash_receipt_records=[],
    )

    revenue_ar = _result_node(result, "revenue_receivable_matching")
    assert revenue_ar.matched_count == 1
    assert revenue_ar.unmatched_count == 1
    assert any(link.match_status == "AMBIGUOUS" for link in result.matched_links)


def test_task406_invoice_match_with_conflicting_identity_is_not_matched() -> None:
    result = run_data_reconciliation(
        project={"name": "TASK-406"},
        contract_evidence=None,
        revenue_recognition_evidence=None,
        revenue_risk_evidence=None,
        revenue_records=[
            _reconciliation_record("REV-1", invoice_number="INV-1", amount="1000")
        ],
        receivable_records=[
            _reconciliation_record(
                "AR-1",
                invoice_number="INV-1",
                contract_reference="CON-2",
                customer_name="OTHER",
                amount="9000",
            )
        ],
        cash_receipt_records=[],
    )

    revenue_ar = _result_node(result, "revenue_receivable_matching")
    assert revenue_ar.status == "CONFLICTING"
    assert revenue_ar.matched_count == 0
    assert any(link.match_status == "CONFLICTING" for link in result.matched_links)
    assert result.overall_exception_level == "high"


def test_task406_contract_amount_normalizes_wan_unit() -> None:
    result = run_data_reconciliation(
        project={"name": "TASK-406"},
        contract_evidence={
            "evidence_id": "E-1",
            "source": "capability:contract_extraction",
            "extracted_value": {
                "fields": [
                    {"field_name": "transaction_price", "value": "人民币100万元"},
                    {"field_name": "customer_party", "value": "客户A"},
                ]
            },
        },
        revenue_recognition_evidence=None,
        revenue_risk_evidence=None,
        revenue_records=[
            _reconciliation_record("REV-1", customer_name="客户A", amount="1000000")
        ],
        receivable_records=[],
        cash_receipt_records=[],
    )

    contract_node = _result_node(result, "contract_revenue_matching")
    assert contract_node.status == "COMPLETE"
    assert contract_node.matched_count == 1
    assert not contract_node.exceptions


def test_task406_empty_inputs_have_no_business_low_exception_level() -> None:
    result = run_data_reconciliation(
        project={"name": "TASK-406"},
        contract_evidence=None,
        revenue_recognition_evidence=None,
        revenue_risk_evidence=None,
        revenue_records=[],
        receivable_records=[],
        cash_receipt_records=[],
    )

    assert result.status == "INSUFFICIENT_DATA"
    assert result.overall_exception_level is None
    assert result.coverage.coverage_ratio == 0


async def _create_project(client):  # type: ignore[no-untyped-def]
    response = await client.post(
        "/api/v1/projects",
        json={
            "name": "TASK-305",
            "audit_period_start": "2026-01-01",
            "audit_period_end": "2026-12-31",
        },
    )
    return response.json()["project_id"]


async def _create_contract_evidence(client, project_id: str):  # type: ignore[no-untyped-def]
    return await _create_evidence(
        client,
        project_id,
        "capability:contract_extraction",
        {
            "fields": [
                {
                    "field_name": "transaction_price",
                    "value": "1000",
                },
                {
                    "field_name": "customer_party",
                    "value": "ACME",
                },
            ]
        },
    )


async def _create_evidence(
    client,
    project_id: str,
    source: str,
    extracted_value: dict,
):  # type: ignore[type-arg,no-untyped-def]
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


def _record(
    record_id: str,
    *,
    invoice_number: str = "INV-1",
    contract_reference: str = "CON-1",
    customer_name: str = "ACME",
    amount: str = "1000",
) -> dict[str, str]:
    return {
        "record_id": record_id,
        "contract_reference": contract_reference,
        "customer_name": customer_name,
        "invoice_number": invoice_number,
        "recognition_date": "2026-03-31",
        "due_date": "2026-04-30",
        "receipt_date": "2026-04-15",
        "amount": amount,
    }


def _reconciliation_record(
    record_id: str,
    *,
    invoice_number: str = "INV-1",
    contract_reference: str = "CON-1",
    customer_name: str = "ACME",
    amount: str = "1000",
) -> ReconciliationRecord:
    return ReconciliationRecord(
        record_id=record_id,
        contract_reference=contract_reference,
        customer_name=customer_name,
        invoice_number=invoice_number,
        recognition_date="2026-03-31",
        due_date="2026-04-30",
        receipt_date="2026-04-15",
        amount=amount,
    )


def _node(payload: dict, node_id: str) -> dict:  # type: ignore[type-arg]
    return next(node for node in payload["nodes"] if node["node_id"] == node_id)


def _result_node(result, node_id: str):  # type: ignore[no-untyped-def]
    return next(node for node in result.nodes if node.node_id == node_id)
