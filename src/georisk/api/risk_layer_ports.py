"""Sprint C — composition-root glue wiring a real, Data-Acquisition-backed
Risk Layer Generation port into the Analysis Engine. Lives here, under
``api/``, deliberately outside ``contexts.analysis`` and
``contexts.data_acquisition`` — the import-linter's peer-independence
contract forbids either bounded context from importing the other
directly, so the only place code needing both contexts' repositories can
legally live is a neutral composition layer, the identical role
``api/analysis_ports.py``/``api/prediction_ports.py`` already play for
their own peer pairs.

**Geometry source naming convention**: the tenant's Dataset cataloged
under ``f"{hazard_type}:RISK"`` (e.g. ``"FLOOD:RISK"``, ``"WILDFIRE:RISK"``)
is the real, genuinely-uploaded (Sprint B) Shapefile this hazard type's
risk layers are generated against — deliberately NOT reusing any of
Sprint A's own indicator-input dataset slots (``f"{hazard_type}:HAZARD"``/
``"EXPOSURE"``/``"VULNERABILITY"``/etc.). Those must supply FIRAS's/
WRRAS's own flat/nested indicator vocabulary exactly, and — as Sprint B's
own BURN_SEVERITY-only finding showed — most of that vocabulary exceeds a
classic DBF field name's 10-character limit, so a Shapefile can almost
never BE one of those datasets without silently breaking indicator
parsing. The RISK stage-type slot is provably free of that risk: RISK is
a DERIVED stage (``HazardStrategy.input_dependencies`` declares it reads
prior ``StageResult``s, never raw inputs — confirmed in
``RecordStageResultHandler._gather_inputs``: the ``IndicatorInputProvider``
branch is only ever reached when a stage has NO declared dependencies),
so nothing in this platform ever calls
``CompositionRootIndicatorInputProvider.provide_raw_inputs()`` for a
``f"{hazard_type}:RISK"``-named dataset — it is safe, uncontested space
for Sprint C to claim as "the real geometry to visualize this hazard's
calculated risk against."

A missing or non-Shapefile-sourced geometry dataset is an expected,
benign outcome — ``generate_if_possible`` silently returns without
generating a layer rather than raising, so a RISK stage's own successful
completion (the actual Analysis output) is never blocked or failed by the
absence of an auxiliary spatial artifact.
"""

from __future__ import annotations

import base64

from georisk.contexts.analysis.application.commands import GenerateRiskLayerCommand
from georisk.contexts.analysis.application.handlers import GenerateRiskLayerHandler
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyAcquisitionJobRepository,
    SqlAlchemyDatasetRepository,
)
from georisk.contexts.data_acquisition.infrastructure.shapefile_importer import read_all_features
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.session import Database


def _geometry_dataset_name(hazard_type: str) -> str:
    return f"{hazard_type}:RISK"


class CompositionRootRiskLayerService:
    """Implements Analysis's ``RiskLayerGenerationPort`` using Data
    Acquisition's real ``Dataset``/``AcquisitionJob`` repositories
    directly, then calling Analysis's own ``GenerateRiskLayerHandler`` —
    composition-root code is exempt from the peer-independence contract
    by design, the same reasoning ``CompositionRootIndicatorInputProvider``
    already relies on."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def generate_if_possible(
        self,
        *,
        tenant_id: str,
        assessment_id: str,
        hazard_type: str,
        stage_result_id: str,
        issued_by: str,
    ) -> None:
        tenant = TenantId.from_string(tenant_id)
        dataset_name = _geometry_dataset_name(hazard_type)

        async with self._db.session() as session:
            dataset = await SqlAlchemyDatasetRepository(session).get_latest(tenant, dataset_name)
            if dataset is None:
                return

            jobs = await SqlAlchemyAcquisitionJobRepository(session).list_by_tenant(tenant)
            job = next((j for j in jobs if j.dataset_id == dataset.id), None)
            if (
                job is None
                or job.shapefile_geometry_type is None
                or not job.raw_content_base64
            ):
                # Not Shapefile-sourced (or the originating job can't be
                # recovered) — no genuine geometries to build a layer
                # from. Benign: this hazard type simply has no spatial
                # risk layer yet, not an error.
                return
            geometry_type = job.shapefile_geometry_type
            crs = job.shapefile_crs or "EPSG:4326"
            raw_zip = base64.b64decode(job.raw_content_base64)

        shapefile_features = read_all_features(raw_zip)
        features = [
            {"geometry": feature.geometry, "properties": feature.properties}
            for feature in shapefile_features
        ]

        async with self._db.session() as session:
            await GenerateRiskLayerHandler(session).handle(
                GenerateRiskLayerCommand(
                    tenant_id=tenant_id,
                    assessment_id=assessment_id,
                    stage_result_id=stage_result_id,
                    dataset_id=str(dataset.id),
                    geometry_type=geometry_type,
                    crs=crs,
                    features=features,
                    issued_by=issued_by,
                )
            )
