# API Deployment Guide — NOVA GeoRisk Platform

**Base URL (production)**: `https://novaapi.novarex.co.tz/api/v1`
**Health checks (unversioned, no `/api/v1` prefix)**: `https://novaapi.novarex.co.tz/health/live`, `/health/ready`
**Interactive docs**: `/api/v1/docs` and `/api/v1/openapi.json` are **only served when `ENVIRONMENT != production`** — they are intentionally hidden in this deployment. Use this document, or point a local/staging instance's `/docs` at the same codebase, for interactive exploration.

---

## Authentication

Every endpoint below requires a JWT bearer token unless explicitly marked **(public)**. Obtain one via:

```
POST /api/v1/auth/token
{ "email": "...", "password": "..." }
→ { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
```

Send it as `Authorization: Bearer <access_token>` on every subsequent request. Access tokens expire after `JWT_ACCESS_TOKEN_TTL_SECONDS` (default 8 hours); exchange the refresh token for a new one via:

```
POST /api/v1/auth/token/refresh
{ "refresh_token": "..." }
```

Each permission-gated route below lists its required `PermissionCode` — a caller's JWT carries their tenant's role's permission grants; a 403 means authenticated-but-not-authorized, a 401 means missing/invalid/expired token.

### Identity & Access endpoints

| Method & Path | Permission | Purpose |
|---|---|---|
| `POST /tenants` | *(public)* | Register a new tenant + owner account |
| `POST /auth/token` | *(public)* | Login — issue access + refresh token |
| `POST /auth/token/refresh` | *(public)* | Exchange refresh token for new access token |
| `POST /auth/logout` | *(public — body-supplied refresh token)* | Revoke a refresh token |
| `POST /auth/password-reset/request` | *(public)* | Request password-reset email (enumeration-safe) |
| `POST /auth/password-reset/confirm` | *(public)* | Confirm password reset with token |
| `GET /users/me` | authenticated | Get caller's own profile |
| `POST /users/me/password` | authenticated | Change own password |
| `POST /users` | `USER_INVITE` | Invite a new user into the tenant |
| `POST /users/invitations/accept` | *(public)* | Accept invitation, set password |
| `GET /users` | `USER_VIEW` | List users (paginated) |
| `GET /users/{user_id}` | `USER_VIEW` | Get a user by id |
| `POST /users/{user_id}/actions/change-role` | `USER_MANAGE_ROLE` | Change a user's role |
| `POST /users/{user_id}/actions/suspend` | `USER_MANAGE_STATUS` | Suspend a user |
| `POST /users/{user_id}/actions/reactivate` | `USER_MANAGE_STATUS` | Reactivate a user |
| `POST /users/{user_id}/actions/deactivate` | `USER_MANAGE_STATUS` | Deactivate a user |
| `GET /roles` | `ROLE_VIEW` | List role/permission catalog |

---

## Assessment APIs

Base path: `/assessments`

| Method & Path | Permission | Purpose |
|---|---|---|
| `POST /assessments` | `ASSESSMENT_MANAGE` | Create a new assessment |
| `GET /assessments` | `ASSESSMENT_VIEW` | List assessments (paginated, filter by status/hazard_type) |
| `GET /assessments/{assessment_id}` | `ASSESSMENT_VIEW` | Get an assessment |
| `POST /assessments/{assessment_id}/actions/mark-ready` | `ASSESSMENT_MANAGE` | DRAFT → READY |
| `POST /assessments/{assessment_id}/actions/start` | `ASSESSMENT_MANAGE` | READY → RUNNING |
| `POST /assessments/{assessment_id}/actions/validate` | `ASSESSMENT_MANAGE` | RUNNING → VALIDATED |
| `POST /assessments/{assessment_id}/actions/report` | `ASSESSMENT_MANAGE` | VALIDATED → REPORTED |
| `POST /assessments/{assessment_id}/actions/archive` | `ASSESSMENT_ARCHIVE` | → ARCHIVED |
| `POST /assessments/{assessment_id}/actions/cancel` | `ASSESSMENT_CANCEL` | → CANCELLED (with reason) |
| `POST /assessments/{assessment_id}/actions/start-workflow` | `ASSESSMENT_MANAGE` | Start workflow from a WorkflowTemplate |
| `POST /assessments/{assessment_id}/stages/{stage_type}/actions/execute` | `ASSESSMENT_MANAGE` | Manually execute/retry a workflow stage |
| `GET /assessments/{assessment_id}/workflow` | `ASSESSMENT_VIEW` | Get workflow/stage status |

