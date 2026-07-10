"""Data Acquisition API — top-level catalog/registry resources
(``/dataset-sources``, ``/datasets``, ``/predictor-variables``,
``/variable-selections``), not nested under assessments (these are
tenant-level catalog resources, the same "reference, not owned" shape
API Resource Model §20 gives ``dataset-sources`` for the fuller GIS
Engine design). Every route is a thin adapter: parse request -> build a
command/query -> invoke the one handler/query that owns it -> map to a
response schema — no business logic in this file.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.data_acquisition.application.commands import (
    CatalogDatasetCommand,
    ConfirmVariableSelectionCommand,
    CreateVariableSelectionCommand,
    ExecuteAcquisitionJobCommand,
    RegisterDatasetSourceCommand,
    RegisterPredictorVariableCommand,
    ReviseDatasetCommand,
    ScheduleAcquisitionJobCommand,
)
from georisk.contexts.data_acquisition.application.handlers import (
    CatalogDatasetHandler,
    ConfirmVariableSelectionHandler,
    CreateVariableSelectionHandler,
    ExecuteAcquisitionJobHandler,
    RegisterDatasetSourceHandler,
    RegisterPredictorVariableHandler,
    ReviseDatasetHandler,
    ScheduleAcquisitionJobHandler,
)
from georisk.contexts.data_acquisition.application.ports import AoiReader, ProviderRegistry
from georisk.contexts.data_acquisition.application.queries import (
    GetAcquisitionJobQuery,
    GetDatasetCatalogQuery,
    GetDatasetQuery,
    GetVariableSelectionQuery,
    ListAcquisitionJobsQuery,
    ListDatasetSourcesQuery,
    ListDatasetVersionsQuery,
    ListPredictorVariablesQuery,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionJobId,
    DatasetId,
    DatasetReadinessTag,
    VariableSelectionId,
)
from georisk.contexts.data_acquisition.interface.schemas import (
    AcquisitionJobListResponse,
    AcquisitionJobResponse,
    CatalogDatasetRequest,
    CreateVariableSelectionRequest,
    DatasetListResponse,
    DatasetResponse,
    DatasetSourceListResponse,
    DatasetSourceResponse,
    PredictorVariableListResponse,
    PredictorVariableResponse,
    RegisterDatasetSourceRequest,
    RegisterPredictorVariableRequest,
    ReviseDatasetRequest,
    ScheduleAcquisitionJobRequest,
    VariableSelectionResponse,
)
from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import get_current_claims, require_permission
from georisk.db.session import get_session
from georisk.rate_limiting import rate_limit_by_tenant

router = APIRouter(tags=["data-acquisition"])


async def _tenant_id_from_claims(
    claims: Annotated[AccessTokenClaims, Depends(get_current_claims)],
) -> str:
    return str(claims.tenant_id)


def _provider_registry(request: Request) -> ProviderRegistry:
    return request.app.state.acquisition_provider_registry


def _aoi_reader(request: Request) -> AoiReader:
    return request.app.state.acquisition_aoi_reader


@router.get("/dataset-sources", response_model=DatasetSourceListResponse)
async def list_dataset_sources(
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatasetSourceListResponse:
    sources = await ListDatasetSourcesQuery(session).handle(claims.tenant_id)
    return DatasetSourceListResponse.from_domain(sources)


@router.post("/dataset-sources", response_model=DatasetSourceResponse, status_code=201)
async def register_dataset_source(
    body: RegisterDatasetSourceRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatasetSourceResponse:
    handler = RegisterDatasetSourceHandler(session)
    source = await handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(claims.tenant_id),
            name=body.name,
            provider=body.provider,
            description=body.description,
            issued_by=str(claims.user_id),
        )
    )
    return DatasetSourceResponse.from_domain(source)


@router.get("/datasets", response_model=DatasetListResponse)
async def get_dataset_catalog(
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
    dataset_type: str | None = Query(default=None),
    mlr_ready: bool = Query(default=False),
    correlation_ready: bool = Query(default=False),
) -> DatasetListResponse:
    readiness = None
    if mlr_ready:
        readiness = DatasetReadinessTag.MLR_READY
    elif correlation_ready:
        readiness = DatasetReadinessTag.CORRELATION_READY
    datasets = await GetDatasetCatalogQuery(session).handle(
        claims.tenant_id, dataset_type=dataset_type, readiness=readiness
    )
    return DatasetListResponse.from_domain(datasets)


@router.post("/datasets", response_model=DatasetResponse, status_code=201)
async def catalog_dataset(
    body: CatalogDatasetRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatasetResponse:
    handler = CatalogDatasetHandler(session)
    dataset = await handler.handle(
        CatalogDatasetCommand(
            tenant_id=str(claims.tenant_id),
            dataset_source_id=body.dataset_source_id,
            name=body.name,
            dataset_type=body.dataset_type,
            source=body.source,
            provider=body.provider,
            acquisition_date=body.acquisition_date,
            crs=body.crs,
            spatial_coverage=body.spatial_coverage,
            temporal_coverage_start=body.temporal_coverage_start.isoformat(),
            temporal_coverage_end=body.temporal_coverage_end.isoformat(),
            processing_method=body.processing_method,
            spatial_resolution_m=body.spatial_resolution_m,
            temporal_resolution=body.temporal_resolution,
            model_used=body.model_used,
            is_mlr_ready=body.is_mlr_ready,
            is_correlation_ready=body.is_correlation_ready,
            issued_by=str(claims.user_id),
        )
    )
    return DatasetResponse.from_domain(dataset)


@router.get("/datasets/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: str,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatasetResponse:
    dataset = await GetDatasetQuery(session).handle(
        claims.tenant_id, DatasetId.from_string(dataset_id)
    )
    return DatasetResponse.from_domain(dataset)


@router.get("/datasets/by-name/{name}/versions", response_model=DatasetListResponse)
async def list_dataset_versions(
    name: str,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatasetListResponse:
    """Also serves "Dataset Provenance Tracking" — each returned version
    carries its own full ``provenance`` lineage."""
    versions = await ListDatasetVersionsQuery(session).handle(claims.tenant_id, name)
    return DatasetListResponse.from_domain(versions)


@router.post("/datasets/by-name/{name}/actions/revise", response_model=DatasetResponse)
async def revise_dataset(
    name: str,
    body: ReviseDatasetRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DatasetResponse:
    handler = ReviseDatasetHandler(session)
    dataset = await handler.handle(
        ReviseDatasetCommand(
            tenant_id=str(claims.tenant_id),
            dataset_name=name,
            dataset_type=body.dataset_type,
            source=body.source,
            provider=body.provider,
            acquisition_date=body.acquisition_date,
            crs=body.crs,
            spatial_coverage=body.spatial_coverage,
            temporal_coverage_start=body.temporal_coverage_start.isoformat(),
            temporal_coverage_end=body.temporal_coverage_end.isoformat(),
            processing_method=body.processing_method,
            description=body.description,
            spatial_resolution_m=body.spatial_resolution_m,
            temporal_resolution=body.temporal_resolution,
            model_used=body.model_used,
            is_mlr_ready=body.is_mlr_ready,
            is_correlation_ready=body.is_correlation_ready,
            issued_by=str(claims.user_id),
        )
    )
    return DatasetResponse.from_domain(dataset)


@router.get("/predictor-variables", response_model=PredictorVariableListResponse)
async def list_predictor_variables(
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
    category: str | None = Query(default=None),
) -> PredictorVariableListResponse:
    variables = await ListPredictorVariablesQuery(session).handle(
        claims.tenant_id, category=category
    )
    return PredictorVariableListResponse.from_domain(variables)


@router.post("/predictor-variables", response_model=PredictorVariableResponse, status_code=201)
async def register_predictor_variable(
    body: RegisterPredictorVariableRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PredictorVariableResponse:
    handler = RegisterPredictorVariableHandler(session)
    variable = await handler.handle(
        RegisterPredictorVariableCommand(
            tenant_id=str(claims.tenant_id),
            name=body.name,
            code=body.code,
            category=body.category,
            variable_role=body.variable_role,
            data_type=body.data_type,
            unit=body.unit,
            value_min=body.value_min,
            value_max=body.value_max,
            is_required_for_mlr=body.is_required_for_mlr,
            linked_dataset_id=body.linked_dataset_id,
            issued_by=str(claims.user_id),
        )
    )
    return PredictorVariableResponse.from_domain(variable)


@router.post("/variable-selections", response_model=VariableSelectionResponse, status_code=201)
async def create_variable_selection(
    body: CreateVariableSelectionRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VariableSelectionResponse:
    handler = CreateVariableSelectionHandler(session)
    selection = await handler.handle(
        CreateVariableSelectionCommand(
            tenant_id=str(claims.tenant_id),
            name=body.name,
            hazard_type=body.hazard_type,
            selected_variable_ids=tuple(body.selected_variable_ids),
            issued_by=str(claims.user_id),
        )
    )
    return VariableSelectionResponse.from_domain(selection)


@router.get(
    "/variable-selections/{variable_selection_id}", response_model=VariableSelectionResponse
)
async def get_variable_selection(
    variable_selection_id: str,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VariableSelectionResponse:
    selection = await GetVariableSelectionQuery(session).handle(
        claims.tenant_id, VariableSelectionId.from_string(variable_selection_id)
    )
    return VariableSelectionResponse.from_domain(selection)


@router.post(
    "/variable-selections/{variable_selection_id}/actions/confirm",
    response_model=VariableSelectionResponse,
)
async def confirm_variable_selection(
    variable_selection_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VariableSelectionResponse:
    handler = ConfirmVariableSelectionHandler(session)
    selection = await handler.handle(
        ConfirmVariableSelectionCommand(
            tenant_id=str(claims.tenant_id), variable_selection_id=variable_selection_id
        )
    )
    return VariableSelectionResponse.from_domain(selection)


@router.get("/acquisition-jobs", response_model=AcquisitionJobListResponse)
async def list_acquisition_jobs(
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AcquisitionJobListResponse:
    jobs = await ListAcquisitionJobsQuery(session).handle(claims.tenant_id)
    return AcquisitionJobListResponse.from_domain(jobs)


@router.post(
    "/acquisition-jobs",
    response_model=AcquisitionJobResponse,
    status_code=201,
    dependencies=[
        Depends(rate_limit_by_tenant("upload", tenant_id_dependency=_tenant_id_from_claims))
    ],
)
async def schedule_acquisition_job(
    body: ScheduleAcquisitionJobRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AcquisitionJobResponse:
    handler = ScheduleAcquisitionJobHandler(session)
    job = await handler.handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(claims.tenant_id),
            provider=body.provider,
            source_reference=body.source_reference,
            format=body.format,
            dataset_source_id=body.dataset_source_id,
            declared_crs=body.declared_crs,
            raw_content_base64=body.raw_content_base64,
            remote_sensing_source=body.remote_sensing_source,
            aoi_id=body.aoi_id,
            temporal_start=body.temporal_start.isoformat() if body.temporal_start else None,
            temporal_end=body.temporal_end.isoformat() if body.temporal_end else None,
            comparison_temporal_start=(
                body.comparison_temporal_start.isoformat()
                if body.comparison_temporal_start
                else None
            ),
            comparison_temporal_end=(
                body.comparison_temporal_end.isoformat() if body.comparison_temporal_end else None
            ),
            requested_preprocessing=tuple(body.requested_preprocessing),
            requested_indices=tuple(body.requested_indices),
            issued_by=str(claims.user_id),
        )
    )
    return AcquisitionJobResponse.from_domain(job)


@router.get("/acquisition-jobs/{acquisition_job_id}", response_model=AcquisitionJobResponse)
async def get_acquisition_job(
    acquisition_job_id: str,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AcquisitionJobResponse:
    job = await GetAcquisitionJobQuery(session).handle(
        claims.tenant_id, AcquisitionJobId.from_string(acquisition_job_id)
    )
    return AcquisitionJobResponse.from_domain(job)


@router.post(
    "/acquisition-jobs/{acquisition_job_id}/actions/execute",
    response_model=AcquisitionJobResponse,
)
async def execute_acquisition_job(
    acquisition_job_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.DATASET_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    provider_registry: Annotated[ProviderRegistry, Depends(_provider_registry)],
    aoi_reader: Annotated[AoiReader, Depends(_aoi_reader)],
) -> AcquisitionJobResponse:
    handler = ExecuteAcquisitionJobHandler(session, provider_registry, aoi_reader)
    job = await handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(claims.tenant_id),
            acquisition_job_id=acquisition_job_id,
            issued_by=str(claims.user_id),
        )
    )
    return AcquisitionJobResponse.from_domain(job)
