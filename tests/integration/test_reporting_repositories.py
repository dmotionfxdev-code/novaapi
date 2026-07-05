"""Repository-level integration tests against a real Postgres instance —
confirms ``Report``'s domain<->ORM mapping round-trips correctly (every
section VO), that ``save`` inserts on first save and updates in place on
``finalize``, that ``next_version`` increments per assessment, and that
``list_latest_by_tenant`` returns the latest report per assessment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.domain.entities import Report
from georisk.contexts.reporting.domain.value_objects import (
    AssessmentSummary,
    CorrelationPairSummary,
    DatasetProvenanceEntrySummary,
    PredictionSummary,
    RiskSummarySection,
    StageFormulaVersion,
    StageSummary,
    ValidationSummary,
)
from georisk.contexts.reporting.infrastructure.repositories import SqlAlchemyReportRepository

pytestmark = pytest.mark.integration


def _assessment_summary(assessment_id: str) -> AssessmentSummary:
    return AssessmentSummary(
        assessment_id=assessment_id,
        name="Test Assessment",
        hazard_type="FLOOD",
        status="VALIDATED",
        created_at=datetime.now(UTC),
        aoi_name="Test AOI",
        aoi_version=1,
        aoi_area_m2=1234.5,
        sampling_campaign_name="Campaign 1",
        sample_count=1000,
    )


async def test_generated_report_round_trips_every_section(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())

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
    predictor_summary = (
        PredictionSummary(
            prediction_run_id=str(uuid.uuid4()),
            method="PEARSON_CORRELATION",
            formula_version="pearson-v1",
            sample_size=1000,
            predictor_variable_codes=("ndvi", "wind_speed"),
            dependent_variable_code=None,
            correlation_pairs=(
                CorrelationPairSummary(
                    variable_a="ndvi", variable_b="wind_speed", coefficient=0.42, sample_size=1000
                ),
            ),
        ),
    )
    dataset_provenance = (
        DatasetProvenanceEntrySummary(
            dataset_id=str(uuid.uuid4()),
            name="Rainfall-2020-2025",
            version=2,
            dataset_type="RASTER",
            provider="CHIRPS",
            processing_method="CLOUD_MASKED",
            is_mlr_ready=True,
            is_correlation_ready=False,
            provenance_entry_count=2,
            latest_provenance_action="REVISED",
            latest_provenance_at=datetime.now(UTC),
        ),
    )
    validation_summary = ValidationSummary(
        validation_run_id=str(uuid.uuid4()),
        subject_type="STAGE_RESULT",
        verdict="PASS",
        sample_size=100,
        overall_accuracy=0.9,
        precision=0.88,
        recall=0.91,
        f1_score=0.895,
        kappa=0.8,
        auc=0.93,
        computed_at=datetime.now(UTC),
    )

    report, _event = Report.generate(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        version=1,
        assessment_summary=_assessment_summary(assessment_id),
        risk_summary=risk_summary,
        predictor_summary=predictor_summary,
        dataset_provenance=dataset_provenance,
        validation_summary=validation_summary,
        formula_versions=(StageFormulaVersion(stage_type="RISK", formula_version="fri-v2"),),
        strategy_version="firas-2.0",
        issued_by="analyst-1",
    )
    repo = SqlAlchemyReportRepository(db_session)
    await repo.save(report)
    await db_session.flush()

    fetched = await repo.get_by_id(report.id)
    assert fetched is not None
    assert fetched.assessment_summary is not None
    assert fetched.assessment_summary.aoi_name == "Test AOI"
    assert fetched.risk_summary is not None
    assert fetched.risk_summary.stages[0].indicators["flood_risk_index"] == pytest.approx(0.11)
    assert fetched.predictor_summary[0].correlation_pairs[0].coefficient == pytest.approx(0.42)
    assert fetched.dataset_provenance[0].name == "Rainfall-2020-2025"
    assert fetched.validation_summary is not None
    assert fetched.validation_summary.verdict == "PASS"
    assert fetched.strategy_version == "firas-2.0"
    assert fetched.formula_versions[0].formula_version == "fri-v2"


async def test_finalize_updates_the_same_row_in_place(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    report, _event = Report.generate(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        version=1,
        assessment_summary=_assessment_summary(assessment_id),
        risk_summary=None,
        predictor_summary=(),
        dataset_provenance=(),
        validation_summary=None,
        formula_versions=(),
        strategy_version=None,
        issued_by="analyst-1",
    )
    repo = SqlAlchemyReportRepository(db_session)
    await repo.save(report)
    await db_session.flush()

    report.finalize(finalized_by="reviewer-1")
    await repo.save(report)
    await db_session.flush()

    fetched = await repo.get_by_id(report.id)
    assert fetched is not None
    assert fetched.status.value == "FINALIZED"
    assert fetched.finalized_by == "reviewer-1"
    assert fetched.version == 1  # same generation, not a new row


async def test_next_version_increments_per_assessment(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    repo = SqlAlchemyReportRepository(db_session)

    assert await repo.next_version(tenant_id, assessment_id) == 1

    report, _event = Report.generate(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        version=1,
        assessment_summary=_assessment_summary(assessment_id),
        risk_summary=None,
        predictor_summary=(),
        dataset_provenance=(),
        validation_summary=None,
        formula_versions=(),
        strategy_version=None,
        issued_by="analyst-1",
    )
    await repo.save(report)
    await db_session.flush()

    assert await repo.next_version(tenant_id, assessment_id) == 2


async def test_list_latest_by_tenant_returns_one_row_per_assessment(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_a = str(uuid.uuid4())
    assessment_b = str(uuid.uuid4())
    repo = SqlAlchemyReportRepository(db_session)

    for assessment_id in (assessment_a, assessment_a, assessment_b):
        version = await repo.next_version(tenant_id, assessment_id)
        report, _event = Report.generate(
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            version=version,
            assessment_summary=_assessment_summary(assessment_id),
            risk_summary=None,
            predictor_summary=(),
            dataset_provenance=(),
            validation_summary=None,
            formula_versions=(),
            strategy_version=None,
            issued_by="analyst-1",
        )
        await repo.save(report)
        await db_session.flush()

    latest = await repo.list_latest_by_tenant(tenant_id)
    assert len(latest) == 2
    by_assessment = {r.assessment_id: r.version for r in latest}
    assert by_assessment[assessment_a] == 2
    assert by_assessment[assessment_b] == 1
