"""Shared Sprint A test helper: catalogs real Data Acquisition datasets so
``CompositionRootIndicatorInputProvider`` (production wiring, no stub) can
feed a FIRAS/WRRAS workflow real data when driven through the full HTTP
stack (``create_app()``'s real lifespan).

Every payload below is copied verbatim from
``StubIndicatorInputProvider``'s fixed dicts (``contexts/analysis/
application/ports.py``) — Sprint A retired the stub from runtime wiring,
but every pre-existing HTTP test that asserted an exact stub-derived
indicator value (e.g. ``flood_hazard_index == 0.565``) still holds
unchanged, because the *same* numbers now arrive as a real, tenant-
uploaded, cataloged dataset instead of a hardcoded object in the call
path — proving the real seam without rewriting every assertion in this
test suite.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, date, datetime

from georisk.contexts.data_acquisition.domain.entities import AcquisitionJob, Dataset, DatasetSource
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionFormat,
    DataProvider,
    DatasetMetadata,
    DatasetType,
    ProcessingMethod,
)
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyAcquisitionJobRepository,
    SqlAlchemyDatasetRepository,
    SqlAlchemyDatasetSourceRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.session import Database
from georisk.shared_kernel.types import DateRange

_FIRAS_STAGE_PAYLOADS = {
    "HAZARD": {
        "rainfall_index": 0.65,
        "water_level_index": 0.55,
        "slope_index": 0.40,
        "drainage_index": 0.50,
        "land_use_index": 0.60,
        "soil_index": 0.70,
    },
    "EXPOSURE": {
        "asset_data": {
            "population": {"total": 10000, "exposed": 4000},
            "houses": {"total": 2000, "exposed": 900},
            "roads": {"total": 150, "exposed": 60},
            "schools": {"total": 20, "exposed": 8},
            "hospitals": {"total": 5, "exposed": 2},
            "power_infrastructure": {"total": 30, "exposed": 10},
            "agricultural_land": {"total": 500, "exposed": 200},
            "livestock": {"total": 3000, "exposed": 1200},
        }
    },
    "VULNERABILITY": {
        "population_density": 0.60,
        "elderly_population": 0.30,
        "children_population": 0.35,
        "disability_status": 0.20,
        "education_level": 0.50,
        "poverty_level": 0.40,
        "housing_quality": 0.40,
        "building_materials": 0.50,
        "infrastructure_condition": 0.45,
        "household_income": 0.30,
        "livelihood_dependence": 0.55,
        "crop_dependence": 0.60,
        "emergency_plans": 0.50,
        "community_training": 0.40,
        "evacuation_preparedness": 0.45,
        "resource_availability": 0.50,
        "warning_timeliness": 0.60,
        "warning_accuracy": 0.55,
        "warning_accessibility": 0.50,
        "flood_awareness": 0.65,
        "previous_experience": 0.70,
        "understanding_of_risk": 0.60,
        "response_speed": 0.50,
        "relief_distribution": 0.45,
        "coordination": 0.55,
        "economic_recovery": 0.40,
        "infrastructure_recovery": 0.45,
        "social_recovery": 0.50,
    },
}

_WRRAS_STAGE_PAYLOADS = {
    "HAZARD": {
        "temperature": 0.70,
        "wind_speed": 0.55,
        "drought_index": 0.60,
        "fuel_load": 0.65,
        "vegetation_density": 0.60,
        "slope": 0.40,
        "human_activity": 0.35,
        "rainfall": 0.30,
    },
    "EXPOSURE": {
        "population_exposed": 3500,
        "population_total": 10000,
        "infrastructure_exposed": 800,
        "infrastructure_total": 2000,
        "environmental_exposed": 150,
        "environmental_total": 500,
        "economic_exposed": 400,
        "economic_total": 1000,
    },
    "VULNERABILITY": {
        "poverty_rate": 0.45,
        "literacy_level": 0.65,
        "age_dependency_ratio": 0.40,
        "disability_ratio": 0.15,
        "building_flammability": 0.55,
        "roof_material_index": 0.50,
        "building_density": 0.45,
        "access_road_quality": 0.60,
        "fuel_accumulation_index": 0.60,
        "ecosystem_sensitivity": 0.50,
        "forest_condition": 0.55,
        "tourism_dependence": 0.35,
        "forest_livelihood_dependence": 0.50,
        "agricultural_dependence": 0.45,
        "firebreak_coverage": 0.45,
        "community_training": 0.40,
        "fire_committee_presence": 0.35,
        "equipment_availability": 0.40,
        "warning_timeliness": 0.55,
        "warning_accessibility": 0.50,
        "warning_accuracy": 0.55,
        "fire_awareness": 0.60,
        "fire_prevention_knowledge": 0.50,
        "evacuation_knowledge": 0.45,
        "response_time_index": 0.50,
        "suppression_efficiency": 0.45,
        "resource_adequacy": 0.40,
        "forest_restoration": 0.40,
        "economic_recovery": 0.35,
        "community_recovery": 0.45,
    },
    "FIRE_REGIME": {
        "observation_years": 10.0,
        "fire_count": 15,
        "area_km2": 250.0,
        "repeated_burned_pixels": 800,
        "total_burned_pixels": 2000,
        "burned_area_ha": 1500.0,
        "first_fire_date": "2015-06-01",
        "last_fire_date": "2025-09-15",
        "high_severity_fires": 4,
        "temperature": 0.70,
        "wind_speed": 0.55,
        "relative_humidity": 0.40,
        "fuel_load": 0.65,
        "drought_index": 0.60,
        "human_activity": 0.35,
    },
    "BURN_OCCURRENCE_PROBABILITY": {
        "temperature": 0.70,
        "wind_speed": 0.55,
        "relative_humidity": 0.40,
        "fuel_load": 0.65,
        "drought_index": 0.60,
        "human_activity": 0.35,
        "historical_fire_index": 0.50,
    },
    "BURN_SEVERITY": {
        "nir_pre": 0.45,
        "swir_pre": 0.20,
        "nir_post": 0.25,
        "swir_post": 0.30,
        "red_pre": 0.08,
        "red_post": 0.18,
    },
}


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


async def _catalog(
    db: Database,
    tenant_id: TenantId,
    name: str,
    payload: dict,
    *,
    previous: Dataset | None = None,
) -> Dataset:
    async with db.session() as session:
        if previous is None:
            source, _ = DatasetSource.register(
                tenant_id=tenant_id,
                name=f"Local Upload — {name}",
                provider=DataProvider.LOCAL_UPLOAD,
                description="",
                created_by="test-seed",
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
            requested_by="test-seed",
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
                catalogued_by="test-seed",
            )
        else:
            dataset, _ = Dataset.revise(
                previous=previous,
                metadata=_dataset_metadata(name),
                readiness=frozenset(),
                description="Re-uploaded with new observations",
                catalogued_by="test-seed",
            )
            previous.mark_superseded()
            await dataset_repo.save(previous)
        await dataset_repo.save(dataset)

        job.complete(dataset_id=dataset.id)
        await job_repo.save(job)
        await session.commit()
    return dataset


async def seed_firas_indicator_datasets(db: Database, tenant_id: TenantId) -> None:
    """Catalogs FLOOD:HAZARD / FLOOD:EXPOSURE / FLOOD:VULNERABILITY —
    every leaf stage a standard FIRAS workflow template needs."""
    for stage, payload in _FIRAS_STAGE_PAYLOADS.items():
        await _catalog(db, tenant_id, f"FLOOD:{stage}", payload)


async def seed_wrras_indicator_datasets(db: Database, tenant_id: TenantId) -> None:
    """Catalogs every WRRAS leaf stage's dataset (WILDFIRE:HAZARD /
    EXPOSURE / VULNERABILITY / FIRE_REGIME / BURN_OCCURRENCE_PROBABILITY /
    BURN_SEVERITY) — a superset covering both the minimal and the full
    optional-stage WRRAS workflow templates this test suite builds."""
    for stage, payload in _WRRAS_STAGE_PAYLOADS.items():
        await _catalog(db, tenant_id, f"WILDFIRE:{stage}", payload)


def _run_standalone(seed_coro) -> None:  # noqa: ANN001
    """Runs a seeding coroutine (built against its own fresh ``Database``)
    on its own independent event loop via ``asyncio.run`` — deliberately
    NOT ``app.state.db`` from an HTTP test's ``TestClient``, whose engine
    is bound to TestClient's own AnyIO-portal event loop; mixing the two
    raises "Future attached to a different loop". A second, independent
    connection is safe here regardless: this only ever writes
    newly-committed rows a fresh session on the SAME real Postgres
    instance sees immediately, no shared-transaction assumptions."""
    asyncio.run(seed_coro)


async def _seed_firas_standalone(database_url: str, tenant_id: str) -> None:
    db = Database(database_url)
    try:
        await seed_firas_indicator_datasets(db, TenantId.from_string(tenant_id))
    finally:
        await db.dispose()


async def _seed_wrras_standalone(database_url: str, tenant_id: str) -> None:
    db = Database(database_url)
    try:
        await seed_wrras_indicator_datasets(db, TenantId.from_string(tenant_id))
    finally:
        await db.dispose()


def seed_firas_indicator_datasets_sync(database_url: str, tenant_id: str) -> None:
    _run_standalone(_seed_firas_standalone(database_url, tenant_id))


def seed_wrras_indicator_datasets_sync(database_url: str, tenant_id: str) -> None:
    _run_standalone(_seed_wrras_standalone(database_url, tenant_id))


async def _seed_real_hazard_observations(
    db: Database, tenant_id: TenantId, hazard: str, observations: list[dict]
) -> None:
    """For Prediction/Reporting API tests: creates one real Assessment +
    completed HAZARD ``StageResult`` per entry in ``observations`` (each a
    dict of extra/overriding fields layered on the hazard's required
    HAZARD indicator codes — e.g. ``{"ndvi": 0.2, "wind_speed": 0.55}``),
    all sharing one ``{hazard}:HAZARD`` Dataset lineage (revised once per
    entry). Gives ``CompositionRootPredictionDataProvider`` genuine
    per-assessment historical rows to read for whatever variable codes a
    test registers, instead of ``StubPredictionDataProvider``'s on-demand
    synthetic fabrication. ``hazard`` is ``"FLOOD"`` or ``"WILDFIRE"``.
    """
    # Local imports: this module is a test-only helper, not part of the
    # production composition root — importing api.* modules here (rather
    # than at module scope) keeps this file's own import graph obviously
    # test-scoped.
    from georisk.api.analysis_ports import CompositionRootIndicatorInputProvider
    from georisk.api.workflow_stage_executors import AnalysisStageExecutor
    from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
    from georisk.contexts.analysis.domain.value_objects import HazardType as AnalysisHazardType
    from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy
    from georisk.contexts.analysis.strategies.wrras.strategy import WRRASHazardStrategy
    from georisk.contexts.assessment.domain.entities import Assessment
    from georisk.contexts.assessment.domain.value_objects import (
        HazardType as AssessmentHazardType,
    )
    from georisk.contexts.assessment.domain.workflow_value_objects import (
        StageType as AssessmentStageType,
    )
    from georisk.contexts.assessment.infrastructure.repositories import (
        SqlAlchemyAssessmentRepository,
    )
    from georisk.contexts.identity.domain.value_objects import UserId

    assessment_hazard_type = AssessmentHazardType[hazard]
    base_payload = (_FIRAS_STAGE_PAYLOADS if hazard == "FLOOD" else _WRRAS_STAGE_PAYLOADS)["HAZARD"]

    registry = StrategyRegistry()
    if hazard == "FLOOD":
        registry.register(AnalysisHazardType.FLOOD, FIRASHazardStrategy())
    else:
        registry.register(AnalysisHazardType.WILDFIRE, WRRASHazardStrategy())
    executor = AnalysisStageExecutor(db, registry, CompositionRootIndicatorInputProvider(db))

    # A "{hazard}:HAZARD" dataset may already exist for this tenant (e.g.
    # a prior seed_firas_indicator_datasets_sync call for the same test's
    # main workflow assessment) — revise that same lineage rather than
    # attempting a second independent Dataset.catalog() under the same
    # (tenant, name), which DatasetRepository.get_latest can't
    # disambiguate between (both would sit at version 1).
    async with db.session() as session:
        previous_dataset = await SqlAlchemyDatasetRepository(session).get_latest(
            tenant_id, f"{hazard}:HAZARD"
        )

    for i, extra in enumerate(observations):
        payload = {**base_payload, **extra}
        previous_dataset = await _catalog(
            db, tenant_id, f"{hazard}:HAZARD", payload, previous=previous_dataset
        )

        async with db.session() as session:
            assessment, _ = Assessment.create(
                tenant_id=tenant_id,
                name=f"Prediction Seed Observation {i}",
                hazard_type=assessment_hazard_type,
                created_by=UserId.new(),
            )
            assessment.mark_ready(changed_by="test-seed")
            await SqlAlchemyAssessmentRepository(session).save(assessment)
            await session.commit()

        outcome = await executor.execute(
            AssessmentStageType.HAZARD, assessment_id=str(assessment.id)
        )
        assert outcome.success, outcome.error


async def seed_real_wildfire_hazard_observations(
    db: Database, tenant_id: TenantId, observations: list[dict]
) -> None:
    await _seed_real_hazard_observations(db, tenant_id, "WILDFIRE", observations)


async def seed_real_firas_hazard_observations(
    db: Database, tenant_id: TenantId, observations: list[dict]
) -> None:
    await _seed_real_hazard_observations(db, tenant_id, "FLOOD", observations)


async def _seed_real_observations_standalone(
    database_url: str, tenant_id: str, hazard: str, observations: list[dict]
) -> None:
    db = Database(database_url)
    try:
        await _seed_real_hazard_observations(
            db, TenantId.from_string(tenant_id), hazard, observations
        )
    finally:
        await db.dispose()


def seed_real_wildfire_hazard_observations_sync(
    database_url: str, tenant_id: str, observations: list[dict]
) -> None:
    _run_standalone(
        _seed_real_observations_standalone(database_url, tenant_id, "WILDFIRE", observations)
    )


def seed_real_firas_hazard_observations_sync(
    database_url: str, tenant_id: str, observations: list[dict]
) -> None:
    _run_standalone(
        _seed_real_observations_standalone(database_url, tenant_id, "FLOOD", observations)
    )