## Workflow APIs

Base path: `/workflow-templates`

| Method & Path | Permission | Purpose |
|---|---|---|
| `POST /workflow-templates` | `WORKFLOW_TEMPLATE_MANAGE` | Create a workflow template (DAG of stages) |
| `POST /workflow-templates/{template_id}/actions/publish` | `WORKFLOW_TEMPLATE_MANAGE` | Publish a template |
| `GET /workflow-templates` | `WORKFLOW_TEMPLATE_VIEW` | List templates |
| `GET /workflow-templates/{template_id}` | `WORKFLOW_TEMPLATE_VIEW` | Get a template |

## Analysis APIs (FIRAS / WRRAS stage results)

Base path: `/assessments/{assessment_id}/stage-results`

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /assessments/{assessment_id}/stage-results` | `ASSESSMENT_VIEW` | List all StageResults (Hazard/Exposure/Vulnerability/Risk/Resilience) |
| `GET /assessments/{assessment_id}/stage-results/{stage_type}` | `ASSESSMENT_VIEW` | Get the latest StageResult for a stage type |

`stage_type` selects the hazard strategy transparently — the same endpoint serves FIRAS (flood) and WRRAS (wildfire) assessments; the strategy is resolved from the assessment's own `hazard_type`.

## Validation APIs

Base path: `/assessments/{assessment_id}/validations`

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /assessments/{assessment_id}/validations` | `VALIDATION_VIEW` | List validation runs |
| `GET /assessments/{assessment_id}/validations/{validation_run_id}` | `VALIDATION_VIEW` | Get a validation run |
| `POST /assessments/{assessment_id}/validations/actions/run` | `VALIDATION_MANAGE` | Run classification validation |
| `POST /assessments/{assessment_id}/validations/actions/run-regression` | `VALIDATION_MANAGE` | Run regression validation against a PredictionRun's fit stats (RMSE/MAE/MSE/R²/Adjusted R²) |

## Geospatial APIs

Base path: `/assessments/{assessment_id}`

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /assessments/{assessment_id}/aoi` | `ASSESSMENT_VIEW` | Get active Area of Interest |
| `POST /assessments/{assessment_id}/aoi` | `ASSESSMENT_MANAGE` | Define or revise an AOI (GeoJSON Polygon/MultiPolygon) |
| `GET /assessments/{assessment_id}/aoi/versions` | `ASSESSMENT_VIEW` | List AOI version history |
| `POST /assessments/{assessment_id}/sampling-campaigns` | `ASSESSMENT_MANAGE` | Configure a sampling campaign |
| `GET /assessments/{assessment_id}/sampling-campaigns` | `ASSESSMENT_VIEW` | List sampling campaigns |
| `GET /assessments/{assessment_id}/sampling-campaigns/{id}` | `ASSESSMENT_VIEW` | Get a sampling campaign |
| `POST /assessments/{assessment_id}/sampling-campaigns/{id}/actions/generate-points` | `ASSESSMENT_MANAGE` | Generate sample points |
| `GET /assessments/{assessment_id}/sampling-campaigns/{id}/points` | `ASSESSMENT_VIEW` | List generated sample points |

## Dataset APIs (Data Acquisition — catalog/registry)

Top-level catalog resources, not nested under assessments:

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /dataset-sources` | `DATASET_VIEW` | List dataset sources |
| `POST /dataset-sources` | `DATASET_MANAGE` | Register a dataset source (provider: CHIRPS/ERA5/MODIS/SENTINEL/LANDSAT/.../GOOGLE_EARTH_ENGINE/USGS/NASA/COPERNICUS/LOCAL_UPLOAD/...) |
| `GET /datasets` | `DATASET_VIEW` | Dataset catalog (filter by type / MLR-ready / correlation-ready) |
| `POST /datasets` | `DATASET_MANAGE` | Catalog a new dataset |
| `GET /datasets/{dataset_id}` | `DATASET_VIEW` | Get a dataset |
| `GET /datasets/by-name/{name}/versions` | `DATASET_VIEW` | List a dataset's version/provenance history |
| `POST /datasets/by-name/{name}/actions/revise` | `DATASET_MANAGE` | Revise a dataset (new version, supersedes previous) |
| `GET /predictor-variables` | `DATASET_VIEW` | List predictor variables |
| `POST /predictor-variables` | `DATASET_MANAGE` | Register a predictor variable |
| `POST /variable-selections` | `DATASET_MANAGE` | Create a named variable selection |
| `GET /variable-selections/{id}` | `DATASET_VIEW` | Get a variable selection |
| `POST /variable-selections/{id}/actions/confirm` | `DATASET_MANAGE` | Confirm a variable selection |

