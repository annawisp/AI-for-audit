import asyncio
from pathlib import Path

from app.core.config import get_settings
from tests.asgi_client import app_client


def _prepare_test_settings(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))


def test_dependency_graph_lists_default_nodes_and_edges() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            return await client.get("/api/v1/procedure-dependencies")

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["graph_version"] == "procedure_dependency_graph_v1"
    assert payload["total_nodes"] >= 11
    assert payload["total_edges"] >= 11
    node_ids = {node["node_id"] for node in payload["nodes"]}
    assert {
        "P02.performance_obligation",
        "P03.transaction_price",
        "P04.payment_terms",
    } <= node_ids


def test_dependency_graph_queries_upstream_and_downstream() -> None:
    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            upstream = await client.get(
                "/api/v1/procedure-dependencies/P05.revenue_timing/upstream"
            )
            downstream = await client.get(
                "/api/v1/procedure-dependencies/P02.performance_obligation/downstream"
            )
            return upstream, downstream

    upstream_response, downstream_response = asyncio.run(scenario())

    assert upstream_response.status_code == 200
    upstream = upstream_response.json()
    assert upstream["node"]["node_id"] == "P05.revenue_timing"
    assert upstream["related_nodes"][0]["node_id"] == "P02.performance_obligation"

    assert downstream_response.status_code == 200
    downstream = downstream_response.json()
    assert downstream["node"]["node_id"] == "P02.performance_obligation"
    assert downstream["related_nodes"][0]["node_id"] == "P05.revenue_timing"


def test_p02_abstained_only_impacts_dependent_revenue_timing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-403 Local Failure"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-dependencies/impact",
                json={"node_statuses": {"P02.performance_obligation": "ABSTAINED"}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    impacted_ids = {item["node_id"] for item in payload["impacted_nodes"]}
    unaffected_ids = {item["node_id"] for item in payload["unaffected_nodes"]}
    assert impacted_ids == {"P05.revenue_timing"}
    assert "P03.transaction_price" in unaffected_ids
    assert "P04.payment_terms" in unaffected_ids
    assert payload["impacted_nodes"][0]["recommended_status"] == "ABSTAINED"


def test_contract_only_missing_revenue_records_does_not_abstain_whole_graph(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-403 Contract Only"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-dependencies/impact",
                json={"node_statuses": {"D01.revenue_records": "BLOCKED"}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    impacts = {
        item["node_id"]: item["recommended_status"]
        for item in payload["impacted_nodes"]
    }
    unaffected_ids = {item["node_id"] for item in payload["unaffected_nodes"]}
    assert impacts["P06.risk_identification"] == "PARTIAL"
    assert impacts["P07.data_reconciliation"] == "BLOCKED"
    assert "P02.performance_obligation" in unaffected_ids
    assert "P03.transaction_price" in unaffected_ids
    assert not all(status == "ABSTAINED" for status in impacts.values())


def test_optional_special_terms_issue_degrades_risk_to_partial(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-403 Optional Edge"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-dependencies/impact",
                json={"node_statuses": {"C01.special_terms": "ABSTAINED"}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 200
    payload = response.json()
    assert payload["impacted_nodes"][0]["node_id"] == "P06.risk_identification"
    assert payload["impacted_nodes"][0]["recommended_status"] == "PARTIAL"
    assert payload["impacted_nodes"][0]["dependency_type"] == "optional"


def test_unknown_dependency_node_returns_controlled_404(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _prepare_test_settings(monkeypatch, tmp_path)

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_response = await client.post(
                "/api/v1/projects",
                json={"name": "TASK-403 Unknown Node"},
            )
            project_id = project_response.json()["project_id"]
            return await client.post(
                f"/api/v1/projects/{project_id}/procedure-dependencies/impact",
                json={"node_statuses": {"missing.node": "BLOCKED"}},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "dependency_node_not_found"
