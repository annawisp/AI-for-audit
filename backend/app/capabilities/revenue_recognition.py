from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.schemas.revenue_recognition import (
    RevenueAnalysisNode,
    RevenueCoverage,
    RevenueRecord,
)

ANALYZER_VERSION = "revenue_recognition_rule_v1"


@dataclass(frozen=True)
class RevenueRecognitionResult:
    status: str
    coverage: RevenueCoverage
    nodes: list[RevenueAnalysisNode]
    limitations: list[str]
    impact: str
    conclusion: str
    confidence_level: str
    node_status: str
    judgment_status: str
    failure_reason: str | None = None


def analyze_revenue_recognition(
    *,
    contract_evidence: dict[str, Any],
    project: dict[str, Any],
    revenue_records: list[RevenueRecord],
) -> RevenueRecognitionResult:
    fields = _field_map(contract_evidence)
    if not fields:
        return _blocked("contract_evidence_has_no_extractable_fields")

    nodes = [
        _performance_obligation_node(fields),
        _timing_node(fields),
        _acceptance_node(fields),
        _payment_node(fields),
        _variable_consideration_node(fields),
        _revenue_record_node(revenue_records),
    ]
    limitations = _limitations(fields, project, revenue_records, nodes)
    status, node_status, judgment_status, confidence_level = _overall_status(nodes)
    conclusion = _overall_conclusion(nodes)
    impact = _impact(status, revenue_records)
    coverage = RevenueCoverage(
        contract_level_analysis=any(node.status != "BLOCKED" for node in nodes[:5]),
        revenue_record_analysis=bool(revenue_records),
        project_context_available=bool(
            project.get("audit_period_start") or project.get("audit_period_end")
        ),
        analyzed_nodes=[node.node_name for node in nodes if node.status != "ABSTAINED"],
        skipped_nodes=[node.node_name for node in nodes if node.status == "ABSTAINED"],
    )
    return RevenueRecognitionResult(
        status=status,
        coverage=coverage,
        nodes=nodes,
        limitations=limitations,
        impact=impact,
        conclusion=conclusion,
        confidence_level=confidence_level,
        node_status=node_status,
        judgment_status=judgment_status,
    )


def build_revenue_recognition_evidence_value(
    *,
    contract_evidence_id: str,
    coverage: RevenueCoverage,
    nodes: list[RevenueAnalysisNode],
    limitations: list[str],
    impact: str,
    analyzer_type: str,
) -> dict[str, Any]:
    return {
        "capability": "revenue_recognition_analysis",
        "contract_evidence_id": contract_evidence_id,
        "analyzer_type": analyzer_type,
        "analyzer_version": ANALYZER_VERSION,
        "coverage": coverage.model_dump(),
        "nodes": [node.model_dump() for node in nodes],
        "limitations": limitations,
        "impact": impact,
    }


def _blocked(reason: str) -> RevenueRecognitionResult:
    return RevenueRecognitionResult(
        status="BLOCKED",
        coverage=RevenueCoverage(
            contract_level_analysis=False,
            revenue_record_analysis=False,
            project_context_available=False,
            analyzed_nodes=[],
            skipped_nodes=[
                "performance_obligation_assessment",
                "revenue_timing_assessment",
                "acceptance_dependency_assessment",
                "payment_vs_recognition_assessment",
                "variable_consideration_assessment",
                "revenue_record_reconciliation",
            ],
        ),
        nodes=[],
        limitations=["Contract extraction evidence is missing or not readable."],
        impact="Revenue recognition analysis cannot proceed until contract fields are available.",
        conclusion="Revenue recognition analysis was blocked by missing contract evidence.",
        confidence_level="low",
        node_status="blocked",
        judgment_status="NEED_MORE_EVIDENCE",
        failure_reason=reason,
    )


def _field_map(contract_evidence: dict[str, Any]) -> dict[str, dict[str, Any]]:
    extracted_value = contract_evidence.get("extracted_value", {})
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


def _field_status(fields: dict[str, dict[str, Any]], field_name: str) -> str:
    return str(fields.get(field_name, {}).get("status", "MISSING_IN_DOCUMENT"))


