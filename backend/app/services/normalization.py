from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.normalization import ProcedureReadiness, QualityStatus, ValueType


@dataclass(frozen=True)
class NormalizationResult:
    standard_value: Any
    normalization_rule: str
    quality_status: QualityStatus
    quality_score: int
    issues: list[str]


@dataclass(frozen=True)
class DatasetQualityResult:
    quality_score: int
    quality_status: QualityStatus
    procedure_readiness: ProcedureReadiness
    issues: list[str]


DEFAULT_RULES: dict[ValueType, str] = {
    "amount": "amount_decimal_v1",
    "date": "date_iso_yyyy_mm_dd_v1",
    "currency": "currency_iso_4217_v1",
    "number": "number_decimal_v1",
    "text": "text_trim_v1",
}


def normalize_value(
    *,
    value_type: ValueType,
    raw_value: Any,
    normalization_rule: str | None = None,
) -> NormalizationResult:
    rule = normalization_rule or DEFAULT_RULES[value_type]
    if raw_value is None or str(raw_value).strip() == "":
        return NormalizationResult(
            standard_value=None,
            normalization_rule=rule,
            quality_status="abstained",
            quality_score=0,
            issues=["raw_value_missing"],
        )

    try:
        if value_type == "amount":
            standard_value = _normalize_decimal(raw_value)
        elif value_type == "number":
            standard_value = _normalize_decimal(raw_value)
        elif value_type == "date":
            standard_value = _normalize_date(raw_value)
        elif value_type == "currency":
            standard_value = _normalize_currency(raw_value)
        else:
            standard_value = str(raw_value).strip()
    except ValueError as error:
        return NormalizationResult(
            standard_value=None,
            normalization_rule=rule,
            quality_status="partial",
            quality_score=40,
            issues=[str(error)],
        )

    return NormalizationResult(
        standard_value=standard_value,
        normalization_rule=rule,
        quality_status="ready",
        quality_score=100,
        issues=[],
    )


def assess_dataset_quality(
    *,
    total_records: int,
    usable_records: int,
    partial_records: int,
    rejected_records: int,
    issues: list[str] | None = None,
) -> DatasetQualityResult:
    quality_issues = list(issues or [])
    if total_records == 0:
        quality_issues.append("dataset_has_no_records")
        return DatasetQualityResult(
            quality_score=0,
            quality_status="abstained",
            procedure_readiness="ABSTAINED",
            issues=quality_issues,
        )

    weighted_score = round(((usable_records * 100) + (partial_records * 50)) / total_records)
    quality_score = max(0, min(100, weighted_score))
    usable_or_partial_records = usable_records + partial_records

    if usable_or_partial_records == 0:
        status: QualityStatus = "abstained"
        readiness: ProcedureReadiness = "ABSTAINED"
    elif quality_score >= 80 and rejected_records == 0 and not quality_issues:
        status = "ready"
        readiness = "READY"
    else:
        status = "partial"
        readiness = "PARTIAL"

    return DatasetQualityResult(
        quality_score=quality_score,
        quality_status=status,
        procedure_readiness=readiness,
        issues=quality_issues,
    )


def _normalize_decimal(raw_value: Any) -> str:
    text = str(raw_value).strip()
    is_negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[,\s￥¥$€]", "", text)
    cleaned = cleaned.replace("人民币", "").replace("元", "").replace("RMB", "").replace("CNY", "")
    cleaned = cleaned.strip("()")
    try:
        value = Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError("decimal_parse_failed") from error
    if is_negative:
        value = -value
    return format(value, "f")


def _normalize_date(raw_value: Any) -> str:
    text = str(raw_value).strip()
    date_formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y.%m.%d",
        "%Y年%m月%d日",
        "%d %b %Y",
        "%d %B %Y",
    )
    for date_format in date_formats:
        try:
            return datetime.strptime(text, date_format).date().isoformat()
        except ValueError:
            continue
    raise ValueError("date_parse_failed")


def _normalize_currency(raw_value: Any) -> str:
    text = str(raw_value).strip().upper()
    currency_map = {
        "CNY": "CNY",
        "RMB": "CNY",
        "人民币": "CNY",
        "￥": "CNY",
        "¥": "CNY",
        "USD": "USD",
        "美元": "USD",
        "$": "USD",
        "HKD": "HKD",
        "港币": "HKD",
    }
    if text in currency_map:
        return currency_map[text]
    raise ValueError("currency_parse_failed")
