"""FastAPI application factory.

A factory (``create_app()``), not a module-level singleton, so tests can
construct isolated app instances — each with its own :class:`Database`
attached to ``app.state.db`` (Sprint 0 Review finding #14 / Remediation
#14), rather than sharing a process-global engine.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

import redis.asyncio as redis_asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from georisk.api.dashboard_ports import (
    CompositionRootAssessmentReader as CompositionRootDashboardAssessmentReader,
)
from georisk.api.dashboard_ports import (
    CompositionRootDatasetReader,
    CompositionRootNotificationReader,
    CompositionRootReportReader,
)
from georisk.api.dashboard_ports import (
    CompositionRootPredictionReader as CompositionRootDashboardPredictionReader,
)
from georisk.api.dashboard_ports import (
    CompositionRootStageResultReader as CompositionRootDashboardStageResultReader,
)
from georisk.api.dashboard_ports import (
    CompositionRootValidationReader as CompositionRootDashboardValidationReader,
)
from georisk.api.data_acquisition_ports import CompositionRootAoiReader
from georisk.api.middleware.error_handling import register_exception_handlers
from georisk.api.middleware.tenant_context import TenantContextMiddleware
from georisk.api.middleware.tracing import TraceContextMiddleware
from georisk.api.notification_ports import (
    CompositionRootAlertMetricReader,
)
from georisk.api.notification_ports import (
    CompositionRootAssessmentReader as CompositionRootNotificationAssessmentReader,
)
from georisk.api.prediction_ports import (
    CompositionRootSamplingCampaignReader,
    CompositionRootVariableSelectionReader,
)
from georisk.api.reporting_ports import (
    CompositionRootAssessmentReader,
    CompositionRootDatasetCatalogReader,
    CompositionRootPredictionReader,
    CompositionRootStageResultReader,
    CompositionRootValidationReader,
)
from georisk.api.routes.health import router as health_router
from georisk.api.validation_ports import CompositionRootRegressionValidationSubjectResolver
from georisk.api.workflow_stage_executors import (
    AnalysisStageExecutor,
    CompositeStageExecutor,
    ValidationStageExecutor,
)
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.value_objects import HazardType as AnalysisHazardType
from georisk.contexts.analysis.interface.routes import router as stage_result_router
from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy
from georisk.contexts.analysis.strategies.wrras.strategy import WRRASHazardStrategy
from georisk.contexts.assessment.application.workflow_engine import ImmediateSuccessStageExecutor
from georisk.contexts.assessment.domain.workflow_value_objects import StageType
from georisk.contexts.assessment.interface.routes import router as assessment_router
from georisk.contexts.assessment.interface.workflow_template_routes import (
    router as workflow_template_router,
)
from georisk.contexts.dashboard.interface.routes import router as dashboard_view_router
from georisk.contexts.data_acquisition.application.ports import (
    LocalUploadProvider,
    ProviderRegistry,
)
from georisk.contexts.data_acquisition.domain.value_objects import DataProvider
from georisk.contexts.data_acquisition.infrastructure.gee_connector import (
    GoogleEarthEngineProvider,
)
from georisk.contexts.data_acquisition.infrastructure.providers import HttpAcquisitionProvider
from georisk.contexts.data_acquisition.interface.routes import (
    router as data_acquisition_router,
)
from georisk.contexts.geospatial.interface.routes import router as geospatial_router
from georisk.contexts.identity.interface.routes_auth import router as identity_auth_router
from georisk.contexts.identity.interface.routes_catalog import router as identity_catalog_router
from georisk.contexts.identity.interface.routes_tenants import router as identity_tenants_router
from georisk.contexts.identity.interface.routes_users import router as identity_users_router
from georisk.contexts.notification.application.ports import (
    InAppNotificationChannel,
    UnconfiguredSmsNotificationChannel,
)
from georisk.contexts.notification.domain.value_objects import NotificationChannelType
from georisk.contexts.notification.infrastructure.channels import SmtpEmailNotificationChannel
from georisk.contexts.notification.interface.routes import (
    alert_rule_router,
    notification_history_router,
    notification_router,
)
from georisk.contexts.notification.interface.routes import (
    subscription_router as notification_subscription_router,
)
from georisk.contexts.prediction.application.ports import StubPredictionDataProvider
from georisk.contexts.prediction.interface.routes import router as prediction_router
from georisk.contexts.reporting.interface.routes import (
    dashboard_router,
)
from georisk.contexts.reporting.interface.routes import (
    router as report_router,
)
from georisk.contexts.validation.interface.routes import router as validation_router
from georisk.db.session import Database
from georisk.observability.logging import configure_logging
from georisk.observability.tracing import configure_tracing, instrument_app, shutdown_tracing
from georisk.settings import Settings, get_settings


def _make_lifespan(settings: Settings) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Returns a lifespan context manager bound to the *specific* settings
    instance `create_app()` was called with — not the process-wide
    ``get_settings()`` cache.

    An earlier version of this file had ``lifespan`` as a plain module-level
    function that called ``get_settings()`` internally, silently ignoring
    whatever ``settings`` was passed into ``create_app()``. That defeated
    the entire point of ``create_app(settings=...)`` accepting an explicit
    settings object: two app instances built with two different
    ``database_url`` values still ended up sharing one engine, pointed at
    whatever ``get_settings()``'s cache happened to hold — exactly the
    test-isolation failure Sprint 0 Review finding #14 / Remediation #14
    was written to close. Caught by `tests/integration/test_db_isolation.py`
    actually failing during Sprint 0 validation, not assumed correct from
    reading the code.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings)
        configure_tracing(settings)

        app.state.db = Database(settings.database_url, pool_size=settings.db_pool_size)
        app.state.redis = redis_asyncio.from_url(settings.redis_url, decode_responses=True)

        # Sprint 5: registering FIRASHazardStrategy is the platform-facing
        # step the brief's success test is built around ("only a strategy
        # registration should be required") — everything else in this
        # block already existed before this sprint touched anything.
        # Sprint 6 registers WRRASHazardStrategy the same way — the second
        # independent proof of the same claim.
        strategy_registry = StrategyRegistry()
        strategy_registry.register(AnalysisHazardType.FLOOD, FIRASHazardStrategy())
        strategy_registry.register(AnalysisHazardType.WILDFIRE, WRRASHazardStrategy())
        analysis_executor = AnalysisStageExecutor(app.state.db, strategy_registry)

        # Sprint 4: the VALIDATION stage runs Validation's own
        # RunValidationCommand pipeline; Sprint 5: Hazard/Exposure/
        # Vulnerability/Risk/Resilience run the Analysis Engine's
        # RecordStageResultCommand pipeline via the registry above.
        # Composed here — the composition root — because
        # contexts.assessment, contexts.validation, and contexts.analysis
        # may not import each other directly (import-linter's peer-
        # independence contract); see
        # `api/workflow_stage_executors.py`'s module docstring.
        app.state.stage_executor = CompositeStageExecutor(
            default=ImmediateSuccessStageExecutor(),
            overrides={
                StageType.HAZARD: analysis_executor,
                StageType.EXPOSURE: analysis_executor,
                StageType.VULNERABILITY: analysis_executor,
                StageType.RISK: analysis_executor,
                StageType.RESILIENCE: analysis_executor,
                StageType.VALIDATION: ValidationStageExecutor(app.state.db),
            },
        )

        # Sprint 8: Prediction's read-only ports into Data Acquisition's
        # VariableSelection/PredictorVariable registry and Geospatial's
        # SamplingCampaign — composed here for the identical
        # peer-independence reason as the stage executors above; see
        # `api/prediction_ports.py`'s module docstring.
        app.state.prediction_variable_selection_reader = CompositionRootVariableSelectionReader(
            app.state.db
        )
        app.state.prediction_sampling_campaign_reader = CompositionRootSamplingCampaignReader(
            app.state.db
        )
        app.state.prediction_data_provider = StubPredictionDataProvider()

        # Sprint 9: Reporting's read-only ports into Assessment (+
        # Geospatial's AOI/SamplingCampaign), Analysis Engine's
        # StageResult, Prediction's PredictionRun, Data Acquisition's
        # Dataset catalog, and Validation's ValidationRun — composed here
        # for the identical peer-independence reason as every reader
        # above; see `api/reporting_ports.py`'s module docstring.
        app.state.reporting_assessment_reader = CompositionRootAssessmentReader(app.state.db)
        app.state.reporting_stage_result_reader = CompositionRootStageResultReader(app.state.db)
        app.state.reporting_prediction_reader = CompositionRootPredictionReader(app.state.db)
        app.state.reporting_dataset_catalog_reader = CompositionRootDatasetCatalogReader(
            app.state.db
        )
        app.state.reporting_validation_reader = CompositionRootValidationReader(app.state.db)

        # Sprint 10: Validation's read-only port into Prediction's real
        # PredictionRun regression fit — composed here for the identical
        # peer-independence reason as every reader above; see
        # `api/validation_ports.py`'s module docstring.
        app.state.regression_validation_subject_resolver = (
            CompositionRootRegressionValidationSubjectResolver(app.state.db)
        )

        # Sprint 11: Notification's read-only ports into Assessment,
        # Analysis Engine, Prediction, and Validation (the Early Warning
        # Engine's metric resolution) — composed here for the identical
        # peer-independence reason as every reader above; see
        # `api/notification_ports.py`'s module docstring. Channel map:
        # IN_APP is genuinely real (persistence IS delivery), Email is a
        # real smtplib-backed channel gated on `settings.smtp_host` being
        # configured, SMS is Sprint 11 requirement #8's honest
        # not-a-real-gateway abstraction.
        app.state.notification_assessment_reader = CompositionRootNotificationAssessmentReader(
            app.state.db
        )
        app.state.notification_alert_metric_reader = CompositionRootAlertMetricReader(
            app.state.db
        )
        app.state.notification_channels = {
            NotificationChannelType.IN_APP: InAppNotificationChannel(),
            NotificationChannelType.EMAIL: SmtpEmailNotificationChannel(settings),
            NotificationChannelType.SMS: UnconfiguredSmsNotificationChannel(),
        }

        # Sprint 12: Dashboard's read-only ports into every peer context it
        # visualizes — composed here for the identical peer-independence
        # reason as every reader above; see `api/dashboard_ports.py`'s
        # module docstring. No writable state of its own (Sprint 12's
        # "projection/read-model approach only").
        app.state.dashboard_assessment_reader = CompositionRootDashboardAssessmentReader(
            app.state.db
        )
        app.state.dashboard_stage_result_reader = CompositionRootDashboardStageResultReader(
            app.state.db
        )
        app.state.dashboard_prediction_reader = CompositionRootDashboardPredictionReader(
            app.state.db
        )
        app.state.dashboard_validation_reader = CompositionRootDashboardValidationReader(
            app.state.db
        )
        app.state.dashboard_notification_reader = CompositionRootNotificationReader(app.state.db)
        app.state.dashboard_dataset_reader = CompositionRootDatasetReader(app.state.db)
        app.state.dashboard_report_reader = CompositionRootReportReader(app.state.db)

        # Sprint 13: Data Acquisition's Provider Registry — mirrors
        # Sprint 5/6's StrategyRegistry wiring above exactly. USGS/NASA/
        # Copernicus share one HttpAcquisitionProvider class, each
        # configured from its own Settings fields (base_url=None means
        # "not configured" — the same honest-immediate-failure discipline
        # as Sprint 11's SmtpEmailNotificationChannel).
        #
        # Sprint 14: GEE is now a real connector (superseding Sprint 13's
        # interface-only stub), gated on its own Settings fields the same
        # way — and, since it's the first data_acquisition provider that
        # genuinely needs to read another context (Geospatial's AOI
        # geometry), this is also the first sprint that needs a
        # composition-root reader for this context (`acquisition_aoi_
        # reader`, implementing `AoiReader`).
        acquisition_provider_registry = ProviderRegistry()
        acquisition_provider_registry.register(
            DataProvider.GOOGLE_EARTH_ENGINE,
            GoogleEarthEngineProvider(
                service_account_email=settings.gee_service_account_email,
                service_account_private_key=settings.gee_service_account_private_key,
                project_id=settings.gee_project_id,
            ),
        )
        acquisition_provider_registry.register(DataProvider.LOCAL_UPLOAD, LocalUploadProvider())
        acquisition_provider_registry.register(
            DataProvider.USGS,
            HttpAcquisitionProvider(
                provider_name="USGS",
                base_url=settings.usgs_api_base_url,
                api_key=settings.usgs_api_key,
                timeout_seconds=settings.acquisition_http_timeout_seconds,
            ),
        )
        acquisition_provider_registry.register(
            DataProvider.NASA,
            HttpAcquisitionProvider(
                provider_name="NASA",
                base_url=settings.nasa_api_base_url,
                api_key=settings.nasa_api_key,
                timeout_seconds=settings.acquisition_http_timeout_seconds,
            ),
        )
        acquisition_provider_registry.register(
            DataProvider.COPERNICUS,
            HttpAcquisitionProvider(
                provider_name="Copernicus",
                base_url=settings.copernicus_api_base_url,
                api_key=settings.copernicus_api_key,
                timeout_seconds=settings.acquisition_http_timeout_seconds,
            ),
        )
        app.state.acquisition_provider_registry = acquisition_provider_registry
        app.state.acquisition_aoi_reader = CompositionRootAoiReader(app.state.db)

        yield

        await app.state.redis.aclose()
        await app.state.db.dispose()
        shutdown_tracing()

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    # Sprint 0 Review finding #17 / Remediation #17: `docs_url` alone does
    # not hide the API surface — `openapi_url` is the underlying data source
    # it reads from, and stays fetchable by anyone if left unconditional.
    # Decision made explicitly here, not defaulted into: gate both behind
    # the same non-production check.
    expose_docs = not settings.is_production

    app = FastAPI(
        title="NOVA GeoRisk Platform API",
        version="0.1.0",
        openapi_url="/api/v1/openapi.json" if expose_docs else None,
        docs_url="/api/v1/docs" if expose_docs else None,
        redoc_url=None,
        lifespan=_make_lifespan(settings),
    )

    # Middleware registration order matters. Starlette applies middleware in
    # LIFO order — the LAST one added via add_middleware() becomes the
    # OUTERMOST layer, executing first on the way in and last on the way
    # out. We want trace context established before anything else touches
    # the request (Implementation Bootstrap §3: every log line and error
    # response from this point on is expected to carry a traceId), then
    # tenant context, with CORS innermost. Registration order is therefore
    # the reverse of execution order: innermost (CORS) added first, outermost
    # (Trace) added last. FastAPI's own exception-handling layer sits inside
    # all of these regardless of this order, so a response it produces still
    # flows back out through every middleware below.
    app.add_middleware(CORSMiddleware, **_cors_kwargs(settings))
    app.add_middleware(TenantContextMiddleware)
    app.add_middleware(TraceContextMiddleware)

    register_exception_handlers(app)
    instrument_app(app)

    app.include_router(health_router)

    # Identity context (Roadmap Sprint 1) — the first set of domain routes
    # in the API. Versioned per API Resource Model §10: every resource
    # route lives under /api/v1, health checks deliberately don't (they're
    # infrastructure, not a versioned resource contract).
    app.include_router(identity_tenants_router, prefix="/api/v1")
    app.include_router(identity_auth_router, prefix="/api/v1")
    app.include_router(identity_users_router, prefix="/api/v1")
    app.include_router(identity_catalog_router, prefix="/api/v1")

    # Assessment context (Roadmap Sprint 2) — the platform's aggregate root.
    app.include_router(assessment_router, prefix="/api/v1")

    # Workflow Engine (Roadmap Sprint 3) — same "Assessment Orchestration"
    # bounded context as Assessment itself; a separate router only because
    # WorkflowTemplate's routes live under their own /workflow-templates
    # collection rather than nested under /assessments.
    app.include_router(workflow_template_router, prefix="/api/v1")

    # Validation context (Roadmap Sprint 7, brought forward to this sprint
    # per explicit instruction) — an independent peer bounded context,
    # nested under /assessments/{id}/validations purely as a URL-path
    # convenience (API Resource Model §18); its router never imports
    # anything from contexts.assessment.
    app.include_router(validation_router, prefix="/api/v1")

    # Analysis Engine (Roadmap Sprint 4/5, brought forward to this sprint
    # per explicit instruction) — an independent peer bounded context,
    # nested under /assessments/{id}/stage-results purely as a URL-path
    # convenience; its router never imports anything from
    # contexts.assessment.
    app.include_router(stage_result_router, prefix="/api/v1")

    # Geospatial context (Sprint 7) — an independent peer bounded context,
    # AOI/SamplingCampaign nested under /assessments/{id}/... purely as a
    # URL-path convenience (API Resource Model §20); its router never
    # imports anything from contexts.assessment.
    app.include_router(geospatial_router, prefix="/api/v1")

    # Data Acquisition context (Sprint 7) — an independent peer bounded
    # context; its catalog/registry resources (dataset-sources, datasets,
    # predictor-variables, variable-selections) are top-level, not
    # assessment-nested, matching API Resource Model §20's "reference, not
    # owned" shape for DatasetSource.
    app.include_router(data_acquisition_router, prefix="/api/v1")

    # Prediction context (Sprint 8) — an independent peer bounded
    # context, nested under /assessments/{id}/predictions purely as a
    # URL-path convenience; its router never imports anything from
    # contexts.data_acquisition or contexts.geospatial.
    app.include_router(prediction_router, prefix="/api/v1")

    # Reporting context (Sprint 9) — an independent peer bounded context,
    # nested under /assessments/{id}/reports purely as a URL-path
    # convenience, plus a tenant-level /dashboard/reports route for the
    # Dashboard Projection Layer; its router never imports anything from
    # contexts.assessment, contexts.analysis, contexts.prediction,
    # contexts.data_acquisition, or contexts.validation.
    app.include_router(report_router, prefix="/api/v1")
    app.include_router(dashboard_router, prefix="/api/v1")

    # Notification & Early Warning context (Sprint 11) — an independent
    # peer bounded context. AlertRule/NotificationSubscription are
    # top-level catalog resources (not assessment-nested); the Early
    # Warning Engine's trigger and per-assessment history are nested under
    # /assessments/{id}/notifications purely as a URL-path convenience,
    # plus a tenant-level /notifications route for Notification History.
    # Its router never imports anything from contexts.assessment,
    # contexts.analysis, contexts.prediction, or contexts.validation.
    app.include_router(alert_rule_router, prefix="/api/v1")
    app.include_router(notification_subscription_router, prefix="/api/v1")
    app.include_router(notification_router, prefix="/api/v1")
    app.include_router(notification_history_router, prefix="/api/v1")

    # Dashboard & Visualization context (Sprint 12) — an independent peer
    # bounded context, entirely read-only ("Use projection/read-model
    # approach only"); nested under /dashboards (plural, deliberately
    # distinct from Reporting's own /dashboard/reports route from Sprint
    # 9). Its router never imports anything from contexts.assessment,
    # contexts.analysis, contexts.prediction, contexts.validation,
    # contexts.reporting, contexts.notification, or
    # contexts.data_acquisition.
    app.include_router(dashboard_view_router, prefix="/api/v1")

    return app


def _cors_kwargs(settings: Settings) -> dict[str, object]:
    return {
        "allow_origins": settings.cors_allowed_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*", "X-Trace-Id"],
        "expose_headers": ["X-Trace-Id"],
    }


app = create_app()