def _performance_obligation_node(fields: dict[str, dict[str, Any]]) -> RevenueAnalysisNode:
    status = _field_status(fields, "performance_obligations")
    text = _field_text(fields, "performance_obligations")
    goods_text = _field_text(fields, "goods_or_services")
    obligations_count = _list_value_count(fields.get("performance_obligations", {}))
    if status != "EXTRACTED":
        return RevenueAnalysisNode(
            node_name="performance_obligation_assessment",
            status="PARTIAL",
            trigger="Contract extraction did not provide clear performance obligation terms.",
            analysis=(
                "The system cannot determine the promised goods or services from "
                "available fields."
            ),
            conclusion="Performance obligation assessment requires more contract evidence.",
            requires_review=True,
            review_reason="performance_obligation_missing",
            confidence_level="low",
            supporting_fields=["performance_obligations", "goods_or_services"],
        )
    if obligations_count > 1:
        return RevenueAnalysisNode(
            node_name="performance_obligation_assessment",
            status="REQUIRES_REVIEW",
            trigger="Multiple performance obligation clauses were extracted.",
            analysis=(
                "Multiple obligations may require transaction price allocation. "
                "The rule engine does not infer allocation without standalone selling prices."
            ),
            conclusion="Multiple performance obligations require manual review before conclusion.",
            requires_review=True,
            review_reason="multiple_obligations_without_allocation_basis",
            confidence_level="medium",
            supporting_fields=["performance_obligations", "transaction_price"],
        )
    return RevenueAnalysisNode(
        node_name="performance_obligation_assessment",
        status="COMPLETED",
        trigger="Performance obligation terms were extracted.",
        analysis=f"Extracted obligation: {text or goods_text}.",
        conclusion="Contract appears to contain a single identifiable performance obligation.",
        confidence_level="medium",
        supporting_fields=["performance_obligations", "goods_or_services"],
    )


def _timing_node(fields: dict[str, dict[str, Any]]) -> RevenueAnalysisNode:
    obligation_text = _field_text(fields, "performance_obligations")
    services_text = _field_text(fields, "goods_or_services")
    period_text = _field_text(fields, "contract_period")
    combined_text = f"{obligation_text} {services_text} {period_text}"
    if _contains_any(combined_text, ("按月", "期间", "年度", "持续", "订阅", "服务期限")):
        conclusion = "Revenue recognition appears more likely to be over time."
        analysis = "The contract includes continuous service or period-based language."
    elif _contains_any(combined_text, ("交付", "验收", "上线", "一次性")):
        conclusion = "Revenue recognition appears more likely to be at a point in time."
        analysis = "The contract includes delivery, launch, or acceptance language."
    else:
        return RevenueAnalysisNode(
            node_name="revenue_timing_assessment",
            status="PARTIAL",
            trigger="Timing analysis was triggered by available contract fields.",
            analysis=(
                "Available terms do not clearly indicate over-time or point-in-time "
                "recognition."
            ),
            conclusion="Revenue timing needs manual review or additional contract context.",
            requires_review=True,
            review_reason="timing_basis_unclear",
            confidence_level="low",
            supporting_fields=["performance_obligations", "goods_or_services", "contract_period"],
        )
    return RevenueAnalysisNode(
        node_name="revenue_timing_assessment",
        status="COMPLETED",
        trigger="Timing analysis was triggered by contract obligation and period terms.",
        analysis=analysis,
        conclusion=conclusion,
        confidence_level="medium",
        supporting_fields=["performance_obligations", "goods_or_services", "contract_period"],
    )


def _acceptance_node(fields: dict[str, dict[str, Any]]) -> RevenueAnalysisNode:
    acceptance_text = _field_text(fields, "acceptance_terms")
    acceptance_status = _field_status(fields, "acceptance_terms")
    if acceptance_status == "NOT_APPLICABLE":
        return RevenueAnalysisNode(
            node_name="acceptance_dependency_assessment",
            status="COMPLETED",
            trigger="Contract explicitly indicates acceptance is not applicable.",
            analysis="No acceptance dependency was identified from the extracted contract field.",
            conclusion=(
                "Revenue recognition does not appear acceptance-dependent based on "
                "this field."
            ),
            confidence_level="medium",
            supporting_fields=["acceptance_terms"],
        )
    if acceptance_status != "EXTRACTED":
        return RevenueAnalysisNode(
            node_name="acceptance_dependency_assessment",
            status="PARTIAL",
            trigger="Acceptance dependency assessment is required for revenue timing.",
            analysis="Acceptance or delivery condition was not extracted from the contract.",
            conclusion="Cannot rule out acceptance dependency without additional evidence.",
            requires_review=True,
            review_reason="acceptance_terms_missing",
            confidence_level="low",
            supporting_fields=["acceptance_terms"],
        )
    return RevenueAnalysisNode(
        node_name="acceptance_dependency_assessment",
        status="REQUIRES_REVIEW",
        trigger="Acceptance or delivery condition was extracted.",
        analysis=f"Extracted acceptance terms: {acceptance_text}.",
        conclusion="Revenue recognition may depend on customer acceptance or delivery evidence.",
        requires_review=True,
        review_reason="acceptance_or_delivery_evidence_needed",
        confidence_level="medium",
        supporting_fields=["acceptance_terms"],
    )


