"""Command DTOs (Application Layer §1). Every state-changing action on an
Assessment is one of these — named as an imperative verb phrase, one
command per FSM transition (value_objects.LEGAL_TRANSITIONS), each handled
by exactly one handler touching exactly one aggregate instance
(Application Layer §9).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateAssessment:
    tenant_id: str
    name: str
    hazard_type: str
    created_by: str


@dataclass(frozen=True, slots=True)
class MarkAssessmentReady:
    tenant_id: str
    assessment_id: str
    changed_by: str


@dataclass(frozen=True, slots=True)
class StartAssessment:
    tenant_id: str
    assessment_id: str
    changed_by: str


@dataclass(frozen=True, slots=True)
class ValidateAssessment:
    tenant_id: str
    assessment_id: str
    changed_by: str


@dataclass(frozen=True, slots=True)
class ReportAssessment:
    tenant_id: str
    assessment_id: str
    changed_by: str


@dataclass(frozen=True, slots=True)
class ArchiveAssessment:
    tenant_id: str
    assessment_id: str
    archived_by: str


@dataclass(frozen=True, slots=True)
class CancelAssessment:
    tenant_id: str
    assessment_id: str
    reason: str
    cancelled_by: str
