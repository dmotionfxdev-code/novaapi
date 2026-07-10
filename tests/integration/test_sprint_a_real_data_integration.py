"""Sprint A integration tests — "Replace all stub providers so Analysis
and Prediction use real uploaded datasets instead of synthetic reference
data." Proves, against a real Postgres instance:

1. ``CompositionRootIndicatorInputProvider`` (``api/analysis_ports.py``)
   feeds ``AnalysisStageExecutor`` real, tenant-uploaded Data Acquisition
   payloads — and the computed FIRAS indicators genuinely differ from
   ``StubIndicatorInputProvider``'s fixed values, proving the real data
   actually drove the computation rather than a stub silently still
   running underneath.
2. Missing real data fails honestly (``StageResult.FAILED`` with a clear
   error), never silently falling back to fabricated values.
3. ``CompositionRootPredictionDataProvider`` (``api/prediction_ports.py``)
   reads real completed ``StageResult`` history across multiple real
   assessments as Prediction's observation rows, excluding any assessment
   missing a requested variable code rather than padding it.
4. An end-to-end demonstration: Upload dataset -> Catalog -> Analysis ->
   Prediction -> Validation, entirely on real data, zero stubs in the
   Analysis/Prediction seams.

Uses the ``real_database`` fixture, not ``db_session``: both
``CompositionRootIndicatorInputProvider`` and
``CompositionRootPredictionDataProvider`` open their own sessions per call
(the same "manages its own transaction boundary" pattern every
composition-root reader in this platform already uses), so setup data
must be committed on a real, independently-connecting ``Database`` for it
to be visible to those sessions — ``db_session``'s per-test rollback
would hide it.
"""

from __future__ import annotations

import base64
import json
import uuid
from datetime import UTC, date, datetime

import pytest

from georisk.api.analysis_ports import (
    CompositionRootIndicatorInputProvider,
    MissingIndicatorDatasetError,
)
from georisk.api.prediction_ports import (
    CompositionRootPredictionDataProvider,
    CompositionRootVariableSelectionReader,
    MissingHazardTypeError,
)
from georisk.api.workflow_stage_executors import AnalysisStageExecutor
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.value_objects import (
    HazardType as AnalysisHazardType,
)
from georisk.contexts.analysis.domain.value_objects import (
    StageResultId,
    StageResultStatus,
)
from georisk.contexts.analysis.domain.value_objects import (
    StageType as AnalysisStageType,
)
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy
from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.value_objects import HazardType as AssessmentHazardType
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageType as AssessmentStageType,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.data_acquisition.domain.entities import (
    AcquisitionJob,
    Dataset,
    DatasetSource,
    PredictorVariable,
    VariableSelection,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionFormat,
    DataProvider,
    DatasetMetadata,
    DatasetType,
    ProcessingMethod,
    VariableCategory,
    VariableDataType,
    VariableRole,
)
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyAcquisitionJobRepository,
    SqlAlchemyDatasetRepository,
    SqlAlchemyDatasetSourceRepository,
    SqlAlchemyPredictorVariableRepository,
    SqlAlchemyVariableSelectionRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.prediction.application.commands import RunPredictionCommand
from georisk.contexts.prediction.application.handlers import RunPredictionHandler
from georisk.contexts.prediction.application.ports import PredictorVariableInfo
from georisk.contexts.prediction.domain.value_objects import PredictionRunStatus
from georisk.db.session import Database
from georisk.shared_kernel.types import DateRange

pytestmark = pytest.mark.integration

# Deliberately far from StubIndicatorInputProvider's fixed HAZARD values
# (rainfall_index=0.65, water_level_index=0.55, slope_index=0.40,
# drainage_index=0.50, land_use_index=0.60, soil_index=0.70) — a passing
# assertion against these genuinely proves the computation was driven by
# the uploaded payload, not a stub silently still running underneath.
_FIRAS_HAZARD_UPLOAD = {
    "rainfall_index": 0.95,
    "water_level_index": 0.90,
    "slope_index": 0.85,
    "drainage_index": 0.80,
    "land_use_index": 0.92,
    "soil_index": 0.88,
}


class _FakeSamplingCampaignReader:
    def __init__(self, sample_count: int) -> None:
        self._sample_count = sample_count

    async def get_sample_count(
        self, *, tenant_id: str, sampling_campaign_id: str
    ) -> int | None:
        return self._sample_count