def _payment_node(fields: dict[str, dict[str, Any]]) -> RevenueAnalysisNode:
    payment_text = _field_text(fields, "payment_terms")
    if _field_status(fields, "payment_terms") != "EXTRACTED":
        return RevenueAnalysisNode(
            node_name="payment_vs_recognition_assessment",
            status="PARTIAL",
            trigger="Payment terms are needed to compare billing and revenue recognition basis.",
            analysis="Payment terms were not extracted from available contract fields.",
            conclusion="Payment versus recognition analysis requires more evidence.",
            requires_review=True,
            review_reason="payment_terms_missing",
            confidence_level="low",
            supporting_fields=["payment_terms"],
        )
    return RevenueAnalysisNode(
        node_name="payment_vs_recognition_assessment",
        status="COMPLETED",
        trigger="Payment terms were extracted.",
        analysis=f"Extracted payment terms: {payment_text}.",
        conclusion="Payment milestones should not be used alone as revenue recognition evidence.",
        confidence_level="medium",
        supporting_fields=["payment_terms"],
    )


def _variable_consideration_node(fields: dict[str, dict[str, Any]]) -> RevenueAnalysisNode:
    special_status = _field_status(fields, "special_terms")
    special_text = _field_text(fields, "special_terms")
    if special_status == "NOT_APPLICABLE":
        return RevenueAnalysisNode(
            node_name="variable_consideration_assessment",
            status="COMPLETED",
            trigger="Special terms were explicitly marked not applicable.",
            analysis="No refund, return, warranty, or variable consideration clause was extracted.",
            conclusion=(
                "No variable consideration constraint was identified from the "
                "contract field."
            ),
            confidence_level="medium",
            supporting_fields=["special_terms"],
        )
    if special_status != "EXTRACTED":
        return RevenueAnalysisNode(
            node_name="variable_consideration_assessment",
            status="ABSTAINED",
            trigger="Special terms were not extracted.",
            analysis="The system abstains from variable consideration assessment without terms.",
            conclusion="No conclusion on variable consideration can be made from current evidence.",
            confidence_level="low",
            supporting_fields=["special_terms"],
        )
    if _contains_any(special_text, ("退款", "退货", "质保", "违约", "可变对价", "折扣", "返利")):
        return RevenueAnalysisNode(
            node_name="variable_consideration_assessment",
            status="REQUIRES_REVIEW",
            trigger="Potential variable consideration or constraint terms were extracted.",
            analysis=f"Extracted special terms: {special_text}.",
            conclusion=(
                "Potential variable consideration or constraint terms require "
                "manual review."
            ),
            requires_review=True,
            review_reason="variable_consideration_or_constraint_terms_found",
            confidence_level="medium",
            supporting_fields=["special_terms"],
        )
    return RevenueAnalysisNode(
        node_name="variable_consideration_assessment",
        status="COMPLETED",
        trigger="Special terms were extracted.",
        analysis=f"Extracted special terms: {special_text}.",
        conclusion="No obvious variable consideration keyword was identified by rules.",
        confidence_level="medium",
        supporting_fields=["special_terms"],
    )


