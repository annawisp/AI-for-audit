from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from app.schemas.document_parse import ChunkType, ParseStatus

PARSER_VERSION = "document_parser_v1"


@dataclass(frozen=True)
class ParsedChunk:
    chunk_type: ChunkType
    sequence_number: int
    text: str
    content: Any
    page_number: int | None
    sheet_name: str | None
    row_number: int | None
    paragraph_number: int | None
    table_index: int | None
    source_locator: str


@dataclass(frozen=True)
class ParseResult:
    status: ParseStatus
    parser_name: str
    parser_version: str
    requires_ocr: bool
    failure_reason: str | None
    chunks: list[ParsedChunk]


def parse_document(path: Path, original_filename: str) -> ParseResult:
    suffix = Path(original_filename).suffix.lower()
    try:
        if suffix == ".txt":
            return _parse_txt(path)
        if suffix == ".csv":
            return _parse_csv(path)
        if suffix == ".docx":
            return _parse_docx(path)
        if suffix == ".xlsx":
            return _parse_xlsx(path)
        if suffix == ".pdf":
            return _parse_pdf(path)
    except (
        OSError,
        UnicodeDecodeError,
        zipfile.BadZipFile,
        ElementTree.ParseError,
        KeyError,
        ValueError,
    ) as error:
        parser_type = suffix.lstrip(".") or "unknown"
        return _blocked_result(f"{parser_type}_parse_failed:{error.__class__.__name__}")

    return _blocked_result("unsupported_file_type")


def _parse_txt(path: Path) -> ParseResult:
    text = path.read_text(encoding="utf-8-sig")
    chunks = [
        ParsedChunk(
            chunk_type="paragraph",
            sequence_number=0,
            text=line.strip(),
            content={"line_number": line_number},
            page_number=None,
            sheet_name=None,
            row_number=line_number,
            paragraph_number=line_number,
            table_index=None,
            source_locator=f"line={line_number}",
        )
        for line_number, line in enumerate(text.splitlines(), start=1)
        if line.strip()
    ]
    return _result_for_chunks("txt", chunks)


def _parse_csv(path: Path) -> ParseResult:
    raw_text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw_text))
    rows = list(reader)
    if reader.fieldnames is None:
        return _blocked_result("csv_header_missing")
    chunks = [
        ParsedChunk(
            chunk_type="csv_row",
            sequence_number=0,
            text=json.dumps(row, ensure_ascii=False, default=str),
            content={"row": row, "fieldnames": reader.fieldnames},
            page_number=None,
            sheet_name=None,
            row_number=row_number,
            paragraph_number=None,
            table_index=None,
            source_locator=f"row={row_number}",
        )
        for row_number, row in enumerate(rows, start=2)
    ]
    return _result_for_chunks("csv", chunks)


def _parse_docx(path: Path) -> ParseResult:
    with zipfile.ZipFile(path) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)
    namespaces = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    chunks: list[ParsedChunk] = []
    paragraph_number = 0
    table_number = 0

    for child in root.findall(".//w:body/*", namespaces):
        if child.tag.endswith("}p"):
            text = _docx_text(child, namespaces)
            if text:
                paragraph_number += 1
                chunks.append(
                    ParsedChunk(
                        chunk_type="paragraph",
                        sequence_number=0,
                        text=text,
                        content={"text": text},
                        page_number=None,
                        sheet_name=None,
                        row_number=None,
                        paragraph_number=paragraph_number,
                        table_index=None,
                        source_locator=f"paragraph={paragraph_number}",
                    )
                )
        elif child.tag.endswith("}tbl"):
            table_number += 1
            for row_number, row in enumerate(child.findall(".//w:tr", namespaces), start=1):
                cells = row.findall("./w:tc", namespaces)
                values = [_docx_text(cell, namespaces) for cell in cells]
                if any(values):
                    chunks.append(
                        ParsedChunk(
                            chunk_type="table_row",
                            sequence_number=0,
                            text=json.dumps(values, ensure_ascii=False),
                            content={"cells": values},
                            page_number=None,
                            sheet_name=None,
                            row_number=row_number,
                            paragraph_number=None,
                            table_index=table_number,
                            source_locator=f"table={table_number};row={row_number}",
                        )
                    )

    return _result_for_chunks("docx", chunks)


def _parse_xlsx(path: Path) -> ParseResult:
    with zipfile.ZipFile(path) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        sheet_paths = _xlsx_sheet_paths(archive)
        chunks: list[ParsedChunk] = []
        for sheet_name, sheet_path in sheet_paths:
            root = ElementTree.fromstring(archive.read(sheet_path))
            namespaces = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for row in root.findall(".//x:sheetData/x:row", namespaces):
                row_number = int(row.attrib.get("r", "0") or "0")
                values = [
                    _xlsx_cell_value(cell, shared_strings, namespaces)
                    for cell in row.findall("./x:c", namespaces)
                ]
                if any(value != "" for value in values):
                    chunks.append(
                        ParsedChunk(
                            chunk_type="spreadsheet_row",
                            sequence_number=0,
                            text=json.dumps(values, ensure_ascii=False),
                            content={"cells": values},
                            page_number=None,
                            sheet_name=sheet_name,
                            row_number=row_number,
                            paragraph_number=None,
                            table_index=None,
                            source_locator=f"sheet={sheet_name};row={row_number}",
                        )
                    )
    return _result_for_chunks("xlsx", chunks)


