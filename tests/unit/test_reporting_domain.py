"""Domain-layer unit tests for the ``Report`` aggregate — pure logic, no
I/O.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.domain.entities import Report
from georisk.contexts.reporting.domain.errors import IllegalReportStatusTransitionError
from georisk.contexts.reporting.domain.value_objects import (
    AssessmentSummary,
    ReportStatus,
    RiskSummarySection,
    StageFormulaVersion,
    StageSummary,
)

pytestmark = pytest.mark.unit


def _assessment_summary() -> AssessmentSummary:
    return AssessmentSummary(
        assessment_id=str(uuid.uuid4()),
        name="Test Assessment",
        hazard_type="FLOOD",
        status="VALIDATED",
        created_at=datetime.now(UTC),
    )


def test_generate_produces_draft_report_with_generated_event() -> None:
    risk_summary = RiskSummarySection(
        hazard_type="FLOOD",
        stages=(
            StageSummary(
                stage_type="RISK",
                status="COMPLETE",
                confidence_tier="LOW",
                indicators={"flood_risk_index": 0.11},
                computed_at=datetime.now(UTC),
            ),
        ),
    )
    report, event = Report.generate(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        version=1,
        assessment_summary=_assessment_summary(),
        risk_summary=risk_summary,
        predictor_summary=(),
        dataset_provenance=(),
        validation_summary=None,
        formula_versions=(StageFormulaVersion(stage_type="RISK", formula_version="fri-v2"),),
        strategy_version="firas-2.0",
        issued_by="analyst-1",
    )
    assert report.status == ReportStatus.DRAFT
    assert report.risk_summary is risk_summary
    assert report.finalized_at is None
    assert event.event_type == "reporting.ReportGenerated"
    assert event.has_risk_summary is True
    assert event.has_prediction_summary is False
    assert event.has_validation_summary is False


def test_finalize_transitions_draft_to_finalized() -> None:
    report, _event = Report.generate(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        version=1,
        assessment_summary=_assessment_summary(),
        risk_summary=None,
        predictor_summary=(),
        dataset_provenance=(),
        validation_summary=None,
        formula_versions=(),
        strategy_version=None,
        issued_by="analyst-1",
    )
    finalized_event = report.finalize(finalized_by="reviewer-1")
    assert report.status == ReportStatus.FINALIZED
    assert report.finalized_by == "reviewer-1"
    assert report.finalized_at is not None
    assert finalized_event.event_type == "reporting.ReportFinalized"
    assert finalized_event.finalized_by == "reviewer-1"


def test_finalize_twice_raises_illegal_transition() -> None:
    report, _event = Report.generate(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        version=1,
        assessment_summary=_assessment_summary(),
        risk_summary=None,
        predictor_summary=(),
        dataset_provenance=(),
        validation_summary=None,
        formula_versions=(),
        strategy_version=None,
        issued_by="analyst-1",
    )
    report.finalize(finalized_by="reviewer-1")
    with pytest.raises(IllegalReportStatusTransitionError):
        report.finalize(finalized_by="reviewer-2")


def test_failed_produces_failed_report_with_no_sections() -> None:
    report, event = Report.failed(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        version=1,
        error="Assessment not found",
        issued_by="analyst-1",
    )
    assert report.status == ReportStatus.FAILED
    assert report.assessment_summary is None
    assert report.error == "Assessment not found"
    assert event.event_type == "reporting.ReportGenerationFailed"
    assert event.error == "Assessment not found"