## Acquisition APIs (Sprint 13/14 — AcquisitionJob pipeline)

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /acquisition-jobs` | `DATASET_VIEW` | List acquisition jobs |
| `POST /acquisition-jobs` | `DATASET_MANAGE` | Schedule an acquisition job |
| `GET /acquisition-jobs/{id}` | `DATASET_VIEW` | Get an acquisition job |
| `POST /acquisition-jobs/{id}/actions/execute` | `DATASET_MANAGE` | Execute a scheduled job (fetch → validate → catalog) |

**Scheduling a job** (`POST /acquisition-jobs`) body fields: `provider` (`LOCAL_UPLOAD`/`USGS`/`NASA`/`COPERNICUS`/`GOOGLE_EARTH_ENGINE`), `source_reference`, `format` (`GEOJSON`/`CSV`/`GEOTIFF`/`SHAPEFILE`/`JSON`), `dataset_source_id`, `declared_crs`, `raw_content_base64` (Local Upload only). GEE jobs additionally require `remote_sensing_source` and `aoi_id` — see Remote Sensing APIs below.

## Remote Sensing APIs (Sprint 14 — same `/acquisition-jobs` endpoints, GEE-specific fields)

Google Earth Engine jobs use the identical `POST /acquisition-jobs` / `.../actions/execute` endpoints above with these additional request fields:

| Field | Values | Notes |
|---|---|---|
| `remote_sensing_source` | `SENTINEL_1` / `SENTINEL_2` / `LANDSAT` / `MODIS` / `CHIRPS` / `ERA5` | Required when `provider=GOOGLE_EARTH_ENGINE` |
| `aoi_id` | a real Geospatial `AreaOfInterest` id | **Required** for GEE jobs (hard requirement — unbounded exports are refused) |
| `temporal_start` / `temporal_end` | ISO 8601 datetimes | Acquisition window |
| `comparison_temporal_start` / `comparison_temporal_end` | ISO 8601 datetimes | Pre/post window, required only if requesting `DNBR` |
| `requested_preprocessing` | list of `CLOUD_MASKING`/`ATMOSPHERIC_CORRECTION`/`RADIOMETRIC_CORRECTION`/`REPROJECTION`/`AOI_CLIPPING` | Steps not applicable to the chosen source are honestly skipped, not faked |
| `requested_indices` | list of `NDVI`/`EVI`/`SAVI`/`NDWI`/`LST`/`NBR`/`DNBR`/`SPEI` | Response includes `extracted_features` (computed) and `skipped_features` (name → reason) |

**This requires a real Google Cloud service account with the Earth Engine API enabled** (`GEE_SERVICE_ACCOUNT_EMAIL`/`GEE_SERVICE_ACCOUNT_PRIVATE_KEY`/`GEE_PROJECT_ID` in `.env`) — without it, execution fails immediately and honestly with `"Google Earth Engine is not configured"`, not a fabricated result.

## Prediction APIs

Base path: `/assessments/{assessment_id}/predictions`

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /assessments/{assessment_id}/predictions` | `ASSESSMENT_VIEW` | List prediction runs |
| `GET /assessments/{assessment_id}/predictions/{id}` | `ASSESSMENT_VIEW` | Get a prediction run |
| `POST /assessments/{assessment_id}/predictions/actions/run` | `ASSESSMENT_MANAGE` | Run correlation (Pearson/Spearman/Kendall) or MLR against a confirmed VariableSelection + SamplingCampaign |

## Reporting APIs

Base path: `/assessments/{assessment_id}/reports`, plus `/dashboard/reports`

