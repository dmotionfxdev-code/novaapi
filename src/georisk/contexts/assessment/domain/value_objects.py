"""Value objects for the Assessment context.

``AssessmentId`` is defined locally (this context owns the Assessment
aggregate). ``TenantId``/``UserId`` are imported directly from Identity —
legitimate under the shared-kernel relationship (Domain Model §7,
pyproject.toml's corrected import-linter contracts, Sprint 2) — not
redefined locally, since Domain Model §7 is explicit that these types are
"used by every context as-is."
"""

from __future__ import annotations

from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class AssessmentId(TypedId):
    pass


class AssessmentStatus(StrEnum):
    """This sprint's simplified seven-state lifecycle. The full Domain
    Model §6 FSM (DRAFT, AOI_DEFINED, DATA_COLLECTION, ANALYSIS_IN_PROGRESS,
    ANALYSIS_COMPLETE, PREDICTION_GENERATED, VALIDATED, VALIDATION_FAILED,
    REPORTED, ARCHIVED, CANCELLED) has several states whose entry/exit
    conditions depend on contexts that don't exist yet this sprint
    (Geospatial for AOI, the Workflow Engine for stage orchestration,
    Prediction, Validation). Rather than build those states now with no
    real guard behind them, this sprint implements the collapsed,
    "hollow" version explicitly scoped by the sprint brief:

        DRAFT -> READY -> RUNNING -> VALIDATED -> REPORTED -> ARCHIVED
                                    \\-> CANCELLED (from any non-terminal state)

    Later sprints are expected to *elaborate* RUNNING/VALIDATED/REPORTED
    into the fuller state set as their owning contexts land (Workflow
    Engine, Validation, Reporting) — this is an intentional, documented
    simplification, not a divergent redesign of Domain Model §6.
    """

    DRAFT = "DRAFT"
    READY = "READY"
    RUNNING = "RUNNING"
    VALIDATED = "VALIDATED"
    REPORTED = "REPORTED"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class HazardType(StrEnum):
    """Domain Model §3 — extensible; only the four hazard types the
    Platform Architecture document names are enumerated here. No
    hazard-specific behavior is attached to this value in this sprint
    (Hazard Logic is explicitly out of scope) — it is purely a
    classification field.
    """

    FLOOD = "FLOOD"
    WILDFIRE = "WILDFIRE"
    DROUGHT = "DROUGHT"
    LANDSLIDE = "LANDSLIDE"


# Legal transitions (Domain Model §6's FSM pattern). A transition not
# listed here is illegal — enforced by the Assessment entity, never left to
# direct field assignment (this sprint's "No direct state mutation"
# requirement, made literal).
LEGAL_TRANSITIONS: dict[AssessmentStatus, frozenset[AssessmentStatus]] = {
    AssessmentStatus.DRAFT: frozenset({AssessmentStatus.READY, AssessmentStatus.CANCELLED}),
    AssessmentStatus.READY: frozenset({AssessmentStatus.RUNNING, AssessmentStatus.CANCELLED}),
    AssessmentStatus.RUNNING: frozenset({AssessmentStatus.VALIDATED, AssessmentStatus.CANCELLED}),
    AssessmentStatus.VALIDATED: frozenset({AssessmentStatus.REPORTED, AssessmentStatus.CANCELLED}),
    AssessmentStatus.REPORTED: frozenset({AssessmentStatus.ARCHIVED}),
    AssessmentStatus.ARCHIVED: frozenset(),
    AssessmentStatus.CANCELLED: frozenset(),
}
