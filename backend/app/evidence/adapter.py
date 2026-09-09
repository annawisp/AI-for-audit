from dataclasses import dataclass
from typing import Any

from app.schemas.evidence import EvidenceCreate


@dataclass(frozen=True)
class ContractExtractionResult:
    document_id: str | None
    field_name: str
    extracted_value: Any
    source_location: str
    confidence: float | None = None
    confidence_basis: str | None = None


@dataclass(frozen=True)
class RuleEvaluationResult:
    procedure_id: str | None
    rule_id: str
    observed_value: Any
    conclusion: str
    confidence_basis: str


@dataclass(frozen=True)
class AiJudgmentResult:
    procedure_id: str | None
    prompt_name: str
    extracted_value: Any
    conclusion: str
    model_confidence: float | None
    confidence_basis: str


def contract_extraction_to_evidence(result: ContractExtractionResult) -> EvidenceCreate:
    return EvidenceCreate(
        document_id=result.document_id,
        source=f"contract_extraction:{result.source_location}:{result.field_name}",
        extracted_value={
            "field_name": result.field_name,
            "value": result.extracted_value,
            "source_location": result.source_location,
        },
        execution_status="completed",
        node_status="ready",
        judgment_status="AI_GENERATED",
        confidence=result.confidence,
        confidence_level=_confidence_level(result.confidence),
        confidence_basis=result.confidence_basis or "Contract extraction result.",
    )


def rule_result_to_evidence(result: RuleEvaluationResult) -> EvidenceCreate:
    return EvidenceCreate(
        procedure_id=result.procedure_id,
        source=f"rule:{result.rule_id}",
        extracted_value={
            "rule_id": result.rule_id,
            "observed_value": result.observed_value,
        },
        conclusion=result.conclusion,
        execution_status="completed",
        node_status="ready",
        judgment_status="PENDING_REVIEW",
        confidence_level="medium",
        confidence_basis=result.confidence_basis,
    )


def ai_judgment_to_evidence(result: AiJudgmentResult) -> EvidenceCreate:
    return EvidenceCreate(
        procedure_id=result.procedure_id,
        source=f"ai_judgment:{result.prompt_name}",
        extracted_value=result.extracted_value,
        conclusion=result.conclusion,
        execution_status="completed",
        node_status="ready",
        judgment_status="AI_GENERATED",
        model_confidence=result.model_confidence,
        confidence_level=_confidence_level(result.model_confidence),
        confidence_basis=result.confidence_basis,
    )


def _confidence_level(confidence: float | None) -> str | None:
    if confidence is None:
        return None
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return "low"
