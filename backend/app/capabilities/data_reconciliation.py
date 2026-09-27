from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.schemas.data_reconciliation import (
    MatchedLink,
    ReconciliationCoverage,
    ReconciliationException,
    ReconciliationNode,
    ReconciliationRecord,
)

RULES_VERSION = "data_reconciliation_rule_v1"
AMOUNT_TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class DataReconciliationResult:
    status: str
    overall_exception_level: str
    coverage: ReconciliationCoverage
    nodes: list[ReconciliationNode]
    matched_links: list[MatchedLink]
    exceptions: list[ReconciliationException]
    limitations: list[str]
    source_evidence_ids: list[str]
    requires_review: bool
    conclusion: str
    confidence_level: str
    node_status: str
    judgment_status: str


def run_data_reconciliation(
    *,
    project: dict[str, Any],
    contract_evidence: dict[str, Any] | None,
    revenue_recognition_evidence: dict[str, Any] | None,
    revenue_risk_evidence: dict[str, Any] | None,
    revenue_records: list[ReconciliationRecord],
    receivable_records: list[ReconciliationRecord],
    cash_receipt_records: list[ReconciliationRecord],
    audit_period_start: str | None = None,
    audit_period_end: str | None = None,
) -> DataReconciliationResult:
    contract_fields = _field_map(contract_evidence)
    period_start = audit_period_start or project.get("audit_period_start")
    period_end = audit_period_end or project.get("audit_period_end")
    source_evidence_ids = [
        str(evidence["evidence_id"])
        for evidence in (contract_evidence, revenue_recognition_evidence, revenue_risk_evidence)
        if evidence is not None and evidence.get("evidence_id")
    ]

    nodes = [
        _contract_revenue_node(contract_fields, contract_evidence, revenue_records),
        _revenue_receivable_node(revenue_records, receivable_records),
        _revenue_cash_node(revenue_records, cash_receipt_records),
        _cutoff_node(revenue_records, period_start, period_end),
        _anomaly_node(revenue_records),
        _benford_node(revenue_records),
    ]
    matched_links = _matched_links_from_inputs(
        contract_evidence=contract_evidence,
        revenue_records=revenue_records,
        receivable_records=receivable_records,
        cash_receipt_records=cash_receipt_records,
    )
    exceptions = [exception for node in nodes for exception in node.exceptions]
    limitations = _limitations(
        nodes,
        contract_evidence,
        revenue_records,
        receivable_records,
        cash_receipt_records,
    )
    coverage = _coverage(nodes)
    status = _overall_status(
        nodes,
        source_evidence_ids,
        revenue_records,
        receivable_records,
        cash_receipt_records,
    )
    overall_exception_level = _overall_exception_level(exceptions)
    requires_review = any(exception.requires_review for exception in exceptions)
    conclusion = _conclusion(status, overall_exception_level, exceptions, coverage)

    return DataReconciliationResult(
        status=status,
        overall_exception_level=overall_exception_level,
        coverage=coverage,
        nodes=nodes,
        matched_links=matched_links,
        exceptions=exceptions,
        limitations=limitations,
        source_evidence_ids=source_evidence_ids,
        requires_review=requires_review,
        conclusion=conclusion,
        confidence_level=_confidence_level(coverage.coverage_ratio, exceptions),
        node_status="ready" if status != "INSUFFICIENT_DATA" else "blocked",
        judgment_status="PENDING_REVIEW" if requires_review else "AI_GENERATED",
    )


def build_data_reconciliation_evidence_value(result: DataReconciliationResult) -> dict[str, Any]:
    return {
        "capability": "data_reconciliation",
        "rules_version": RULES_VERSION,
        "coverage": result.coverage.model_dump(mode="json"),
        "nodes": [node.model_dump(mode="json") for node in result.nodes],
        "matched_links": [link.model_dump(mode="json") for link in result.matched_links],
        "exceptions": [exception.model_dump(mode="json") for exception in result.exceptions],
        "limitations": result.limitations,
    }


