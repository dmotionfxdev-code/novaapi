"""Composition-root glue wiring Data Acquisition's ``VariableSelection``/
``PredictorVariable`` registry and Geospatial's ``SamplingCampaign`` into
Prediction as read-only ports. Lives here, under ``api/``, deliberately
outside ``contexts.prediction``, ``contexts.data_acquisition``, and
``contexts.geospatial`` — the import-linter's peer-independence contract
forbids any of these bounded contexts from importing another, so the
only place code needing all three contexts' repositories can legally
live is a neutral composition layer, the identical role
``api/workflow_stage_executors.py`` already plays for Assessment/
Analysis/Validation.

Each reader opens its own session per call (``Database.session()``)
rather than sharing the caller's request-scoped session — the same
"manages its own transaction boundary" pattern
``AnalysisStageExecutor``/``ValidationStageExecutor`` already established,
since these are read-only lookups against a *different* aggregate than
whatever transaction is currently open on the caller's session.
"""

from __future__ import annotations

from georisk.contexts.data_acquisition.domain.value_objects import VariableSelectionId
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyPredictorVariableRepository,
    SqlAlchemyVariableSelectionRepository,
)
from georisk.contexts.geospatial.domain.value_objects import (
    SamplingCampaignId,
    SamplingCampaignStatus,
)
from georisk.contexts.geospatial.infrastructure.repositories import (
    SqlAlchemySamplingCampaignRepository,
)
from georisk.contexts.prediction.application.ports import (
    PredictorVariableInfo,
    VariableSelectionInfo,
)
from georisk.db.session import Database


class CompositionRootVariableSelectionReader:
    """Implements Prediction's ``VariableSelectionReader`` port using
    Data Acquisition's real repositories directly — this data genuinely
    exists (Sprint 7 built it), unlike ``StubPredictionDataProvider``'s
    synthetic observation values."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_selection(
        self, *, tenant_id: str, variable_selection_id: str
    ) -> VariableSelectionInfo | None:
        async with self._db.session() as session:
            selection_repo = SqlAlchemyVariableSelectionRepository(session)
            selection = await selection_repo.get_by_id(
                VariableSelectionId.from_string(variable_selection_id)
            )
            if selection is None or str(selection.tenant_id) != tenant_id:
                return None

            variable_repo = SqlAlchemyPredictorVariableRepository(session)
            variables = []
            for variable_id in selection.selected_variable_ids:
                variable = await variable_repo.get_by_id(variable_id)
                if variable is not None:
                    variables.append(
                        PredictorVariableInfo(
                            predictor_variable_id=str(variable.id),
                            code=variable.code,
                            name=variable.name,
                            variable_role=variable.variable_role.value,
                            value_min=variable.value_min,
                            value_max=variable.value_max,
                        )
                    )

            return VariableSelectionInfo(
                variable_selection_id=str(selection.id),
                status=selection.status.value,
                hazard_type=selection.hazard_type,
                variables=tuple(variables),
            )


class CompositionRootSamplingCampaignReader:
    """Implements Prediction's ``SamplingCampaignReader`` port using
    Geospatial's real ``SamplingCampaign`` repository directly."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_sample_count(
        self, *, tenant_id: str, sampling_campaign_id: str
    ) -> int | None:
        async with self._db.session() as session:
            repo = SqlAlchemySamplingCampaignRepository(session)
            campaign = await repo.get_by_id(SamplingCampaignId.from_string(sampling_campaign_id))
            if campaign is None or str(campaign.tenant_id) != tenant_id:
                return None
            if campaign.status is not SamplingCampaignStatus.GENERATED:
                return None
            return len(campaign.sample_points)