def _revenue_record_node(revenue_records: list[RevenueRecord]) -> RevenueAnalysisNode:
    if not revenue_records:
        return RevenueAnalysisNode(
            node_name="revenue_record_reconciliation",
            status="ABSTAINED",
            trigger="Revenue records were not provided.",
            analysis="TASK-303 does not require revenue records for contract-level analysis.",
            conclusion=(
                "Record-level reconciliation was skipped without blocking contract "
                "analysis."
            ),
            confidence_level="medium",
            supporting_fields=[],
        )
    incomplete_count = sum(
        1 for record in revenue_records if not record.recognition_date or record.amount is None
    )
    if incomplete_count:
        return RevenueAnalysisNode(
            node_name="revenue_record_reconciliation",
            status="PARTIAL",
            trigger="Revenue records were provided.",
            analysis=f"{incomplete_count} revenue record(s) lack amount or recognition date.",
            conclusion="Record-level reconciliation is partial and requires data completion.",
            requires_review=True,
            review_reason="revenue_records_incomplete",
            confidence_level="low",
            supporting_fields=["revenue_records"],
        )
    return RevenueAnalysisNode(
        node_name="revenue_record_reconciliation",
        status="COMPLETED",
        trigger="Revenue records were provided.",
        analysis=f"{len(revenue_records)} revenue record(s) include amount and recognition date.",
        conclusion="Revenue records are available for follow-up amount and cutoff testing.",
        confidence_level="medium",
        supporting_fields=["revenue_records"],
    )


def _limitations(
    fields: dict[str, dict[str, Any]],
    project: dict[str, Any],
    revenue_records: list[RevenueRecord],
    nodes: list[RevenueAnalysisNode],
) -> list[str]:
    limitations: list[str] = []
    missing_fields = [
        field_name
        for field_name in (
            "performance_obligations",
            "transaction_price",
            "payment_terms",
            "acceptance_terms",
        )
        if _field_status(fields, field_name) not in {"EXTRACTED", "NOT_APPLICABLE"}
    ]
    if missing_fields:
        limitations.append(f"Missing or unclear contract fields: {', '.join(missing_fields)}.")
    if not revenue_records:
        limitations.append("Revenue detail records were not provided.")
    if not project.get("audit_period_start") and not project.get("audit_period_end"):
        limitations.append("Audit period context was not provided in Project Context.")
    if any(node.requires_review for node in nodes):
        limitations.append("One or more analysis nodes require manual review.")
    return limitations


def _overall_status(nodes: list[RevenueAnalysisNode]) -> tuple[str, str, str, str]:
    contract_nodes = [node for node in nodes if node.node_name != "revenue_record_reconciliation"]
    if any(node.status == "REQUIRES_REVIEW" for node in contract_nodes):
        return "REQUIRES_REVIEW", "partial", "PENDING_REVIEW", "medium"
    if any(node.status == "PARTIAL" for node in contract_nodes):
        return "PARTIAL", "partial", "PENDING_REVIEW", "low"
    if all(node.status in {"COMPLETED", "ABSTAINED"} for node in contract_nodes):
        return "COMPLETED", "ready", "AI_GENERATED", "medium"
    return "PARTIAL", "partial", "PENDING_REVIEW", "low"


def _overall_conclusion(nodes: list[RevenueAnalysisNode]) -> str:
    timing = _find_node(nodes, "revenue_timing_assessment")
    acceptance = _find_node(nodes, "acceptance_dependency_assessment")
    review_nodes = [node.node_name for node in nodes if node.requires_review]
    if review_nodes:
        return (
            "Contract-level revenue recognition analysis identified matters requiring "
            f"manual review: {', '.join(review_nodes)}."
        )
    if timing and acceptance:
        return f"{timing.conclusion} {acceptance.conclusion}"
    return "Contract-level revenue recognition analysis completed based on available fields."


def _impact(status: str, revenue_records: list[RevenueRecord]) -> str:
    if status == "BLOCKED":
        return "No audit conclusion can be supported until contract evidence is available."
    if not revenue_records:
        return (
            "Contract-level conclusion can support planning and review, but cannot complete "
            "amount-level reconciliation or cutoff testing without revenue records."
        )
    return (
        "Contract-level conclusion can support follow-up revenue testing. Record-level "
        "results should be reconciled to ledgers and supporting documents in later tasks."
    )


def _list_value_count(field: dict[str, Any]) -> int:
    value = field.get("value")
    return len(value) if isinstance(value, list) else (1 if value else 0)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _find_node(nodes: list[RevenueAnalysisNode], node_name: str) -> RevenueAnalysisNode | None:
    return next((node for node in nodes if node.node_name == node_name), None)