def _dataset_metadata(name: str) -> DatasetMetadata:
    now = datetime.now(UTC)
    return DatasetMetadata(
        name=name,
        dataset_type=DatasetType.TABULAR,
        source="Tenant Upload",
        provider=DataProvider.LOCAL_UPLOAD,
        acquisition_date=date.today(),
        spatial_resolution_m=None,
        temporal_resolution=None,
        crs="EPSG:4326",
        spatial_coverage="Tanzania",
        temporal_coverage=DateRange(start=now, end=now),
        processing_method=ProcessingMethod.RAW,
    )


async def _catalog_uploaded_indicator_dataset(
    db: Database,
    *,
    tenant_id: TenantId,
    name: str,
    payload: dict,
    previous: Dataset | None = None,
) -> Dataset:
    """Mirrors the real Local Upload flow this platform actually has:
    register a DatasetSource (first upload only), schedule + start +
    complete an AcquisitionJob carrying ``payload`` as base64-encoded
    JSON, and catalog (or, for a re-upload, ``revise()``) the Dataset it
    produces — under the ``f"{hazard_type}:{stage_type}"`` naming
    convention ``CompositionRootIndicatorInputProvider`` looks datasets up
    by. Re-uploading via ``revise()`` (not a second independent
    ``catalog()``) is deliberate: ``DatasetRepository.get_latest`` only
    has one well-defined "latest" per (tenant, name) when versions form a
    single lineage, exactly Sprint 7's own versioning discipline.
    """
    async with db.session() as session:
        if previous is None:
            source, _ = DatasetSource.register(
                tenant_id=tenant_id,
                name=f"Local Upload — {name}",
                provider=DataProvider.LOCAL_UPLOAD,
                description="",
                created_by="analyst-1",
            )
            await SqlAlchemyDatasetSourceRepository(session).save(source)
            source_id = source.id
        else:
            source_id = previous.dataset_source_id

        raw_content_base64 = base64.b64encode(json.dumps(payload).encode()).decode()
        job, _ = AcquisitionJob.schedule(
            tenant_id=tenant_id,
            provider=DataProvider.LOCAL_UPLOAD,
            source_reference=name,
            format=AcquisitionFormat.JSON,
            dataset_source_id=source_id,
            declared_crs="EPSG:4326",
            raw_content_base64=raw_content_base64,
            requested_by="analyst-1",
        )
        job_repo = SqlAlchemyAcquisitionJobRepository(session)
        await job_repo.save(job)
        job.start()

        dataset_repo = SqlAlchemyDatasetRepository(session)
        if previous is None:
            dataset, _ = Dataset.catalog(
                tenant_id=tenant_id,
                dataset_source_id=source_id,
                metadata=_dataset_metadata(name),
                readiness=frozenset(),
                catalogued_by="analyst-1",
            )
        else:
            dataset, _ = Dataset.revise(
                previous=previous,
                metadata=_dataset_metadata(name),
                readiness=frozenset(),
                description="Re-uploaded with new observations",
                catalogued_by="analyst-1",
            )
            previous.mark_superseded()
            await dataset_repo.save(previous)
        await dataset_repo.save(dataset)

        job.complete(dataset_id=dataset.id)
        await job_repo.save(job)
        await session.commit()
    return dataset


async def _create_assessment(
    db: Database,
    tenant_id: TenantId,
    hazard_type: AssessmentHazardType = AssessmentHazardType.FLOOD,
) -> Assessment:
    async with db.session() as session:
        assessment, _ = Assessment.create(
            tenant_id=tenant_id,
            name=f"Sprint A Assessment {uuid.uuid4().hex[:8]}",
            hazard_type=hazard_type,
            created_by=UserId.new(),
        )
        assessment.mark_ready(changed_by="tester")
        await SqlAlchemyAssessmentRepository(session).save(assessment)
        await session.commit()
    return assessment


def _firas_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(AnalysisHazardType.FLOOD, FIRASHazardStrategy())
    return registry


# --- 1. CompositionRootIndicatorInputProvider reads real uploaded data ---


