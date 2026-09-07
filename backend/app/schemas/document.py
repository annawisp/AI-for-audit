from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    document_id: str
    project_id: str
    original_filename: str
    content_type: str | None
    size_bytes: int
    checksum_sha256: str
    status: Literal["uploaded"]
    created_at: datetime
    trace_id: str


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    trace_id: str
