"""Handler-level integration tests against a real Postgres instance —
``RunPredictionHandler``'s gather -> compute -> persist -> emit pipeline.
Uses small fake ``VariableSelectionReader``/``SamplingCampaignReader``
implementations (not the real composition-root ones, which need the full
Data Acquisition/Geospatial stack — proven separately in
``test_prediction_api.py``'s live-HTTP test) so this file can exercise
the handler's own logic in isolation, the same "swap the seam, not the
handler" pattern every prior context's handler tests already use.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.application.commands import RunPredictionCommand
from georisk.contexts.prediction.application.handlers import RunPredictionHandler
from georisk.contexts.prediction.application.ports import (
    PredictorVariableInfo,
    StubPredictionDataProvider,
    VariableSelectionInfo,
)
from georisk.contexts.prediction.domain.value_objects import PredictionRunStatus
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration

_NDVI = PredictorVariableInfo(
    predictor_variable_id=str(uuid.uuid4()),
    code="ndvi",
    name="NDVI",
    variable_role="INDEPENDENT",
    value_min=-1.0,
    value_max=1.0,
)
_WIND = PredictorVariableInfo(
    predictor_variable_id=str(uuid.uuid4()),
    code="wind_speed",
    name="Wind Speed",
    variable_role="INDEPENDENT",
    value_min=0.0,
    value_max=30.0,
)
_BURNED_AREA = PredictorVariableInfo(
    predictor_variable_id=str(uuid.uuid4()),
    code="burned_area",
    name="Burned Area",
    variable_role="DEPENDENT",
    value_min=0.0,
    value_max=1.0,
)


class _FakeVariableSelectionReader:
    def __init__(self, selection: VariableSelectionInfo | None) -> None:
        self._selection = selection

    async def get_selection(
        self, *, tenant_id: str, variable_selection_id: str
    ) -> VariableSelectionInfo | None:
        return self._selection


class _FakeSamplingCampaignReader:
    def __init__(self, sample_count: int | None) -> None:
        self._sample_count = sample_count

    async def get_sample_count(
        self, *, tenant_id: str, sampling_campaign_id: str
    ) -> int | None:
        return self._sample_count


def _confirmed_selection(*variables) -> VariableSelectionInfo:  # noqa: ANN002
    return VariableSelectionInfo(
        variable_selection_id=str(uuid.uuid4()),
        status="CONFIRMED",
        hazard_type="WILDFIRE",
        variables=tuple(variables),
    )


async def test_pearson_correlation_run_completes(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    handler = RunPredictionHandler(
        db_session,
        _FakeVariableSelectionReader(_confirmed_selection(_NDVI, _WIND)),
        _FakeSamplingCampaignReader(1000),
        StubPredictionDataProvider(),
    )
    run = await handler.handle(
        RunPredictionCommand(
            tenant_id=str(tenant_id),
            assessment_id=str(uuid.uuid4()),
            variable_selection_id=str(uuid.uuid4()),
            sampling_campaign_id=str(uuid.uuid4()),
            method="PEARSON_CORRELATION",
            issued_by="analyst-1",
        )
    )
    assert run.status == PredictionRunStatus.COMPLETED
    assert run.correlation_result is not None
    assert run.correlation_result.get("ndvi", "wind_speed") is not None
    assert run.model_metadata is not None
    assert run.model_metadata.sample_size == 1000
    assert run.model_metadata.formula_version == "pearson-v1"


async def test_mlr_run_completes_with_dependent_and_independent_variables(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    handler = RunPredictionHandler(
        db_session,
        _FakeVariableSelectionReader(_confirmed_selection(_NDVI, _WIND, _BURNED_AREA)),
        _FakeSamplingCampaignReader(1000),
        StubPredictionDataProvider(),
    )
    run = await handler.handle(
        RunPredictionCommand(
            tenant_id=str(tenant_id),
            assessment_id=str(uuid.uuid4()),
            variable_selection_id=str(uuid.uuid4()),
            sampling_campaign_id=str(uuid.uuid4()),
            method="MULTIPLE_LINEAR_REGRESSION",
            issued_by="analyst-1",
        )
    )
    assert run.status == PredictionRunStatus.COMPLETED
    assert run.regression_result is not None
    # The stub synthesizes the dependent as a noisy function of the
    # independents, so R² should be meaningfully above zero — proving
    # the pipeline produces a genuinely fitted model, not degenerate
    # noise-vs-noise.
    assert run.regression_result.r_squared > 0.1
    assert run.model_metadata is not None
    assert run.model_metadata.dependent_variable_code == "burned_area"
    assert set(run.model_metadata.predictor_variable_codes) == {"ndvi", "wind_speed"}


async def test_mlr_without_dependent_variable_fails(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    handler = RunPredictionHandler(
        db_session,
        _FakeVariableSelectionReader(_confirmed_selection(_NDVI, _WIND)),
        _FakeSamplingCampaignReader(1000),
        StubPredictionDataProvider(),
    )
    run = await handler.handle(
        RunPredictionCommand(
            tenant_id=str(tenant_id),
            assessment_id=str(uuid.uuid4()),
            variable_selection_id=str(uuid.uuid4()),
            sampling_campaign_id=str(uuid.uuid4()),
            method="MULTIPLE_LINEAR_REGRESSION",
            issued_by="analyst-1",
        )
    )
    assert run.status == PredictionRunStatus.FAILED
    assert "DEPENDENT" in run.error


async def test_unconfirmed_variable_selection_fails(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    unconfirmed = VariableSelectionInfo(
        variable_selection_id=str(uuid.uuid4()),
        status="DRAFT",
        hazard_type="WILDFIRE",
        variables=(_NDVI, _WIND),
    )
    handler = RunPredictionHandler(
        db_session,
        _FakeVariableSelectionReader(unconfirmed),
        _FakeSamplingCampaignReader(1000),
        StubPredictionDataProvider(),
    )
    run = await handler.handle(
        RunPredictionCommand(
            tenant_id=str(tenant_id),
            assessment_id=str(uuid.uuid4()),
            variable_selection_id=str(uuid.uuid4()),
            sampling_campaign_id=str(uuid.uuid4()),
            method="PEARSON_CORRELATION",
            issued_by="analyst-1",
        )
    )
    assert run.status == PredictionRunStatus.FAILED
    assert "CONFIRMED" in run.error


async def test_missing_sampling_campaign_points_fails(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    handler = RunPredictionHandler(
        db_session,
        _FakeVariableSelectionReader(_confirmed_selection(_NDVI, _WIND)),
        _FakeSamplingCampaignReader(None),
        StubPredictionDataProvider(),
    )
    run = await handler.handle(
        RunPredictionCommand(
            tenant_id=str(tenant_id),
            assessment_id=str(uuid.uuid4()),
            variable_selection_id=str(uuid.uuid4()),
            sampling_campaign_id=str(uuid.uuid4()),
            method="PEARSON_CORRELATION",
            issued_by="analyst-1",
        )
    )
    assert run.status == PredictionRunStatus.FAILED

    outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "PredictionRun",
            OutboxEventModel.aggregate_id == str(run.id),
        )
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert "prediction.PredictionRunFailed" in event_types


async def test_re_running_the_same_configuration_creates_a_new_version(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    variable_selection_id = str(uuid.uuid4())
    handler = RunPredictionHandler(
        db_session,
        _FakeVariableSelectionReader(_confirmed_selection(_NDVI, _WIND)),
        _FakeSamplingCampaignReader(1000),
        StubPredictionDataProvider(),
    )
    command = RunPredictionCommand(
        tenant_id=str(tenant_id),
        assessment_id=assessment_id,
        variable_selection_id=variable_selection_id,
        sampling_campaign_id=str(uuid.uuid4()),
        method="PEARSON_CORRELATION",
        issued_by="analyst-1",
    )
    first = await handler.handle(command)
    second = await handler.handle(command)

    assert first.id != second.id
    assert second.version == first.version + 1