def _contract_revenue_node(
    contract_fields: dict[str, dict[str, Any]],
    contract_evidence: dict[str, Any] | None,
    revenue_records: list[ReconciliationRecord],
) -> ReconciliationNode:
    if contract_evidence is None:
        return _node(
            "contract_revenue_matching",
            "Contract to revenue matching",
            "NOT_PROVIDED",
            "not_attempted_missing_contract",
            "NONE",
            "Contract extraction evidence was not provided.",
            ["Contract to revenue matching requires contract extraction evidence."],
        )
    if not revenue_records:
        return _node(
            "contract_revenue_matching",
            "Contract to revenue matching",
            "NOT_PROVIDED",
            "not_attempted_missing_revenue_records",
            "NONE",
            "Revenue records were not provided.",
            ["Contract terms were available, but revenue records were missing."],
        )

    contract_amount = _extract_contract_amount(contract_fields)
    customer = _field_text(contract_fields, "customer_party")
    revenue_total = _sum_amounts(revenue_records)
    exceptions: list[ReconciliationException] = []

    if contract_amount is None:
        exceptions.append(
            _exception(
                "contract_amount_unavailable",
                "contract_amount_missing",
                "medium",
                "PARTIAL",
                "Contract amount cannot be compared with revenue records.",
                "The transaction_price field was missing or not numeric.",
                [],
                "Complete contract amount extraction before amount-level matching.",
                True,
                contract_evidence,
                "transaction_price",
            )
        )
    elif revenue_total is None:
        exceptions.append(
            _exception(
                "revenue_amount_unavailable",
                "revenue_amount_missing",
                "medium",
                "PARTIAL",
                "Revenue record amounts cannot be totaled.",
                "One or more revenue records contain missing or invalid amounts.",
                _record_ids(revenue_records),
                "Complete revenue amount fields before amount-level matching.",
                True,
            )
        )
    elif abs(contract_amount - revenue_total) > AMOUNT_TOLERANCE:
        exceptions.append(
            _exception(
                "contract_revenue_amount_mismatch",
                "amount_mismatch",
                "high",
                "COMPLETE",
                "Contract amount does not agree to total revenue records.",
                f"Contract amount {contract_amount} differs from revenue total {revenue_total}.",
                _record_ids(revenue_records),
                "Investigate contract coverage, revenue completeness, and allocation basis.",
                True,
                contract_evidence,
                "transaction_price",
            )
        )

    customer_matches = _customer_match_count(revenue_records, customer)
    if customer and customer_matches == 0:
        exceptions.append(
            _exception(
                "contract_revenue_customer_mismatch",
                "customer_mismatch",
                "medium",
                "COMPLETE",
                "No revenue record customer appears to match the contract customer.",
                f"Contract customer '{customer}' was not found in revenue record customer fields.",
                _record_ids(revenue_records),
                "Review whether customer names use aliases or records belong to another contract.",
                True,
                contract_evidence,
                "customer_party",
            )
        )

    link_confidence = "HIGH" if contract_amount is not None and not exceptions else "MEDIUM"
    status = "PARTIAL" if any(item.status == "PARTIAL" for item in exceptions) else "COMPLETE"
    return ReconciliationNode(
        node_id="contract_revenue_matching",
        node_name="Contract to revenue matching",
        status=status,
        link_method="contract_amount_and_customer",
        link_confidence=link_confidence,
        matched_count=len(revenue_records) - len(exceptions),
        unmatched_count=len(exceptions),
        exceptions=exceptions,
        basis="Compared contract extracted fields with provided revenue records.",
        limitations=[],
    )


def _revenue_receivable_node(
    revenue_records: list[ReconciliationRecord],
    receivable_records: list[ReconciliationRecord],
) -> ReconciliationNode:
    if not revenue_records:
        return _missing_node(
            "revenue_receivable_matching",
            "Revenue to receivable matching",
            "Revenue records were not provided.",
        )
    if not receivable_records:
        return _missing_node(
            "revenue_receivable_matching",
            "Revenue to receivable matching",
            "Receivable records were not provided.",
        )
    return _record_matching_node(
        "revenue_receivable_matching",
        "Revenue to receivable matching",
        revenue_records,
        receivable_records,
        "revenue_to_receivable",
    )


def _revenue_cash_node(
    revenue_records: list[ReconciliationRecord],
    cash_receipt_records: list[ReconciliationRecord],
) -> ReconciliationNode:
    if not revenue_records:
        return _missing_node(
            "revenue_cash_matching",
            "Revenue to cash receipt matching",
            "Revenue records were not provided.",
        )
    if not cash_receipt_records:
        return _missing_node(
            "revenue_cash_matching",
            "Revenue to cash receipt matching",
            "Cash receipt records were not provided.",
        )
    return _record_matching_node(
        "revenue_cash_matching",
        "Revenue to cash receipt matching",
        revenue_records,
        cash_receipt_records,
        "revenue_to_cash_receipt",
    )


