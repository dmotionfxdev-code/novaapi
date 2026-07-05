"""Pydantic request/response models — independent of the SQLAlchemy models
and the domain entities (Architecture Redesign §9). Same pattern as
Identity, Sprint 1.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.shared_kernel.types import CursorPage


class CreateAssessmentRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    hazard_type: str


class CancelAssessmentRequest(BaseModel):
    reason: str = Field(min_length=1)


class AssessmentResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    hazard_type: str
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    cancellation_reason: str

    @classmethod
    def from_domain(cls, assessment: Assessment) -> AssessmentResponse:
        return cls(
            id=str(assessment.id),
            tenant_id=str(assessment.tenant_id),
            name=assessment.name,
            hazard_type=assessment.hazard_type.value,
            status=assessment.status.value,
            created_by=str(assessment.created_by),
            created_at=assessment.created_at,
            updated_at=assessment.updated_at,
            cancellation_reason=assessment.cancellation_reason,
        )


class AssessmentListResponse(BaseModel):
    data: list[AssessmentResponse]
    next_cursor: str | None
    has_more: bool

    @classmethod
    def from_page(cls, page: CursorPage[Assessment]) -> AssessmentListResponse:
        return cls(
            data=[AssessmentResponse.from_domain(a) for a in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        )