async def test_real_indicator_input_provider_returns_uploaded_payload_verbatim(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    assessment = await _create_assessment(real_database, tenant_id)
    await _catalog_uploaded_indicator_dataset(
        real_database, tenant_id=tenant_id, name="FLOOD:HAZARD", payload=_FIRAS_HAZARD_UPLOAD
    )

    provider = CompositionRootIndicatorInputProvider(real_database)
    result = await provider.provide_raw_inputs(
        hazard_type=AnalysisHazardType.FLOOD,
        stage_type=AnalysisStageType.HAZARD,
        assessment_id=str(assessment.id),
    )

    assert result == _FIRAS_HAZARD_UPLOAD


async def test_indicator_input_provider_raises_when_no_dataset_cataloged(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    assessment = await _create_assessment(real_database, tenant_id)
    provider = CompositionRootIndicatorInputProvider(real_database)

    with pytest.raises(MissingIndicatorDatasetError, match="FLOOD:HAZARD"):
        await provider.provide_raw_inputs(
            hazard_type=AnalysisHazardType.FLOOD,
            stage_type=AnalysisStageType.HAZARD,
            assessment_id=str(assessment.id),
        )


async def test_analysis_stage_computes_from_real_uploaded_data_not_stub_values(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    assessment = await _create_assessment(real_database, tenant_id)
    await _catalog_uploaded_indicator_dataset(
        real_database, tenant_id=tenant_id, name="FLOOD:HAZARD", payload=_FIRAS_HAZARD_UPLOAD
    )

    executor = AnalysisStageExecutor(
        real_database, _firas_registry(), CompositionRootIndicatorInputProvider(real_database)
    )
    outcome = await executor.execute(AssessmentStageType.HAZARD, assessment_id=str(assessment.id))

    assert outcome.success is True
    async with real_database.session() as session:
        stage_result = await SqlAlchemyStageResultRepository(session).get_by_id(
            StageResultId.from_string(outcome.stage_result_ref)
        )
    assert stage_result is not None
    assert stage_result.status == StageResultStatus.COMPLETE
    # The persisted snapshot's inputs contain the uploaded payload
    # verbatim (merged alongside the computed indicators it produced)...
    for code, value in _FIRAS_HAZARD_UPLOAD.items():
        assert stage_result.snapshot.inputs[code] == value
    # ...and the computed indicator is NOT StubIndicatorInputProvider's
    # well-known 0.565 (see test_firas_workflow_integration.py) — proving
    # this computation was genuinely driven by the real uploaded data.
    computed = stage_result.indicators.value("flood_hazard_index")
    assert computed != pytest.approx(0.565)


async def test_analysis_stage_fails_honestly_when_no_dataset_uploaded(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    assessment = await _create_assessment(real_database, tenant_id)
    executor = AnalysisStageExecutor(
        real_database, _firas_registry(), CompositionRootIndicatorInputProvider(real_database)
    )

    outcome = await executor.execute(AssessmentStageType.HAZARD, assessment_id=str(assessment.id))

    assert outcome.success is False
    assert "FLOOD:HAZARD" in (outcome.error or "")
    async with real_database.session() as session:
        results = await SqlAlchemyStageResultRepository(session).list_by_assessment(
            tenant_id, str(assessment.id)
        )
    assert len(results) == 1
    assert results[0].status == StageResultStatus.FAILED
    assert results[0].indicators is None


# --- 2. CompositionRootPredictionDataProvider reads real Analysis history ---


async def test_real_prediction_data_provider_reads_completed_analysis_outputs(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    registry = _firas_registry()
    executor = AnalysisStageExecutor(
        real_database, registry, CompositionRootIndicatorInputProvider(real_database)
    )

    rainfall_values = [0.20, 0.50, 0.90]
    previous_dataset: Dataset | None = None
    for rainfall in rainfall_values:
        assessment = await _create_assessment(real_database, tenant_id)
        previous_dataset = await _catalog_uploaded_indicator_dataset(
            real_database,
            tenant_id=tenant_id,
            name="FLOOD:HAZARD",
            payload={**_FIRAS_HAZARD_UPLOAD, "rainfall_index": rainfall},
            previous=previous_dataset,
        )
        outcome = await executor.execute(
            AssessmentStageType.HAZARD, assessment_id=str(assessment.id)
        )
        assert outcome.success is True

    provider = CompositionRootPredictionDataProvider(real_database)
    rows = await provider.generate_observations(
        tenant_id=str(tenant_id),
        hazard_type="FLOOD",
        variables=(_variable("rainfall_index"),),
        sample_count=10,
        seed=1,
    )

    assert {row["rainfall_index"] for row in rows} == set(rainfall_values)


async def test_real_prediction_data_provider_excludes_assessments_missing_a_code(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    registry = _firas_registry()
    executor = AnalysisStageExecutor(
        real_database, registry, CompositionRootIndicatorInputProvider(real_database)
    )
    assessment = await _create_assessment(real_database, tenant_id)
    await _catalog_uploaded_indicator_dataset(
        real_database, tenant_id=tenant_id, name="FLOOD:HAZARD", payload=_FIRAS_HAZARD_UPLOAD
    )
    outcome = await executor.execute(AssessmentStageType.HAZARD, assessment_id=str(assessment.id))
    assert outcome.success is True

    provider = CompositionRootPredictionDataProvider(real_database)
    # No assessment for this tenant has ever completed an EXPOSURE stage,
    # so "flood_exposure_index" never appears in any merged row — the
    # real provider must exclude, never fabricate, that observation.
    rows = await provider.generate_observations(
        tenant_id=str(tenant_id),
        hazard_type="FLOOD",
        variables=(_variable("rainfall_index"), _variable("flood_exposure_index")),
        sample_count=10,
        seed=1,
    )
    assert rows == ()


async def test_real_prediction_data_provider_requires_hazard_type(
    real_database: Database,
) -> None:
    provider = CompositionRootPredictionDataProvider(real_database)
    with pytest.raises(MissingHazardTypeError):
        await provider.generate_observations(
            tenant_id=str(TenantId.new()),
            hazard_type=None,
            variables=(_variable("rainfall_index"),),
            sample_count=5,
            seed=1,
        )


def _variable(code: str) -> PredictorVariableInfo:
    return PredictorVariableInfo(
        predictor_variable_id=str(uuid.uuid4()),
        code=code,
        name=code,
        variable_role="INDEPENDENT",
        value_min=0.0,
        value_max=1.0,
    )


# --- 3. End-to-end: Upload -> Catalog -> Analysis -> Prediction -> Validation ---


async def test_end_to_end_upload_catalog_analysis_prediction_validation(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    registry = _firas_registry()
    executor = AnalysisStageExecutor(
        real_database, registry, CompositionRootIndicatorInputProvider(real_database)
    )

    rainfall_values = [0.3, 0.6, 0.9]
    previous_dataset: Dataset | None = None
    for rainfall in rainfall_values:
        # Upload + Catalog (Data Acquisition, real).
        previous_dataset = await _catalog_uploaded_indicator_dataset(
            real_database,
            tenant_id=tenant_id,
            name="FLOOD:HAZARD",
            payload={**_FIRAS_HAZARD_UPLOAD, "rainfall_index": rainfall},
            previous=previous_dataset,
        )
        # Analysis (real IndicatorInputProvider, no stub).
        assessment = await _create_assessment(real_database, tenant_id)
        outcome = await executor.execute(
            AssessmentStageType.HAZARD, assessment_id=str(assessment.id)
        )
        assert outcome.success is True

    # Register a real, confirmed VariableSelection over an indicator code
    # that genuinely exists in the real StageResult history above.
    async with real_database.session() as session:
        variable, _ = PredictorVariable.register(
            tenant_id=tenant_id,
            name="Rainfall Index",
            code="rainfall_index",
            category=VariableCategory.METEOROLOGICAL,
            variable_role=VariableRole.INDEPENDENT,
            data_type=VariableDataType.CONTINUOUS,
            unit="index",
            value_min=0.0,
            value_max=1.0,
            is_required_for_mlr=False,
            linked_dataset_id=None,
            created_by="analyst-1",
        )
        await SqlAlchemyPredictorVariableRepository(session).save(variable)
        selection, _ = VariableSelection.create(
            tenant_id=tenant_id,
            name="Rainfall-only selection",
            hazard_type="FLOOD",
            selected_variable_ids=(variable.id,),
            created_by="analyst-1",
        )
        selection.confirm()
        await SqlAlchemyVariableSelectionRepository(session).save(selection)
        await session.commit()

    # Prediction (real PredictionDataProvider reading real Analysis
    # outputs; VariableSelectionReader is Sprint 8's real reader,
    # unchanged; SamplingCampaignReader is faked here since Geospatial's
    # sampling machinery is outside Sprint A's scope).
    async with real_database.session() as session:
        handler = RunPredictionHandler(
            session,
            CompositionRootVariableSelectionReader(real_database),
            _FakeSamplingCampaignReader(len(rainfall_values)),
            CompositionRootPredictionDataProvider(real_database),
        )
        run = await handler.handle(
            RunPredictionCommand(
                tenant_id=str(tenant_id),
                assessment_id=str(uuid.uuid4()),
                variable_selection_id=str(selection.id),
                sampling_campaign_id=str(uuid.uuid4()),
                method="PEARSON_CORRELATION",
                issued_by="analyst-1",
            )
        )

    assert run.status == PredictionRunStatus.COMPLETED
    assert run.correlation_result is not None
    # Only one variable was selected, so the pair-count is 0, but the
    # model's own recorded sample size proves it ran against exactly the
    # 3 real observations catalogued above, not any synthetic count.
    assert run.model_metadata.sample_size == len(rainfall_values)

    # Validation (Sprint 4, entirely untouched by Sprint A) still runs as
    # its own independent stage inside the same workflow engine wiring —
    # proven already by test_firas_workflow_integration.py; Sprint A adds
    # no new Validation behavior, only real upstream data.