def _record_matching_node(
    node_id: str,
    node_name: str,
    source_records: list[ReconciliationRecord],
    target_records: list[ReconciliationRecord],
    exception_prefix: str,
) -> ReconciliationNode:
    matched = 0
    exceptions: list[ReconciliationException] = []
    for source in source_records:
        target = _find_record_match(source, target_records)
        if target is not None:
            matched += 1
            continue
        exceptions.append(
            _exception(
                f"{exception_prefix}_unmatched_{_record_key(source)}",
                "unmatched_record",
                "medium",
                "UNMATCHED",
                f"No matching target record was found for {node_name}.",
                "Matching used contract reference, invoice number, customer, and amount.",
                [_record_key(source)],
                "Review unmatched records and complete missing linking keys.",
                True,
                match_status="UNMATCHED",
            )
        )
    return ReconciliationNode(
        node_id=node_id,
        node_name=node_name,
        status="UNMATCHED" if exceptions else "COMPLETE",
        link_method="reference_invoice_customer_amount",
        link_confidence="HIGH" if matched == len(source_records) else "MEDIUM",
        matched_count=matched,
        unmatched_count=len(source_records) - matched,
        exceptions=exceptions,
        basis="Matched records by reference fields first, then customer and amount.",
        limitations=[],
    )


def _cutoff_node(
    revenue_records: list[ReconciliationRecord],
    period_start: str | None,
    period_end: str | None,
) -> ReconciliationNode:
    if not revenue_records:
        return _missing_node(
            "cutoff_analysis",
            "Cutoff analysis",
            "Revenue records were not provided.",
        )
    if not period_start or not period_end:
        return _node(
            "cutoff_analysis",
            "Cutoff analysis",
            "NOT_PROVIDED",
            "not_attempted_missing_audit_period",
            "NONE",
            "Audit period start or end date was not provided.",
            ["Cutoff analysis requires an audit period."],
        )

    start = _parse_date(period_start)
    end = _parse_date(period_end)
    if start is None or end is None:
        return _node(
            "cutoff_analysis",
            "Cutoff analysis",
            "PARTIAL",
            "not_attempted_invalid_audit_period",
            "NONE",
            "Audit period dates were not parseable.",
            ["Use ISO date strings such as 2026-12-31."],
        )

    exceptions: list[ReconciliationException] = []
    partial = False
    for record in revenue_records:
        record_date = _parse_date(record.recognition_date)
        if record_date is None:
            partial = True
            exceptions.append(
                _exception(
                    f"cutoff_missing_date_{_record_key(record)}",
                    "revenue_date_missing",
                    "medium",
                    "PARTIAL",
                    "Revenue record recognition date is missing or invalid.",
                    "Cutoff testing cannot evaluate this record without recognition_date.",
                    [_record_key(record)],
                    "Complete recognition_date for cutoff testing.",
                    True,
                    match_status="INSUFFICIENT_DATA",
                )
            )
            continue
        if record_date < start or record_date > end:
            exceptions.append(
                _exception(
                    f"cutoff_outside_period_{_record_key(record)}",
                    "revenue_date_outside_audit_period",
                    "high",
                    "COMPLETE",
                    "Revenue record date is outside the audit period.",
                    f"Recognition date {record_date.isoformat()} is outside {start} to {end}.",
                    [_record_key(record)],
                    "Review cutoff, period classification, and supporting evidence.",
                    True,
                )
            )
    return ReconciliationNode(
        node_id="cutoff_analysis",
        node_name="Cutoff analysis",
        status="PARTIAL" if partial else "COMPLETE",
        link_method="recognition_date_vs_audit_period",
        link_confidence="HIGH",
        matched_count=len(revenue_records) - len(exceptions),
        unmatched_count=len(exceptions),
        exceptions=exceptions,
        basis="Compared revenue recognition dates with the audit period.",
        limitations=[],
    )


