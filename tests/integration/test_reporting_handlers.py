"""Handler-level integration tests against a real Postgres instance —
``GenerateReportHandler``'s gather -> freeze -> persist -> emit pipeline,
and ``FinalizeReportHandler``'s DRAFT -> FINALIZED transition. Uses small
fake reader implementations (not the real composition-root ones, which
need the full Assessment/Analysis/Prediction/Data Acquisition/Validation
stack — proven separately in ``test_reporting_api.py``'s live-HTTP test)
so this file can exercise the handlers' own logic in isolation, the same
"swap the seam, not the handler" pattern every prior context's handler
tests already use.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.application.commands import (
    FinalizeReportCommand,
    GenerateReportCommand,
)
from georisk.contexts.reporting.application.handlers import (
    FinalizeReportHandler,
    GenerateReportHandler,
)
from georisk.contexts.reporting.application.ports import (
    AssessmentInfo,
    DatasetInfo,
    PredictionRunInfo,
    RegressionInfo,
    StageResultInfo,
    ValidationRunInfo,
)
from georisk.contexts.reporting.domain.errors import IllegalReportStatusTransitionError
from georisk.contexts.reporting.domain.value_objects import ReportStatus
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


class _FakeAssessmentReader:
    def __init__(self, info: AssessmentInfo | None) -> None:
        self._info = info

    async def get_assessment_info(
        self, *, tenant_id: str, assessment_id: str
    ) -> AssessmentInfo | None:
        return self._info


class _FakeStageResultReader:
    def __init__(self, results: list[StageResultInfo]) -> None:
        self._results = results

    async def list_latest_stage_results(
        self, *, tenant_id: str, assessment_id: str, hazard_type: str
    ) -> list[StageResultInfo]:
        return self._results


class _FakePredictionReader:
    def __init__(self, runs: list[PredictionRunInfo]) -> None:
        self._runs = runs

    async def list_latest_prediction_runs(
        self, *, tenant_id: str, assessment_id: str
    ) -> list[PredictionRunInfo]:
        return self._runs


class _FakeDatasetCatalogReader:
    def __init__(self, datasets: list[DatasetInfo]) -> None:
        self._datasets = datasets

    async def list_current_datasets(self, *, tenant_id: str) -> list[DatasetInfo]:
        return self._datasets


class _FakeValidationReader:
    def __init__(self, info: ValidationRunInfo | None) -> None:
        self._info = info

    async def get_latest_validation(
        self, *, tenant_id: str, assessment_id: str
    ) -> ValidationRunInfo | None:
        return self._info


def _assessment_info(assessment_id: str) -> AssessmentInfo:
    return AssessmentInfo(
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


def _handler(
    *,
    assessment_info: AssessmentInfo | None,
    stage_results: list[StageResultInfo] | None = None,
    prediction_runs: list[PredictionRunInfo] | None = None,
    datasets: list[DatasetInfo] | None = None,
    validation_info: ValidationRunInfo | None = None,
    session,  # noqa: ANN001
) -> GenerateReportHandler:
    return GenerateReportHandler(
        session,
        _FakeAssessmentReader(assessment_info),
        _FakeStageResultReader(stage_results or []),
        _FakePredictionReader(prediction_runs or []),
        _FakeDatasetCatalogReader(datasets or []),
        _FakeValidationReader(validation_info),
    )


async def test_generate_report_completes_with_full_sections(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    stage_results = [
        StageResultInfo(
            stage_type="RISK",
            status="COMPLETE",
            confidence_tier="LOW",
            formula_version="fri-v2",
            strategy_version="firas-2.0",
            indicators={"flood_risk_index": 0.11},
            computed_at=datetime.now(UTC),
        )
    ]
    prediction_runs = [
        PredictionRunInfo(
            prediction_run_id=str(uuid.uuid4()),
            method="MULTIPLE_LINEAR_REGRESSION",
            formula_version="mlr-ols-v1",
            sample_size=1000,
            predictor_variable_codes=("ndvi", "wind_speed"),
            dependent_variable_code="burned_area",
            regression=RegressionInfo(
                intercept=0.25,
                coefficients={"ndvi": 0.24, "wind_speed": 0.02},
                r_squared=0.87,
                adjusted_r_squared=0.86,
                rmse=0.08,
                mae=0.06,
            ),
        )
    ]
    datasets = [
        DatasetInfo(
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
        )
    ]
    validation_info = ValidationRunInfo(
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

    handler = _handler(
        assessment_info=_assessment_info(assessment_id),
        stage_results=stage_results,
        prediction_runs=prediction_runs,
        datasets=datasets,
        validation_info=validation_info,
        session=db_session,
    )
    report = await handler.handle(
        GenerateReportCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )

    assert report.status == ReportStatus.DRAFT
    assert report.assessment_summary is not None
    assert report.assessment_summary.aoi_name == "Test AOI"
    assert report.risk_summary is not None
    assert report.risk_summary.stages[0].indicators["flood_risk_index"] == pytest.approx(0.11)
    assert report.strategy_version == "firas-2.0"
    assert report.formula_versions[0].formula_version == "fri-v2"
    assert report.predictor_summary[0].regression is not None
    assert report.predictor_summary[0].regression.r_squared == pytest.approx(0.87)
    assert report.dataset_provenance[0].name == "Rainfall-2020-2025"
    assert report.validation_summary is not None
    assert report.validation_summary.verdict == "PASS"


async def test_generate_report_with_no_optional_data_still_succeeds(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = _handler(assessment_info=_assessment_info(assessment_id), session=db_session)

    report = await handler.handle(
        GenerateReportCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )

    assert report.status == ReportStatus.DRAFT
    assert report.assessment_summary is not None
    assert report.risk_summary is None
    assert report.predictor_summary == ()
    assert report.dataset_provenance == ()
    assert report.validation_summary is None


async def test_generate_report_fails_when_assessment_not_found(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = _handler(assessment_info=None, session=db_session)

    report = await handler.handle(
        GenerateReportCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )

    assert report.status == ReportStatus.FAILED
    assert "not found" in report.error

    outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "Report",
            OutboxEventModel.aggregate_id == str(report.id),
        )
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert "reporting.ReportGenerationFailed" in event_types


async def test_finalize_report_transitions_draft_to_finalized(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    generate_handler = _handler(
        assessment_info=_assessment_info(assessment_id), session=db_session
    )
    report = await generate_handler.handle(
        GenerateReportCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )

    finalize_handler = FinalizeReportHandler(db_session)
    finalized = await finalize_handler.handle(
        FinalizeReportCommand(
            tenant_id=str(tenant_id), report_id=str(report.id), finalized_by="reviewer-1"
        )
    )

    assert finalized.status == ReportStatus.FINALIZED
    assert finalized.finalized_by == "reviewer-1"

    outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "Report",
            OutboxEventModel.aggregate_id == str(report.id),
        )
    )
    event_types = [e.event_type for e in outbox.scalars().all()]
    assert "reporting.ReportGenerated" in event_types
    assert "reporting.ReportFinalized" in event_types


async def test_finalizing_an_already_finalized_report_raises(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    generate_handler = _handler(
        assessment_info=_assessment_info(assessment_id), session=db_session
    )
    report = await generate_handler.handle(
        GenerateReportCommand(
            tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
        )
    )
    finalize_handler = FinalizeReportHandler(db_session)
    await finalize_handler.handle(
        FinalizeReportCommand(
            tenant_id=str(tenant_id), report_id=str(report.id), finalized_by="reviewer-1"
        )
    )

    with pytest.raises(IllegalReportStatusTransitionError):
        await finalize_handler.handle(
            FinalizeReportCommand(
                tenant_id=str(tenant_id), report_id=str(report.id), finalized_by="reviewer-2"
            )
        )


async def test_re_generating_a_report_creates_a_new_version(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = _handler(assessment_info=_assessment_info(assessment_id), session=db_session)
    command = GenerateReportCommand(
        tenant_id=str(tenant_id), assessment_id=assessment_id, issued_by="analyst-1"
    )

    first = await handler.handle(command)
    second = await handler.handle(command)

    assert first.id != second.id
    assert second.version == first.version + 1
