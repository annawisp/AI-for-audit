from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.schemas.contract_extraction import ContractFieldExtraction, SourceLocation

EXTRACTOR_VERSION = "contract_extraction_rule_v1"


@dataclass(frozen=True)
class FieldRule:
    field_name: str
    display_name: str
    labels: tuple[str, ...]
    keywords: tuple[str, ...]
    collect_multiple: bool = False
    not_applicable_markers: tuple[str, ...] = ()


FIELD_RULES: tuple[FieldRule, ...] = (
    FieldRule(
        field_name="customer_party",
        display_name="合同甲方/客户",
        labels=("甲方", "客户", "买方", "委托方"),
        keywords=("甲方", "客户", "买方", "委托方"),
    ),
    FieldRule(
        field_name="supplier_party",
        display_name="合同乙方/供应方",
        labels=("乙方", "供应方", "卖方", "受托方", "服务方"),
        keywords=("乙方", "供应方", "卖方", "受托方", "服务方"),
    ),
    FieldRule(
        field_name="contract_period",
        display_name="合同期间/履约期间",
        labels=("合同期间", "服务期限", "履约期限", "合同期限", "有效期"),
        keywords=("合同期间", "服务期限", "履约期限", "合同期限", "有效期"),
    ),
    FieldRule(
        field_name="goods_or_services",
        display_name="商品或服务内容",
        labels=("服务内容", "商品", "合同标的", "项目内容", "销售内容"),
        keywords=("服务内容", "商品", "合同标的", "项目内容", "销售内容"),
    ),
    FieldRule(
        field_name="performance_obligations",
        display_name="履约义务",
        labels=("履约义务", "义务", "交付义务", "服务义务"),
        keywords=("履约义务", "交付义务", "服务义务"),
        collect_multiple=True,
    ),
    FieldRule(
        field_name="transaction_price",
        display_name="交易价格/合同金额",
        labels=("合同金额", "交易价格", "合同价款", "价款", "总金额", "费用"),
        keywords=("合同金额", "交易价格", "合同价款", "总金额", "费用"),
    ),
    FieldRule(
        field_name="payment_terms",
        display_name="收款条件/付款节点",
        labels=("付款方式", "付款条件", "收款条件", "付款节点", "结算方式"),
        keywords=("付款方式", "付款条件", "收款条件", "付款节点", "结算方式"),
    ),
    FieldRule(
        field_name="acceptance_terms",
        display_name="验收条件/交付条件",
        labels=("验收条件", "验收", "交付条件", "交付", "验收标准"),
        keywords=("验收条件", "验收", "交付条件", "验收标准"),
        not_applicable_markers=("无需验收", "不需要验收", "验收不适用"),
    ),
    FieldRule(
        field_name="special_terms",
        display_name="特殊条款",
        labels=("特殊条款", "违约责任", "质保", "退货", "可变对价", "退款"),
        keywords=("特殊条款", "违约责任", "质保", "退货", "可变对价", "退款"),
        collect_multiple=True,
        not_applicable_markers=("无特殊条款", "无退货", "无质保", "不适用特殊条款"),
    ),
)


def extract_contract_fields(chunks: list[dict[str, Any]]) -> list[ContractFieldExtraction]:
    searchable_chunks = [chunk for chunk in chunks if str(chunk.get("text", "")).strip()]
    return [_extract_field(rule, searchable_chunks) for rule in FIELD_RULES]


def fields_for_unavailable_document(status: str) -> list[ContractFieldExtraction]:
    reason = "document_requires_ocr" if status == "DOCUMENT_REQUIRES_OCR" else "document_not_parsed"
    return [
        ContractFieldExtraction(
            field_name=rule.field_name,
            display_name=rule.display_name,
            status="ABSTAINED",
            value=None,
            source=None,
            confidence_level=None,
            confidence_basis="No searchable contract text is available for field extraction.",
            extraction_reason=reason,
            extraction_method="rule_based",
            abstention_reason=reason,
        )
        for rule in FIELD_RULES
    ]


def build_contract_evidence_value(
    *,
    document_id: str,
    fields: list[ContractFieldExtraction],
    extractor_type: str,
) -> dict[str, Any]:
    return {
        "capability": "contract_extraction",
        "document_id": document_id,
        "extractor_type": extractor_type,
        "extractor_version": EXTRACTOR_VERSION,
        "fields": [field.model_dump() for field in fields],
    }


def extraction_summary(fields: list[ContractFieldExtraction]) -> tuple[str, str, str]:
    extracted_count = sum(1 for field in fields if field.status == "EXTRACTED")
    resolved_count = sum(
        1 for field in fields if field.status in {"EXTRACTED", "NOT_APPLICABLE"}
    )
    conflict_count = sum(1 for field in fields if field.status == "CONFLICTING_EVIDENCE")
    review_count = sum(1 for field in fields if field.confidence_level == "low")
    if conflict_count > 0 or review_count > 0:
        return "REQUIRES_REVIEW", "partial", "low"
    if resolved_count == len(fields):
        return "COMPLETED", "ready", "high"
    if extracted_count > 0:
        return "PARTIAL", "partial", "medium"
    return "ABSTAINED", "abstained", "low"