def _anomaly_node(revenue_records: list[ReconciliationRecord]) -> ReconciliationNode:
    if not revenue_records:
        return _missing_node(
            "anomaly_detection",
            "Revenue anomaly detection",
            "Revenue records were not provided.",
        )
    exceptions: list[ReconciliationException] = []
    seen_keys: set[tuple[str, str, str]] = set()
    amounts = [_to_decimal(record.amount) for record in revenue_records]
    valid_amounts = [amount for amount in amounts if amount is not None]
    mean_amount = _mean(valid_amounts)
    stddev_amount = _stddev(valid_amounts, mean_amount)

    for record, amount in zip(revenue_records, amounts, strict=True):
        if amount is None:
            exceptions.append(
                _exception(
                    f"amount_missing_{_record_key(record)}",
                    "amount_missing",
                    "medium",
                    "PARTIAL",
                    "Revenue record amount is missing or invalid.",
                    "Anomaly detection cannot evaluate the amount for this record.",
                    [_record_key(record)],
                    "Complete amount fields before anomaly analysis.",
                    True,
                )
            )
        elif amount < 0:
            exceptions.append(
                _exception(
                    f"negative_amount_{_record_key(record)}",
                    "negative_revenue_amount",
                    "high",
                    "COMPLETE",
                    "Revenue record has a negative amount.",
                    f"Amount is {amount}.",
                    [_record_key(record)],
                    "Review whether this is a credit note, reversal, or posting error.",
                    True,
                )
            )
        elif _is_outlier(amount, mean_amount, stddev_amount):
            exceptions.append(
                _exception(
                    f"large_amount_outlier_{_record_key(record)}",
                    "large_amount_outlier",
                    "medium",
                    "COMPLETE",
                    "Revenue record amount is unusually large compared with the population.",
                    f"Amount {amount} is more than three standard deviations from mean.",
                    [_record_key(record)],
                    "Review high-value revenue transaction support.",
                    True,
                )
            )

        duplicate_key = (
            record.contract_reference or "",
            record.invoice_number or "",
            str(record.amount or ""),
        )
        if duplicate_key in seen_keys and any(duplicate_key):
            exceptions.append(
                _exception(
                    f"duplicate_revenue_{_record_key(record)}",
                    "duplicate_revenue_record",
                    "medium",
                    "COMPLETE",
                    "Possible duplicate revenue record identified.",
                    "Contract reference, invoice number, and amount duplicate another record.",
                    [_record_key(record)],
                    "Review duplicate posting or repeated input.",
                    True,
                )
            )
        seen_keys.add(duplicate_key)

    return ReconciliationNode(
        node_id="anomaly_detection",
        node_name="Revenue anomaly detection",
        status="PARTIAL" if any(item.status == "PARTIAL" for item in exceptions) else "COMPLETE",
        link_method="rule_based_population_scan",
        link_confidence="MEDIUM",
        matched_count=len(revenue_records) - len(exceptions),
        unmatched_count=len(exceptions),
        exceptions=exceptions,
        basis="Screened revenue records for missing, negative, outlier, and duplicate amounts.",
        limitations=[],
    )


def _benford_node(revenue_records: list[ReconciliationRecord]) -> ReconciliationNode:
    if not revenue_records:
        return _missing_node(
            "benford_signal",
            "Benford risk signal",
            "Revenue records were not provided.",
        )
    first_digits = [_first_digit(record.amount) for record in revenue_records]
    first_digits = [digit for digit in first_digits if digit is not None]
    if len(first_digits) < 30:
        return _node(
            "benford_signal",
            "Benford risk signal",
            "NOT_APPLICABLE",
            "not_attempted_population_too_small",
            "NONE",
            "Benford analysis is not meaningful for fewer than 30 usable positive amounts.",
            ["Benford is retained only as a risk signal and not an audit conclusion."],
        )
    high_first_digit_ratio = first_digits.count(9) / len(first_digits)
    exceptions: list[ReconciliationException] = []
    if high_first_digit_ratio > 0.20:
        exceptions.append(
            _exception(
                "benford_high_9_frequency",
                "benford_distribution_signal",
                "low",
                "COMPLETE",
                "Benford first-digit distribution shows an unusual frequency of digit 9.",
                f"Digit 9 frequency is {high_first_digit_ratio:.2%}.",
                [],
                "Use only as a risk signal; perform substantive follow-up before conclusion.",
                True,
            )
        )
    return ReconciliationNode(
        node_id="benford_signal",
        node_name="Benford risk signal",
        status="COMPLETE",
        link_method="benford_first_digit_screening",
        link_confidence="LOW",
        matched_count=len(first_digits),
        unmatched_count=0,
        exceptions=exceptions,
        basis="Applied a lightweight first-digit screen as a risk signal only.",
        limitations=["Benford result is not an audit conclusion and requires contextual review."],
    )


