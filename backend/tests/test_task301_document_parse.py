import asyncio
import zipfile
from pathlib import Path

from app.core.config import get_settings
from tests.asgi_client import app_client


def test_txt_parse_creates_traceable_line_chunks(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_document(
                client,
                filename="contract.txt",
                content=b"Clause A\n\nClause B\n",
                content_type="text/plain",
            )
            parse_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={"allow_ocr_fallback": False},
            )
            chunks_response = await client.get(
                f"/api/v1/projects/{project_id}/documents/{document_id}/chunks"
            )
            return parse_response, chunks_response

    parse_response, chunks_response = asyncio.run(scenario())

    assert parse_response.status_code == 201
    parse_run = parse_response.json()
    assert parse_run["status"] == "COMPLETED"
    assert parse_run["chunks_count"] == 2
    assert parse_run["requires_ocr"] is False

    chunks = chunks_response.json()["items"]
    assert [chunk["text"] for chunk in chunks] == ["Clause A", "Clause B"]
    assert [chunk["sequence_number"] for chunk in chunks] == [1, 2]
    assert [chunk["source_locator"] for chunk in chunks] == ["line=1", "line=3"]


def test_csv_parse_preserves_row_locator(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_document(
                client,
                filename="sales.csv",
                content=b"invoice_no,amount\nINV-1,100\n",
                content_type="text/csv",
            )
            parse_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            chunks_response = await client.get(
                f"/api/v1/projects/{project_id}/documents/{document_id}/chunks"
            )
            return parse_response, chunks_response

    parse_response, chunks_response = asyncio.run(scenario())

    assert parse_response.status_code == 201
    assert parse_response.json()["status"] == "COMPLETED"
    chunk = chunks_response.json()["items"][0]
    assert chunk["chunk_type"] == "csv_row"
    assert chunk["row_number"] == 2
    assert chunk["source_locator"] == "row=2"
    assert chunk["content"]["row"] == {"invoice_no": "INV-1", "amount": "100"}


def test_pdf_without_text_marks_ocr_required(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_document(
                client,
                filename="scanned.pdf",
                content=b"%PDF-1.4\n% image only placeholder\n%%EOF",
                content_type="application/pdf",
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={"allow_ocr_fallback": True},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "OCR_REQUIRED"
    assert payload["requires_ocr"] is True
    assert payload["ocr_requested"] is True
    assert payload["ocr_status"] == "NOT_AVAILABLE"
    assert payload["failure_reason"] == "ocr_required"


def test_pdf_text_layer_parse_creates_page_chunk(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_document(
                client,
                filename="contract.pdf",
                content=b"%PDF-1.4\nBT\n(Revenue clause) Tj\nET\n%%EOF",
                content_type="application/pdf",
            )
            parse_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            chunks_response = await client.get(
                f"/api/v1/projects/{project_id}/documents/{document_id}/chunks"
            )
            return parse_response, chunks_response

    parse_response, chunks_response = asyncio.run(scenario())

    assert parse_response.status_code == 201
    assert parse_response.json()["status"] == "COMPLETED"
    chunk = chunks_response.json()["items"][0]
    assert chunk["chunk_type"] == "text"
    assert chunk["page_number"] == 1
    assert chunk["source_locator"] == "page=1"
    assert chunk["text"] == "Revenue clause"


def test_structurally_corrupted_docx_returns_blocked(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_document(
                client,
                filename="missing-document.docx",
                content=_zip_bytes({"word/styles.xml": "<styles />"}),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == "BLOCKED"
    assert payload["failure_reason"] == "docx_parse_failed:KeyError"


def test_whitespace_txt_abstains_without_fake_chunks(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_document(
                client,
                filename="blank.txt",
                content=b"  \n\t\n",
                content_type="text/plain",
            )
            parse_response = await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )
            chunks_response = await client.get(
                f"/api/v1/projects/{project_id}/documents/{document_id}/chunks"
            )
            return parse_response, chunks_response

    parse_response, chunks_response = asyncio.run(scenario())

    assert parse_response.status_code == 201
    assert parse_response.json()["status"] == "ABSTAINED"
    assert parse_response.json()["failure_reason"] == "no_parseable_content"
    assert chunks_response.json()["total"] == 0


def test_unsupported_parse_type_returns_blocked(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "audit.sqlite3"))
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "upload_allowed_extensions", ".txt,.pdf,.docx,.xlsx,.csv,.json")

    async def scenario():  # type: ignore[no-untyped-def]
        async with app_client() as client:
            project_id, document_id = await _upload_document(
                client,
                filename="unsupported.json",
                content=b"{\"sample\": true}",
                content_type="application/json",
            )
            return await client.post(
                f"/api/v1/projects/{project_id}/documents/{document_id}/parse",
                json={},
            )

    response = asyncio.run(scenario())

    assert response.status_code == 201
    assert response.json()["status"] == "BLOCKED"
    assert response.json()["failure_reason"] == "unsupported_file_type"


async def _upload_document(client, *, filename: str, content: bytes, content_type: str):  # type: ignore[no-untyped-def]
    project_response = await client.post("/api/v1/projects", json={"name": "TASK-301"})
    project_id = project_response.json()["project_id"]
    upload_response = await client.post(
        f"/api/v1/projects/{project_id}/documents",
        files={"file": (filename, content, content_type)},
    )
    return project_id, upload_response.json()["document_id"]


def _zip_bytes(files: dict[str, str]) -> bytes:
    output_path = Path(__file__).parent / "_task301_tmp.zip"
    with zipfile.ZipFile(output_path, "w") as archive:
        for filename, content in files.items():
            archive.writestr(filename, content)
    data = output_path.read_bytes()
    output_path.unlink()
    return data
