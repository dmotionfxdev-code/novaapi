"""Composition-root glue wiring a real, Data-Acquisition-backed
``IndicatorInputProvider`` into the Analysis Engine — Sprint A's
replacement for ``StubIndicatorInputProvider``. Lives here, under
``api/``, deliberately outside ``contexts.analysis`` and
``contexts.data_acquisition`` — the import-linter's peer-independence
contract forbids either bounded context from importing the other
directly, so the only place code needing both contexts' repositories can
legally live is a neutral composition layer, the identical role
``api/workflow_stage_executors.py``/``api/prediction_ports.py`` already
play for their own peer pairs.

Real indicator inputs are sourced from a tenant's own catalogued
``Dataset``: the analyst uploads (via Data Acquisition's Local Upload
provider) a JSON payload shaped exactly like the raw inputs a leaf stage
needs (the same ``{indicator_code: value}``/nested-``asset_data`` shapes
``StubIndicatorInputProvider`` used to fabricate — FIRAS/WRRAS's
calculators are untouched by Sprint A, so they still expect precisely
those shapes), then catalogs it under the naming convention
``f"{hazard_type}:{stage_type}"`` (e.g. ``"FLOOD:HAZARD"``) so this
provider can find it with ``DatasetRepository.get_latest`` — the exact
per-tenant "latest version by name" lookup Sprint 7 already built.

This provider never fabricates a value: a missing dataset, a missing
originating ``AcquisitionJob``, or a payload that isn't valid JSON all
raise a clear, descriptive error rather than falling back to synthetic
data — the same "isolate an untrusted boundary" discipline
``RecordStageResultHandler`` already applies to a calculator's own
validation failures (it converts any exception raised here into a
``StageResult.FAILED``, triggering the Workflow Engine's existing retry
path, no new error-handling seam required).
"""

from __future__ import annotations

import base64
import json

from georisk.contexts.analysis.domain.value_objects import HazardType, StageType
from georisk.contexts.assessment.domain.value_objects import AssessmentId
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyAcquisitionJobRepository,
    SqlAlchemyDatasetRepository,
)
from georisk.db.session import Database


class MissingIndicatorDatasetError(LookupError):
    """No cataloged Data Acquisition dataset (or no recoverable raw
    payload on its originating AcquisitionJob) exists yet for a given
    (tenant, hazard_type, stage_type)."""


class InvalidIndicatorPayloadError(ValueError):
    """A resolved AcquisitionJob's raw payload could not be decoded into
    the flat/nested indicator-input shape the calculator expects."""


def _dataset_name(hazard_type: HazardType, stage_type: StageType) -> str:
    return f"{hazard_type.value}:{stage_type.value}"


class CompositionRootIndicatorInputProvider:
    """Implements Analysis's ``IndicatorInputProvider`` port using Data
    Acquisition's real ``Dataset``/``AcquisitionJob`` repositories
    directly — this data genuinely exists once a tenant uploads and
    catalogs it (Sprint 7/13), unlike ``StubIndicatorInputProvider``'s
    fixed, fabricated values."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def provide_raw_inputs(
        self, *, hazard_type: HazardType, stage_type: StageType, assessment_id: str
    ) -> dict:
        async with self._db.session() as session:
            assessment_repo = SqlAlchemyAssessmentRepository(session)
            assessment = await assessment_repo.get_by_id(AssessmentId.from_string(assessment_id))
            if assessment is None:
                raise MissingIndicatorDatasetError(f"Assessment {assessment_id} not found")
            tenant_id = assessment.tenant_id

        dataset_name = _dataset_name(hazard_type, stage_type)
        async with self._db.session() as session:
            dataset_repo = SqlAlchemyDatasetRepository(session)
            dataset = await dataset_repo.get_latest(tenant_id, dataset_name)
            if dataset is None:
                raise MissingIndicatorDatasetError(
                    f"No cataloged Data Acquisition dataset named {dataset_name!r} exists "
                    f"for this tenant — upload and catalog one (e.g. via Local Upload) "
                    f"before running the {stage_type.value.title()} stage of a "
                    f"{hazard_type.value.title()} assessment."
                )

            job_repo = SqlAlchemyAcquisitionJobRepository(session)
            jobs = await job_repo.list_by_tenant(tenant_id)
            job = next((j for j in jobs if j.dataset_id == dataset.id), None)
            if job is None:
                raise MissingIndicatorDatasetError(
                    f"Dataset {dataset_name!r} (id={dataset.id}) has no originating "
                    f"AcquisitionJob on record — its raw indicator payload cannot be "
                    f"recovered."
                )

            if job.extracted_features:
                return dict(job.extracted_features)

            if job.shapefile_attributes:
                # Sprint B: a genuinely-parsed Shapefile dataset's
                # ``raw_content_base64`` is the uploaded ZIP's bytes, not
                # JSON — its real indicator inputs are the first feature's
                # actual DBF attribute row instead (already extracted at
                # import time by ``infrastructure/shapefile_importer.py``,
                # never re-parsed here). No stub, no duplicate pipeline:
                # this is the exact same real provider Sprint A built,
                # now aware of a second real data shape alongside GEE's
                # ``extracted_features`` and Local Upload's JSON.
                return dict(job.shapefile_attributes)

            if not job.raw_content_base64:
                raise MissingIndicatorDatasetError(
                    f"AcquisitionJob {job.id} for dataset {dataset_name!r} has neither "
                    f"extracted features nor raw content to supply indicator inputs from."
                )

            try:
                decoded = base64.b64decode(job.raw_content_base64).decode("utf-8")
                payload = json.loads(decoded)
            except (ValueError, UnicodeDecodeError) as exc:
                raise InvalidIndicatorPayloadError(
                    f"AcquisitionJob {job.id}'s raw content for dataset {dataset_name!r} "
                    f"is not valid base64-encoded JSON: {exc}"
                ) from exc

            if not isinstance(payload, dict):
                raise InvalidIndicatorPayloadError(
                    f"AcquisitionJob {job.id}'s decoded payload for dataset "
                    f"{dataset_name!r} must be a JSON object mapping indicator codes to "
                    f"values, got {type(payload).__name__}"
                )
            return payload