def _field_map(evidence: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if evidence is None:
        return {}
    extracted_value = evidence.get("extracted_value", {})
    fields = extracted_value.get("fields", []) if isinstance(extracted_value, dict) else []
    return {
        str(field.get("field_name")): field
        for field in fields
        if isinstance(field, dict) and field.get("field_name")
    }


def _field_text(fields: dict[str, dict[str, Any]], field_name: str) -> str:
    field = fields.get(field_name, {})
    value = field.get("value")
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item.get("value", item)) for item in value)
    return str(value)


def _extract_contract_amount(fields: dict[str, dict[str, Any]]) -> Decimal | None:
    text = _field_text(fields, "transaction_price")
    match = re.search(r"[-+]?\d[\d,]*(?:\.\d+)?", text)
    if match is None:
        return None
    return _to_decimal(match.group(0).replace(",", ""))


def _sum_amounts(records: list[ReconciliationRecord]) -> Decimal | None:
    total = Decimal("0")
    for record in records:
        amount = _to_decimal(record.amount)
        if amount is None:
            return None
        total += amount
    return total


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _find_record_match(
    source: ReconciliationRecord,
    targets: list[ReconciliationRecord],
) -> ReconciliationRecord | None:
    for target in targets:
        if source.invoice_number and source.invoice_number == target.invoice_number:
            return target
        if source.contract_reference and source.contract_reference == target.contract_reference:
            source_amount = _to_decimal(source.amount)
            target_amount = _to_decimal(target.amount)
            if source_amount is not None and target_amount is not None:
                if abs(source_amount - target_amount) <= AMOUNT_TOLERANCE:
                    return target
    for target in targets:
        if _normalize_text(source.customer_name) != _normalize_text(target.customer_name):
            continue
        source_amount = _to_decimal(source.amount)
        target_amount = _to_decimal(target.amount)
        if source_amount is not None and target_amount is not None:
            if abs(source_amount - target_amount) <= AMOUNT_TOLERANCE:
                return target
    return None


def _link_method(
    source: ReconciliationRecord,
    target: ReconciliationRecord,
    fallback: str,
) -> str:
    if source.invoice_number and source.invoice_number == target.invoice_number:
        return "invoice_number_exact"
    if source.contract_reference and source.contract_reference == target.contract_reference:
        return "contract_reference_amount"
    if _normalize_text(source.customer_name) == _normalize_text(target.customer_name):
        return "customer_amount"
    return fallback


def _link_confidence(
    source: ReconciliationRecord,
    target: ReconciliationRecord,
) -> str:
    if source.invoice_number and source.invoice_number == target.invoice_number:
        return "HIGH"
    if source.contract_reference and source.contract_reference == target.contract_reference:
        return "HIGH"
    if _normalize_text(source.customer_name) == _normalize_text(target.customer_name):
        return "MEDIUM"
    return "LOW"


def _amount_difference(
    source: ReconciliationRecord,
    target: ReconciliationRecord,
) -> float | None:
    source_amount = _to_decimal(source.amount)
    target_amount = _to_decimal(target.amount)
    if source_amount is None or target_amount is None:
        return None
    return float(target_amount - source_amount)


def _date_difference_days(
    source: ReconciliationRecord,
    target: ReconciliationRecord,
) -> int | None:
    source_date = _parse_date(source.recognition_date)
    target_date = _parse_date(target.receipt_date or target.due_date or target.recognition_date)
    if source_date is None or target_date is None:
        return None
    return (target_date - source_date).days


def _customer_match_count(records: list[ReconciliationRecord], customer: str) -> int:
    if not customer:
        return 0
    normalized_customer = _normalize_text(customer)
    return sum(
        1
        for record in records
        if normalized_customer and normalized_customer in _normalize_text(record.customer_name)
    )


def _normalize_text(value: str | None) -> str:
    return "".join(str(value or "").lower().split())


def _record_key(record: ReconciliationRecord) -> str:
    return (
        record.record_id
        or record.invoice_number
        or record.contract_reference
        or record.customer_name
        or "unknown_record"
    )


def _record_ids(records: list[ReconciliationRecord]) -> list[str]:
    return [_record_key(record) for record in records]