def _parse_pdf(path: Path) -> ParseResult:
    raw = path.read_bytes()
    text = _extract_pdf_text_literals(raw)
    if not text.strip():
        return ParseResult(
            status="OCR_REQUIRED",
            parser_name="pdf_text",
            parser_version=PARSER_VERSION,
            requires_ocr=True,
            failure_reason="ocr_required",
            chunks=[],
        )
    chunks = [
        ParsedChunk(
            chunk_type="text",
            sequence_number=0,
            text=text.strip(),
            content={"text": text.strip()},
            page_number=1,
            sheet_name=None,
            row_number=None,
            paragraph_number=None,
            table_index=None,
            source_locator="page=1",
        )
    ]
    return _result_for_chunks("pdf_text", chunks)


def _docx_text(element: ElementTree.Element, namespaces: dict[str, str]) -> str:
    parts = [node.text or "" for node in element.findall(".//w:t", namespaces)]
    return "".join(parts).strip()


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    namespaces = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    return [
        "".join(node.text or "" for node in item.findall(".//x:t", namespaces))
        for item in root
    ]


def _xlsx_sheet_paths(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    workbook_ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    rel_targets = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall("./r:Relationship", rel_ns)
    }
    sheets: list[tuple[str, str]] = []
    for sheet in workbook.findall(".//x:sheets/x:sheet", workbook_ns):
        relationship_id = sheet.attrib[
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        ]
        target = rel_targets[relationship_id]
        sheet_path = f"xl/{target}" if not target.startswith("/") else target.lstrip("/")
        sheets.append((sheet.attrib["name"], sheet_path))
    return sheets


def _xlsx_cell_value(
    cell: ElementTree.Element,
    shared_strings: list[str],
    namespaces: dict[str, str],
) -> str:
    value_node = cell.find("./x:v", namespaces)
    if value_node is None or value_node.text is None:
        inline = cell.find(".//x:t", namespaces)
        return inline.text if inline is not None and inline.text is not None else ""
    value = value_node.text
    if cell.attrib.get("t") == "s":
        try:
            return shared_strings[int(value)]
        except (IndexError, ValueError):
            return ""
    return value


def _extract_pdf_text_literals(raw: bytes) -> str:
    decoded = raw.decode("latin-1", errors="ignore")
    literal_parts = re.findall(r"\(([^()]*)\)\s*Tj", decoded)
    array_parts = re.findall(r"\[((?:\([^()]*\)\s*)+)\]\s*TJ", decoded)
    for array in array_parts:
        literal_parts.extend(re.findall(r"\(([^()]*)\)", array))
    return "\n".join(_unescape_pdf_text(part) for part in literal_parts)


def _unescape_pdf_text(value: str) -> str:
    return (
        value.replace(r"\(", "(")
        .replace(r"\)", ")")
        .replace(r"\\", "\\")
        .replace(r"\n", "\n")
        .replace(r"\r", "\r")
        .replace(r"\t", "\t")
    )


def _result_for_chunks(parser_name: str, chunks: list[ParsedChunk]) -> ParseResult:
    if not chunks:
        return ParseResult(
            status="ABSTAINED",
            parser_name=parser_name,
            parser_version=PARSER_VERSION,
            requires_ocr=False,
            failure_reason="no_parseable_content",
            chunks=[],
        )
    sequenced_chunks = [
        ParsedChunk(
            chunk_type=chunk.chunk_type,
            sequence_number=sequence_number,
            text=chunk.text,
            content=chunk.content,
            page_number=chunk.page_number,
            sheet_name=chunk.sheet_name,
            row_number=chunk.row_number,
            paragraph_number=chunk.paragraph_number,
            table_index=chunk.table_index,
            source_locator=chunk.source_locator,
        )
        for sequence_number, chunk in enumerate(chunks, start=1)
    ]
    return ParseResult(
        status="COMPLETED",
        parser_name=parser_name,
        parser_version=PARSER_VERSION,
        requires_ocr=False,
        failure_reason=None,
        chunks=sequenced_chunks,
    )


def _blocked_result(failure_reason: str) -> ParseResult:
    return ParseResult(
        status="BLOCKED",
        parser_name="document_parser",
        parser_version=PARSER_VERSION,
        requires_ocr=False,
        failure_reason=failure_reason,
        chunks=[],
    )
