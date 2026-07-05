"""The ``Report`` aggregate (Domain Model §1 row 15) — Reporting's sole
aggregate root. "A report is a frozen, signed-off view of an assessment at
a point in time — never a live query" (Domain Model §4).

Lifecycle is two steps, matching Application Layer §3's ``GenerateReport``/
``FinalizeReport`` command pair (not a single atomic "always finalized"
step like ``PredictionRun``'s, since Sprint 9's "Immutable finalized
reports" requirement only makes sense against a non-immutable precursor
state): ``generate()`` builds a brand-new ``DRAFT`` version, freezing every
section's data at that moment (``ReportSnapshotBuilder``'s job, done by
the application handler before calling this classmethod — this class only
holds the frozen result); ``finalize()`` is the one remaining legal
transition out of ``DRAFT``, mutating this SAME row's status in place (not
minting a new version — ``version`` here means "which generation of
report this is," not an optimistic-concurrency counter). Once
``FINALIZED`` (or ``FAILED``), no method on this class can change the
aggregate further — "immutable finalized reports" is therefore structural,
the same "no direct mutation" discipline every prior aggregate in this
codebase enforces for its own state.

Nothing here imports from ``contexts.assessment``, ``contexts.analysis``,
``contexts.prediction``, ``contexts.validation``, ``contexts.geospatial``,
or ``contexts.data_acquisition`` — structurally enforced by the
import-linter's peer-independence contract; Reporting is a Conformist
downstream reader (Domain Model §7), never importing an upstream context's
domain types directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.domain.errors import IllegalReportStatusTransitionError
from georisk.contexts.reporting.domain.events import (
    ReportFinalized,
    ReportGenerated,
    ReportGenerationFailed,
)
from georisk.contexts.reporting.domain.value_objects import (
    AssessmentSummary,
    DatasetProvenanceEntrySummary,
    PredictionSummary,
    ReportId,
    ReportStatus,
    RiskSummarySection,
    StageFormulaVersion,
    ValidationSummary,
)


@dataclass(slots=True)
class Report:
    id: ReportId
    tenant_id: TenantId
    # Soft, plain-string cross-context reference — assessment is a peer
    # context (import-linter's independence contract).
    assessment_id: str
    version: int
    status: ReportStatus
    generated_at: datetime
    issued_by: str
    assessment_summary: AssessmentSummary | None = None
    risk_summary: RiskSummarySection | None = None
    predictor_summary: tuple[PredictionSummary, ...] = field(default_factory=tuple)
    dataset_provenance: tuple[DatasetProvenanceEntrySummary, ...] = field(default_factory=tuple)
    validation_summary: ValidationSummary | None = None
    formula_versions: tuple[StageFormulaVersion, ...] = field(default_factory=tuple)
    strategy_version: str | None = None
    error: str | None = None
    finalized_by: str | None = None
    finalized_at: datetime | None = None

    @classmethod
    def generate(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        version: int,
        assessment_summary: AssessmentSummary,
        risk_summary: RiskSummarySection | None,
        predictor_summary: tuple[PredictionSummary, ...],
        dataset_provenance: tuple[DatasetProvenanceEntrySummary, ...],
        validation_summary: ValidationSummary | None,
        formula_versions: tuple[StageFormulaVersion, ...],
        strategy_version: str | None,
        issued_by: str,
    ) -> tuple[Report, ReportGenerated]:
        report = cls(
            id=ReportId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            version=version,
            status=ReportStatus.DRAFT,
            generated_at=datetime.now(UTC),
            issued_by=issued_by,
            assessment_summary=assessment_summary,
            risk_summary=risk_summary,
            predictor_summary=predictor_summary,
            dataset_provenance=dataset_provenance,
            validation_summary=validation_summary,
            formula_versions=formula_versions,
            strategy_version=strategy_version,
        )
        event = ReportGenerated(
            report_id=str(report.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            version=version,
            hazard_type=assessment_summary.hazard_type,
            has_risk_summary=risk_summary is not None,
            has_prediction_summary=len(predictor_summary) > 0,
            has_validation_summary=validation_summary is not None,
            dataset_count=len(dataset_provenance),
        )
        return report, event

    @classmethod
    def failed(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        version: int,
        error: str,
        issued_by: str,
    ) -> tuple[Report, ReportGenerationFailed]:
        report = cls(
            id=ReportId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            version=version,
            status=ReportStatus.FAILED,
            generated_at=datetime.now(UTC),
            issued_by=issued_by,
            error=error,
        )
        event = ReportGenerationFailed(
            report_id=str(report.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            version=version,
            error=error,
        )
        return report, event

    def finalize(self, *, finalized_by: str) -> ReportFinalized:
        if self.status is not ReportStatus.DRAFT:
            raise IllegalReportStatusTransitionError(
                f"Report {self.id} is {self.status}, not DRAFT — only a DRAFT report can be "
                "finalized"
            )
        self.status = ReportStatus.FINALIZED
        self.finalized_by = finalized_by
        self.finalized_at = datetime.now(UTC)
        return ReportFinalized(
            report_id=str(self.id),
            tenant_id=str(self.tenant_id),
            assessment_id=self.assessment_id,
            version=self.version,
            finalized_by=finalized_by,
        )