def _extract_field(rule: FieldRule, chunks: list[dict[str, Any]]) -> ContractFieldExtraction:
    matches = [_match_chunk(rule, chunk) for chunk in chunks if _has_keyword(rule, chunk)]
    matches = [match for match in matches if match is not None]
    labeled_matches = [match for match in matches if match["match_type"] == "labeled"]
    if labeled_matches:
        matches = labeled_matches
    not_applicable_match = _find_not_applicable(rule, chunks)
    if not_applicable_match is not None:
        return ContractFieldExtraction(
            field_name=rule.field_name,
            display_name=rule.display_name,
            status="NOT_APPLICABLE",
            value=None,
            source=not_applicable_match["source"],
            sources=[not_applicable_match["source"]],
            confidence_level="medium",
            confidence_basis="Contract text explicitly indicates the field is not applicable.",
            extraction_reason="explicit_not_applicable_marker_found",
            extraction_method="rule_based",
            abstention_reason="field_not_applicable_to_contract",
        )
    if not matches:
        return ContractFieldExtraction(
            field_name=rule.field_name,
            display_name=rule.display_name,
            status="MISSING_IN_DOCUMENT",
            value=None,
            source=None,
            confidence_level=None,
            confidence_basis="No matching keyword or labeled clause was found in available text.",
            extraction_reason="field_not_found_in_available_contract_text",
            extraction_method="rule_based",
            abstention_reason="field_not_found_in_available_contract_text",
        )

    if rule.collect_multiple:
        sources = [match["source"] for match in matches]
        value = [
            {"value": match["value"], "source": match["source"].model_dump()}
            for match in matches
        ]
        return ContractFieldExtraction(
            field_name=rule.field_name,
            display_name=rule.display_name,
            status="EXTRACTED",
            value=value,
            source=matches[0]["source"],
            sources=sources,
            confidence_level="medium",
            confidence_basis="One or more matching clauses were extracted from contract chunks.",
            extraction_reason="matching_labeled_clause_or_keyword_found",
            extraction_method="rule_based",
            abstention_reason=None,
        )

    unique_values = _unique_values(matches)
    if len(unique_values) > 1:
        sources = [match["source"] for match in matches]
        return ContractFieldExtraction(
            field_name=rule.field_name,
            display_name=rule.display_name,
            status="CONFLICTING_EVIDENCE",
            value=[
                {"value": match["value"], "source": match["source"].model_dump()}
                for match in matches
            ],
            source=matches[0]["source"],
            sources=sources,
            confidence_level="low",
            confidence_basis="Multiple different values were found for the same field.",
            extraction_reason="conflicting_values_found_in_contract_text",
            extraction_method="rule_based",
            abstention_reason="conflicting_evidence_requires_review",
        )

    first_match = matches[0]
    return ContractFieldExtraction(
        field_name=rule.field_name,
        display_name=rule.display_name,
        status="EXTRACTED",
        value=first_match["value"],
        source=first_match["source"],
        sources=[first_match["source"]],
        confidence_level="medium",
        confidence_basis="A matching labeled clause or keyword was found in contract chunks.",
        extraction_reason="matching_labeled_clause_or_keyword_found",
        extraction_method="rule_based",
        abstention_reason=None,
    )


def _has_keyword(rule: FieldRule, chunk: dict[str, Any]) -> bool:
    text = str(chunk.get("text", ""))
    return any(keyword in text for keyword in rule.keywords)


def _match_chunk(rule: FieldRule, chunk: dict[str, Any]) -> dict[str, Any] | None:
    text = " ".join(str(chunk.get("text", "")).split())
    if not text:
        return None
    labeled_value = _extract_labeled_value(text, rule.labels)
    value = labeled_value or text
    return {
        "value": value,
        "match_type": "labeled" if labeled_value is not None else "keyword",
        "source": SourceLocation(
            chunk_id=str(chunk.get("chunk_id")) if chunk.get("chunk_id") else None,
            source_locator=chunk.get("source_locator"),
            page_number=chunk.get("page_number"),
            paragraph_number=chunk.get("paragraph_number"),
            row_number=chunk.get("row_number"),
            sheet_name=chunk.get("sheet_name"),
            text_excerpt=text[:500],
        ),
    }


def _find_not_applicable(
    rule: FieldRule,
    chunks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not rule.not_applicable_markers:
        return None
    for chunk in chunks:
        text = " ".join(str(chunk.get("text", "")).split())
        if any(marker in text for marker in rule.not_applicable_markers):
            return {
                "value": None,
                "source": SourceLocation(
                    chunk_id=str(chunk.get("chunk_id")) if chunk.get("chunk_id") else None,
                    source_locator=chunk.get("source_locator"),
                    page_number=chunk.get("page_number"),
                    paragraph_number=chunk.get("paragraph_number"),
                    row_number=chunk.get("row_number"),
                    sheet_name=chunk.get("sheet_name"),
                    text_excerpt=text[:500],
                ),
            }
    return None


def _unique_values(matches: list[dict[str, Any]]) -> set[str]:
    return {" ".join(str(match["value"]).split()) for match in matches}


def _extract_labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    joined_labels = "|".join(re.escape(label) for label in labels)
    pattern = rf"(?:{joined_labels})\s*[:：]\s*(.+)"
    match = re.search(pattern, text)
    if match is None:
        return None
    return match.group(1).strip(" 。；;")
