from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ValueType = Literal["amount", "date", "currency", "number", "text"]
QualityStatus = Literal["ready", "partial", "abstained"]
ProcedureReadiness = Literal["READY", "PARTIAL", "ABSTAINED"]


class NormalizedValueCreate(BaseModel):
    evidence_id: str | None = None
    document_id: str | None = None
    procedure_id: str | None = None
    field_name: str = Field(min_length=1, max_length=200)
    value_type: ValueType
    raw_value: Any
    normalization_rule: str | None = Field(default=None, max_length=200)


class NormalizedValueResponse(BaseModel):
    normalized_value_id: str
    project_id: str
    evidence_id: str | None
    document_id: str | None
    procedure_id: str | None
    field_name: str
    value_type: ValueType
    raw_value: Any
    standard_value: Any
    normalization_rule: str
    quality_status: QualityStatus
    quality_score: int
    issues: list[str]
    created_at: datetime
    trace_id: str


class NormalizedValueListResponse(BaseModel):
    items: list[NormalizedValueResponse]
    total: int


class DatasetQualityCreate(BaseModel):
    dataset_name: str = Field(min_length=1, max_length=200)
    total_records: int = Field(ge=0)
    usable_records: int = Field(ge=0)
    partial_records: int = Field(default=0, ge=0)
    rejected_records: int = Field(default=0, ge=0)
    issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_record_counts(self) -> "DatasetQualityCreate":
        measured_records = self.usable_records + self.partial_records + self.rejected_records
        if measured_records > self.total_records:
            raise ValueError("usable, partial, and rejected records cannot exceed total_records")
        return self


class DatasetQualityResponse(BaseModel):
    dataset_quality_id: str
    project_id: str
    dataset_name: str
    total_records: int
    usable_records: int
    partial_records: int
    rejected_records: int
    quality_score: int
    quality_status: QualityStatus
    procedure_readiness: ProcedureReadiness
    issues: list[str]
    created_at: datetime
    trace_id: str


class DatasetQualityListResponse(BaseModel):
    items: list[DatasetQualityResponse]
    total: int
