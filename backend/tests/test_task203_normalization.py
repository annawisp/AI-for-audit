import asyncio
from pathlib import Path

from app.core.config import get_settings
from tests.asgi_client import app_client


def test_amount_normalization_preserves_raw_standard_and_rule(
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
                json={"name": "TASK-203 Normalization"},
            )
            project_id = project_response.json()["project_id"]
            create_response = await client.post(
                f"/api/v1/projects/{project_id}/normalization/values",
                json={
                    "field_name": "contract_amount",
                    "value_type": "amount",
                    "raw_value": "¥1,200.50",
                },
            )
            list_response = await client.get(
                f"/api/v1/projects/{project_id}/normalization/values"
            )
            return create_response, list_response

    create_response, list_response = asyncio.run(scenario())

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["raw_value"] == "¥1,200.50"
    assert created["standard_value"] == "1200.50"
    assert created["normalization_rule"] == "amount_decimal_v1"
    assert created["quality_status"] == "ready"
    assert created["quality_score"] == 100

    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["total"] == 1
    assert listed["items"][0]["normalized_value_id"] == created["normalized_value_id"]


def test_unparseable_raw_value_is_partially_analyzable_not_rejected(
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
                json={"name": "TASK-203 Partial Value"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/normalization/values",
                json={
                    "field_name": "invoice_date",
                    "value_type": "date",
                    "raw_value": "date pending manual review",
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["raw_value"] == "date pending manual review"
    assert payload["standard_value"] is None
    assert payload["quality_status"] == "partial"
    assert payload["quality_score"] == 40
    assert payload["issues"] == ["date_parse_failed"]


def test_english_date_normalization_returns_iso_date(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-203 English Date"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/normalization/values",
                json={
                    "field_name": "contract_signed_date",
                    "value_type": "date",
                    "raw_value": "10 Sep 2026",
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["raw_value"] == "10 Sep 2026"
    assert payload["standard_value"] == "2026-09-10"
    assert payload["normalization_rule"] == "date_iso_yyyy_mm_dd_v1"
    assert payload["quality_status"] == "ready"
    assert payload["issues"] == []


def test_dataset_quality_returns_partial_readiness_for_low_quality_data(
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
                json={"name": "TASK-203 Dataset Quality"},
            )
            project_id = project_response.json()["project_id"]
            create_response = await client.post(
                f"/api/v1/projects/{project_id}/normalization/datasets/quality",
                json={
                    "dataset_name": "sales_ledger_sample",
                    "total_records": 10,
                    "usable_records": 3,
                    "partial_records": 4,
                    "rejected_records": 3,
                    "issues": ["missing_invoice_dates"],
                },
            )
            list_response = await client.get(
                f"/api/v1/projects/{project_id}/normalization/datasets/quality"
            )
            return create_response, list_response

    create_response, list_response = asyncio.run(scenario())

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["quality_score"] == 50
    assert created["quality_status"] == "partial"
    assert created["procedure_readiness"] == "PARTIAL"
    assert created["issues"] == ["missing_invoice_dates"]

    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1


def test_empty_dataset_abstains_procedure_readiness(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-203 Empty Dataset"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/normalization/datasets/quality",
                json={
                    "dataset_name": "empty_sales_ledger",
                    "total_records": 0,
                    "usable_records": 0,
                    "partial_records": 0,
                    "rejected_records": 0,
                },
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["quality_score"] == 0
    assert payload["quality_status"] == "abstained"
    assert payload["procedure_readiness"] == "ABSTAINED"
    assert payload["issues"] == ["dataset_has_no_records"]