def _mean(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _stddev(values: list[Decimal], mean_value: Decimal | None) -> Decimal | None:
    if mean_value is None or len(values) < 2:
        return None
    variance = sum((value - mean_value) ** 2 for value in values) / Decimal(len(values))
    return Decimal(str(math.sqrt(float(variance))))


def _is_outlier(
    value: Decimal,
    mean_value: Decimal | None,
    stddev_value: Decimal | None,
) -> bool:
    if mean_value is None or stddev_value is None or stddev_value == 0:
        return False
    return abs(value - mean_value) > (stddev_value * Decimal("3"))


def _first_digit(value: Any) -> int | None:
    amount = _to_decimal(value)
    if amount is None or amount <= 0:
        return None
    digits = re.sub(r"\D", "", str(amount.normalize()))
    return int(digits[0]) if digits else None


def _missing_node(node_id: str, node_name: str, reason: str) -> ReconciliationNode:
    return _node(
        node_id,
        node_name,
        "NOT_PROVIDED",
        "not_attempted_missing_data",
        "NONE",
        reason,
        [reason],
    )


def _node(
    node_id: str,
    node_name: str,
    status: str,
    link_method: str,
    link_confidence: str,
    basis: str,
    limitations: list[str],
) -> ReconciliationNode:
    return ReconciliationNode(
        node_id=node_id,
        node_name=node_name,
        status=status,
        link_method=link_method,
        link_confidence=link_confidence,
        basis=basis,
        limitations=limitations,
    )


def _exception(
    exception_id: str,
    exception_type: str,
    severity: str,
    status: str,
    description: str,
    basis: str,
    record_ids: list[str],
    recommendation: str,
    requires_review: bool,
    evidence: dict[str, Any] | None = None,
    field_name: str | None = None,
    match_status: str | None = None,
) -> ReconciliationException:
    references = []
    if evidence is not None and evidence.get("evidence_id"):
        references.append(
            {
                "evidence_id": str(evidence["evidence_id"]),
                "source": str(evidence.get("source", "")),
                "field_name": field_name,
            }
        )
    return ReconciliationException(
        exception_id=exception_id,
        exception_type=exception_type,
        severity=severity,
        status=status,
        description=description,
        basis=basis,
        record_ids=record_ids,
        evidence_references=references,
        recommendation=recommendation,
        recommended_follow_up=recommendation,
        is_audit_conclusion=False,
        match_status=match_status,
        requires_review=requires_review,
    )


def _matched_links_from_inputs(
    *,
    contract_evidence: dict[str, Any] | None,
    revenue_records: list[ReconciliationRecord],
    receivable_records: list[ReconciliationRecord],
    cash_receipt_records: list[ReconciliationRecord],
) -> list[MatchedLink]:
    links: list[MatchedLink] = []
    if contract_evidence is not None:
        for revenue in revenue_records:
            links.append(
                MatchedLink(
                    source_record_id=str(contract_evidence.get("evidence_id")),
                    target_record_id=_record_key(revenue),
                    source_type="contract_evidence",
                    target_type="revenue_record",
                    match_status="MATCHED",
                    link_method="contract_evidence_to_revenue_population",
                    link_confidence="MEDIUM",
                    basis="Revenue record was included in contract-to-revenue matching.",
                )
            )
    links.extend(
        _record_level_links(
            source_records=revenue_records,
            target_records=receivable_records,
            source_type="revenue_record",
            target_type="receivable_record",
            link_method="revenue_to_receivable",
        )
    )
    links.extend(
        _record_level_links(
            source_records=revenue_records,
            target_records=cash_receipt_records,
            source_type="revenue_record",
            target_type="cash_receipt_record",
            link_method="revenue_to_cash_receipt",
        )
    )
    return links


def _record_level_links(
    *,
    source_records: list[ReconciliationRecord],
    target_records: list[ReconciliationRecord],
    source_type: str,
    target_type: str,
    link_method: str,
) -> list[MatchedLink]:
    if not source_records or not target_records:
        return []
    links: list[MatchedLink] = []
    for source in source_records:
        target = _find_record_match(source, target_records)
        if target is None:
            links.append(
                MatchedLink(
                    source_record_id=_record_key(source),
                    target_record_id=None,
                    source_type=source_type,
                    target_type=target_type,
                    match_status="UNMATCHED",
                    link_method=link_method,
                    link_confidence="NONE",
                    basis="No target record matched by reference, invoice, customer, or amount.",
                )
            )
            continue
        links.append(
            MatchedLink(
                source_record_id=_record_key(source),
                target_record_id=_record_key(target),
                source_type=source_type,
                target_type=target_type,
                match_status="MATCHED",
                link_method=_link_method(source, target, link_method),
                link_confidence=_link_confidence(source, target),
                amount_difference=_amount_difference(source, target),
                date_difference_days=_date_difference_days(source, target),
                basis="Matched record using available reference fields and amount comparison.",
            )
        )
    return links


def _coverage(nodes: list[ReconciliationNode]) -> ReconciliationCoverage:
    not_applicable = [node for node in nodes if node.status == "NOT_APPLICABLE"]
    not_provided = [node for node in nodes if node.status == "NOT_PROVIDED"]
    insufficient = [node for node in nodes if node.status == "INSUFFICIENT_DATA"]
    assessable = [
        node
        for node in nodes
        if node.status not in {"INSUFFICIENT_DATA", "NOT_APPLICABLE", "NOT_PROVIDED"}
    ]
    denominator = len(nodes) - len(not_applicable) - len(not_provided)
    ratio = len(assessable) / denominator if denominator else 0
    return ReconciliationCoverage(
        total_nodes=len(nodes),
        assessable_nodes=len(assessable),
        insufficient_data_nodes=len(insufficient),
        not_provided_nodes=len(not_provided),
        not_applicable_nodes=len(not_applicable),
        coverage_ratio=round(ratio, 4),
        excluded_node_ids=[
            node.node_id for node in insufficient + not_applicable + not_provided
        ],
    )


def _overall_status(
    nodes: list[ReconciliationNode],
    source_evidence_ids: list[str],
    revenue_records: list[ReconciliationRecord],
    receivable_records: list[ReconciliationRecord],
    cash_receipt_records: list[ReconciliationRecord],
) -> str:
    if (
        not source_evidence_ids
        and not revenue_records
        and not receivable_records
        and not cash_receipt_records
    ):
        return "INSUFFICIENT_DATA"
    if any(
        node.status in {"PARTIAL", "INSUFFICIENT_DATA", "NOT_PROVIDED", "UNMATCHED"}
        for node in nodes
    ):
        return "PARTIAL"
    return "COMPLETE"


def _overall_exception_level(exceptions: list[ReconciliationException]) -> str:
    if any(exception.severity == "high" for exception in exceptions):
        return "high"
    if any(exception.severity == "medium" for exception in exceptions):
        return "medium"
    return "low"


def _limitations(
    nodes: list[ReconciliationNode],
    contract_evidence: dict[str, Any] | None,
    revenue_records: list[ReconciliationRecord],
    receivable_records: list[ReconciliationRecord],
    cash_receipt_records: list[ReconciliationRecord],
) -> list[str]:
    limitations = [item for node in nodes for item in node.limitations]
    if contract_evidence is None:
        limitations.append(
            "Contract-level matching was limited because contract evidence was not provided."
        )
    if not revenue_records:
        limitations.append(
            "Revenue record testing was not performed because revenue records were missing."
        )
    if not receivable_records:
        limitations.append(
            "Receivable matching was not performed because receivable records were missing."
        )
    if not cash_receipt_records:
        limitations.append(
            "Cash receipt matching was not performed because cash receipt records were missing."
        )
    return list(dict.fromkeys(limitations))


def _conclusion(
    status: str,
    overall_exception_level: str,
    exceptions: list[ReconciliationException],
    coverage: ReconciliationCoverage,
) -> str:
    if status == "INSUFFICIENT_DATA":
        return (
            "Data reconciliation could not be performed because no usable input data "
            "was provided."
        )
    if exceptions:
        return (
            f"Data reconciliation identified {len(exceptions)} exception(s); "
            f"overall exception level is {overall_exception_level}; "
            f"coverage ratio is {coverage.coverage_ratio:.2%}."
        )
    return (
        "Data reconciliation completed with no rule-based exceptions at "
        f"{coverage.coverage_ratio:.2%} coverage."
    )


def _confidence_level(
    coverage_ratio: float,
    exceptions: list[ReconciliationException],
) -> str:
    if coverage_ratio >= 0.8 and not exceptions:
        return "high"
    if coverage_ratio >= 0.5:
        return "medium"
    return "low"