| Method & Path | Permission | Purpose |
|---|---|---|
| `GET /assessments/{assessment_id}/reports` | `ASSESSMENT_VIEW` | List reports |
| `GET /assessments/{assessment_id}/reports/latest` | `ASSESSMENT_VIEW` | Get latest report |
| `GET /assessments/{assessment_id}/reports/{report_id}` | `ASSESSMENT_VIEW` | Get a report |
| `POST /assessments/{assessment_id}/reports/actions/generate` | `ASSESSMENT_MANAGE` | Generate a report snapshot (Assessment + StageResult + Prediction + Dataset + Validation) |
| `POST /assessments/{assessment_id}/reports/{report_id}/actions/finalize` | `ASSESSMENT_MANAGE` | Finalize a report (immutable thereafter) |
| `GET /dashboard/reports` | `ASSESSMENT_VIEW` | Tenant-wide dashboard report projections |

## Notification APIs

| Method & Path | Permission | Purpose |
|---|---|---|
| `POST /alert-rules` | `ALERT_RULE_MANAGE` | Create an alert rule (e.g. `FRI > 0.6`) |
| `GET /alert-rules` | `ALERT_RULE_VIEW` | List alert rules |
| `GET /alert-rules/{id}` | `ALERT_RULE_VIEW` | Get an alert rule |
| `POST /alert-rules/{id}/actions/update-threshold` | `ALERT_RULE_MANAGE` | Update threshold |
| `POST /alert-rules/{id}/actions/activate` | `ALERT_RULE_MANAGE` | Activate |
| `POST /alert-rules/{id}/actions/deactivate` | `ALERT_RULE_MANAGE` | Deactivate |
| `POST /notification-subscriptions` | `NOTIFICATION_SUBSCRIPTION_MANAGE` | Create own subscription |
| `GET /notification-subscriptions` | `NOTIFICATION_SUBSCRIPTION_VIEW` | List subscriptions |
| `GET /notification-subscriptions/{id}` | `NOTIFICATION_SUBSCRIPTION_VIEW` | Get a subscription |
| `POST /notification-subscriptions/{id}/actions/activate` | `NOTIFICATION_SUBSCRIPTION_MANAGE` | Activate |
| `POST /notification-subscriptions/{id}/actions/deactivate` | `NOTIFICATION_SUBSCRIPTION_MANAGE` | Deactivate |
| `POST /assessments/{assessment_id}/notifications/actions/evaluate-alert-rules` | `NOTIFICATION_MANAGE` | Trigger the Early Warning Engine for an assessment |
| `GET /assessments/{assessment_id}/notifications` | `NOTIFICATION_VIEW` | List notifications for an assessment |
| `GET /notifications` | `NOTIFICATION_VIEW` | Tenant-wide notification history |

Delivery channels: In-App (always real), Email (real SMTP if `SMTP_HOST` configured, else honest failure), SMS (always an honest "not implemented" stub — no real gateway integrated).

## Dashboard APIs

Base path: `/dashboards` — all read-only (`GET`), all require `DASHBOARD_VIEW`:

| Path | Purpose |
|---|---|
| `/dashboards/workspace/{assessment_id}` | Cross-context assessment workspace projection |
| `/dashboards/executive` | Tenant-wide executive summary |
| `/dashboards/firas` | Flood hazard dashboard |
| `/dashboards/wrras` | Wildfire hazard dashboard |
| `/dashboards/prediction` | Prediction dashboard |
| `/dashboards/validation` | Validation dashboard |
| `/dashboards/alerts` | Alert dashboard |
| `/dashboards/datasets` | Dataset dashboard |

---

## Health Checks (for load balancers / uptime monitors)

- `GET /health/live` — liveness only, no dependency checks, always fast.
- `GET /health/ready` — pings PostgreSQL and Redis; returns `503` if either is unreachable. Point cPanel/uptime monitoring at this one for a meaningful check, and `deploy.sh` uses it after every deploy.

## Error Response Format

Every error follows RFC 7807 Problem Details:
```json
{
  "type": "https://docs.firas.dev/errors/<ErrorClassName>",
  "title": "<ErrorClassName>",
  "status": 404,
  "detail": "human-readable message",
  "instance": "/api/v1/...",
  "traceId": "...",
  "errors": []
}
```
Status codes: `400` validation, `401` not authenticated, `403` authenticated but not authorized, `404` not found (including cross-tenant references — see `SECURITY_REVIEW.md`), `409` illegal state transition/concurrency conflict, `422` guard/precondition rejected.
