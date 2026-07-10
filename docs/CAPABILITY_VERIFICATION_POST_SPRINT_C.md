# Capability Verification — Post Sprint A / B / C

**Scope**: full re-verification of platform capability status against the CURRENT codebase,
run fresh today against a newly created PostgreSQL instance (no state carried forward from
prior sprint reports). Supersedes the module table in `PRODUCTION_READINESS_REPORT.md` /
`RELEASE_CERTIFICATION.md` (v1.2, pre-Sprint-A), which is now stale on three rows (Data
Acquisition, Analysis/FIRAS-WRRAS, Prediction) — those rows are corrected below with evidence.

No prior document in this repository used a literal VERIFIED/PARTIAL/NOT IMPLEMENTED
label — `grep -rl "VERIFIED\|PARTIAL\|NOT IMPLEMENTED" docs/` returns nothing. This document
is the first to use that exact scheme; it treats v1.2's "Completed Modules" table as the
baseline being carried forward and corrected, not a document being literally "re-run."

**Status legend**
- **VERIFIED** — real implementation, no stub/placeholder in the runtime path, proven today by source citation + passing test(s) + live HTTP evidence where applicable.
- **PARTIAL** — real implementation exists but has a known, honest, documented boundary (e.g. requires external credentials, vector-only, no per-pixel granularity).
- **NOT IMPLEMENTED** — an honest stub/placeholder still stands in the runtime path, or the capability does not exist at all.

---

## 0. Fresh validation run performed for this document

| Check | Result |
|---|---|
| Full test suite (fresh PostgreSQL, migrations `0000_baseline`→`0018_risk_layer`, 19 revisions, single linear chain) | **533 passed, 1 skipped, 0 failed** (skip = real GEE connectivity, no live GCP creds in this environment — expected) |
| `mypy src/` | Clean — 0 errors, **275** source files (271 at v1.2; +4 from Sprints A/B/C) |
| `lint-imports` | **4/4 contracts kept** (peer-context independence, identity-as-shared-kernel, domain purity, GIS/GEE-confined-to-data_acquisition-infrastructure) |
| `ruff check .` | Clean on all real source/test files (2 findings only in a throwaway Python-3.10 compat shim added to this scratch validation harness itself, not part of the repository) |
| Live server boot (`uvicorn` + real Postgres, `ENVIRONMENT=production`) | `GET /health/live` → `200`; `GET /health/ready` → `database: ok`, `redis: error` (expected — no Redis in this sandbox, matches documented risk); `GET /api/v1/docs` → `404` (correctly hidden in production) |
| Live end-to-end HTTP flow (fresh tenant → login → real FIRAS indicator uploads → real Shapefile geometry upload → workflow template → assessment → `start-workflow` → `VALIDATED`) | All real HTTP calls, real Postgres, no `TestClient` shortcuts — see §3 for the actual response bodies |

This is fresh evidence gathered for this document, not a restatement of the Sprint A/B/C
reports' own (already-real) validation runs.

---

## 1. Capability Matrix

| # | Capability | Status | Evidence |
|---|---|---|---|
| 1 | Identity & Access Management (Tenant/User/Role/Permission, JWT + refresh, Argon2id, RBAC) | **VERIFIED** | Unchanged since v1.2; exercised live in §3 (tenant registration → login → bearer-token-authorized calls all succeeded) |
| 2 | Assessment lifecycle (DRAFT→READY→RUNNING→VALIDATED→REPORTED→ARCHIVED, +CANCELLED) | **VERIFIED** | Unchanged since v1.2; live run in §3 reached `VALIDATED` over real HTTP |
| 3 | Workflow Engine (template DAG, cycle detection, stage orchestration) | **VERIFIED** | Unchanged since v1.2; live template with 4 stages (HAZARD/EXPOSURE/VULNERABILITY/RISK) drove a real run in §3 |
| 4 | Validation (classification metrics: accuracy/precision/recall/F1/kappa/ROC-AUC) | **VERIFIED** | Unchanged since v1.2; formulas untouched by Sprints A/B/C per their explicit constraints |
| 5 | FIRAS strategy (flood Hazard/Exposure/Vulnerability/Risk/Resilience, EWM weighting) | **VERIFIED** | Formulas untouched; now fed by real data (row 16) instead of a stub — live run in §3 computed a genuine `risk_index = 0.1101` from uploaded indicator values |
| 6 | WRRAS strategy (wildfire WRI, WVI/WII, Fire Regime/BOP/Burn Severity) | **VERIFIED** | Formulas untouched; `tests/integration/_sprint_a_seed_helpers.py` seeds real WRRAS datasets analogous to row 16 |
| 7 | Geospatial (AreaOfInterest, SamplingCampaign) | **VERIFIED** | Unchanged since v1.2 |
| 8 | Dataset Management (`DatasetSource`/`Dataset`/`PredictorVariable`/`VariableSelection`, provenance, versioning) | **VERIFIED** | Unchanged since v1.2; extended (not replaced) by Sprint B's `Dataset.revise()` duplicate-upload fix |
| 9 | Prediction (Pearson/Spearman/Kendall correlation + Multiple Linear Regression) | **VERIFIED** | Formulas untouched; now fed by real `StageResult` history (row 17) instead of a stub |
| 10 | Reporting (generation/finalization, cross-context snapshot aggregation) | **VERIFIED** | Unchanged since v1.2 |
| 11 | Regression Validation (RMSE/MAE/MSE/R²/Adjusted R²) | **VERIFIED** | Unchanged since v1.2 |
| 12 | Notification & Early Warning (AlertRule, threshold evaluation, In-App/Email channels) | **VERIFIED** | Unchanged since v1.2 |
| 12b | SMS notification channel | **NOT IMPLEMENTED** | `UnconfiguredSmsNotificationChannel` — still an honest stub, deliberately unretired; untouched by any of Sprints A/B/C |
| 13 | Dashboard & Visualization (8 read-model projections) | **VERIFIED** | Unchanged since v1.2 |
| 14 | Data Acquisition core (`AcquisitionJob` lifecycle, `ProviderRegistry`, Local Upload / USGS / NASA / Copernicus) | **VERIFIED** | Unchanged since v1.2 |
| 15 | GEE & Remote Sensing (real Earth Engine connector, spectral indices, AOI processing) | **PARTIAL** | Real connector code is genuine (not a stub), but functionally inert without live GCP credentials — 1 test still honestly skips for this reason; unchanged since v1.2, this is a credentials gap, not a code gap |
| 16 | **Analysis real-data integration (Sprint A)** — Analysis stages fed by genuine tenant-uploaded/cataloged datasets, never fabricated | **VERIFIED** | `CompositionRootIndicatorInputProvider` (`src/georisk/api/analysis_ports.py:63`, `provide_raw_inputs` at line 73) resolves the tenant's cataloged `Dataset` named `f"{hazard_type}:{stage_type}"` via `DatasetRepository.get_latest`, raises `MissingIndicatorDatasetError` (line 48) / `InvalidIndicatorPayloadError` (line 54) rather than fabricating data if absent/malformed. Wired in `api/app.py`, no stub import remains anywhere in production wiring. Proven live in §3: real HAZARD/EXPOSURE/VULNERABILITY JSON uploads → real `risk_index = 0.1101` computed from those exact uploaded numbers |
| 17 | **Prediction real-data integration (Sprint A)** — Prediction fed by real completed-stage history | **VERIFIED** | `CompositionRootPredictionDataProvider` (`src/georisk/api/prediction_ports.py:114`, `generate_observations` at line 128) reads real `StageResultRepository.list_all_indicators_by_assessment`, merging every COMPLETE stage's snapshot inputs; `tests/integration/test_sprint_a_real_data_integration.py` (8 tests, all passing in the 533 total) |
| 18 | **Real ESRI Shapefile import (Sprint B)** — genuine `.shp/.shx/.dbf/.prj` parsing, not header/magic-byte sniffing | **VERIFIED** | `infrastructure/shapefile_importer.py`: `parse_shapefile_archive` (line 116) and `read_all_features` (line 201) use `pyogrio`+`shapely` for real CRS/geometry/attribute extraction (`SHAPEFILE_IMPORTER_VERSION = "pyogrio-shapefile-importer-v1"`, line 63); `domain/validation.py:127`'s `validate_shapefile_archive` does pure-stdlib ZIP-completeness checking (domain layer stays library-free); confined behind `data_acquisition`'s infrastructure layer per the import-linter contract (still 4/4 kept, §0). Proven live in §3: a real 2-polygon shapefile ZIP uploaded over HTTP came back with genuine `geometry_type: Polygon`, `feature_count: 2` |
| 18b | Shapefile corrupted/incomplete/invalid-CRS/empty rejection | **VERIFIED** | `domain/errors.py`'s `IncompleteShapefileDatasetError`/`CorruptedShapefileError`/`InvalidShapefileCrsError`/`UnsupportedShapefileGeometryError`/`EmptyShapefileDatasetError`; covered by `tests/unit/test_data_acquisition_validation.py` and `tests/integration/test_shapefile_import.py` (11 tests) |
| 19 | **Risk Layer Generation & spatial visualization (Sprint C)** — GeoJSON output from genuine uploaded geometry, no fabricated features | **VERIFIED** | `contexts/analysis/infrastructure/risk_layer_generator.py`: `classify_risk` (line 51), `build_risk_layer` (line 104) — contains **no business formula**, only shapes already-computed `risk_index`/genuine geometry into RFC 7946 GeoJSON. `CompositionRootRiskLayerService` (`api/risk_layer_ports.py:58`) resolves geometry from the `f"{hazard_type}:RISK"` dataset slot (line 54's `_geometry_dataset_name`) — deliberately distinct from row 16's `HAZARD/EXPOSURE/VULNERABILITY` slots since RISK is a derived stage that never consumes the indicator-input pipeline (traced via `HazardStrategy.input_dependencies()`, confirmed uncontested). Proven live in §3: the real uploaded polygons ("Live Field A"/"Live Field B", exact `area_ha` 12.5/8.25) came back byte-for-byte in the downloaded GeoJSON, not regenerated/rounded/fabricated |
| 19b | Automatic risk-layer generation immediately after Analysis, no manual regeneration step | **VERIFIED** | `api/workflow_stage_executors.py:228-231` — `AnalysisStageExecutor` compares `stage_type.value == AnalysisStageType.RISK.value` (a real bug caught and fixed during Sprint C: the original `is` comparison across two differently-typed-but-identical-valued enums always evaluated `False`) and calls `risk_layer_service.generate_if_possible(...)` wrapped in `contextlib.suppress(Exception)` so a risk-layer failure can never fail the underlying Analysis computation. Proven live in §3: `risk-layer.geojson` was downloadable immediately after `start-workflow` returned `VALIDATED`, with zero intervening manual call |
| 19c | Read-only Risk Layer API (`/risk-layer`, `/risk-layer.geojson`, `/risk-summary`) | **VERIFIED** | `contexts/analysis/interface/routes.py:45,78,94,111` (`risk_layer_router`); reuses existing `assessment:view` permission, no new permission surface. Proven live in §3 with real response bodies (metadata, GeoJSON with `content-type: application/geo+json`, and the non-spatial summary companion) |
| 19d | Raster-ready output | **PARTIAL** (honestly, not silently) | `RasterMetadataResponse.available` is always `False` — `pyogrio`/`shapely` are vector-only OGR/GEOS bindings, no `rasterio`/GDAL-raster binding exists in this stack. The response includes a documented `reason` string plus a `suggested_bounding_box`/`suggested_crs` a future rasterization pass could use. Confirmed live in §3's `GET /risk-layer` response body — this is an unchanged, deliberate limitation, not a regression |
| 19e | WGS84/EPSG:4326 map-tool compatibility (Leaflet/MapLibre/OpenLayers/QGIS) | **VERIFIED** | All coordinates pass through untouched from the uploaded `.prj` (WGS84 in the live test); GeoJSON output is standard RFC 7946 `FeatureCollection`; proven live in §3 (`content-type: application/geo+json`, standard `Polygon` geometry type) |

---

## 2. What changed vs. the v1.2 baseline

The only three rows in `PRODUCTION_READINESS_REPORT.md`'s original 15-row table that were
stale are **Data Acquisition** (row 14/18/18b — gained real Shapefile import, was placeholder
header-sniffing before Sprint B), **Analysis/FIRAS/WRRAS** (rows 5/6/16 — gained real data
integration, was `StubIndicatorInputProvider` before Sprint A), and **Prediction** (row
9/17 — gained real data integration, was `StubPredictionDataProvider` before Sprint A). Rows
19/19a-e (Risk Layer) are entirely new capability, not a correction. Every other row is
unchanged and independently re-verified today (§0), not merely carried forward.

Test count progression: 491 (v1.2) → 499 (Sprint A) → 515 (Sprint B) → **533 today** (Sprint
C), 0 regressions at any step.

---

## 3. Live HTTP evidence (fresh run performed for this document)

Real HTTP calls against a live `uvicorn` process backed by a freshly created PostgreSQL
database (no fixtures, no `TestClient` shortcuts):

```
tenant registered, logged in (JWT bearer token)
→ 3× real FIRAS indicator dataset uploads (HAZARD/EXPOSURE/VULNERABILITY, genuine JSON payloads)
→ real Shapefile geometry upload (2-polygon ZIP) → parsed geometry_type: Polygon, feature_count: 2
→ workflow template published (HAZARD→EXPOSURE→VULNERABILITY→RISK, all AUTOMATIC)
→ assessment created → mark-ready → start-workflow → status: VALIDATED

GET /risk-layer  →
  risk_index: 0.1101, risk_level: LOW, classification: "Low Risk",
  geometry_type: Polygon, feature_count: 2, bounding_box: [0.0, 0.0, 30.0, 30.0],
  crs: EPSG:4326, formula_version: fri-multiplicative-v2,
  raster_metadata.available: false (honest, documented reason)

GET /risk-layer.geojson  →
  type: FeatureCollection, 2 features, content-type: application/geo+json
  feature 1: Polygon, properties.source_attributes = {name: "Live Field A", area_ha: 12.5}, risk_index: 0.1101
  feature 2: Polygon, properties.source_attributes = {name: "Live Field B", area_ha: 8.25}, risk_index: 0.1101
  (exact uploaded attribute values — not rounded, not fabricated)

GET /risk-summary  →
  risk_index: 0.1101, classification: "Low Risk" (no "features" key — non-spatial companion)
```

---

## 4. Remaining Gaps Before Client UAT

Everything above this line is VERIFIED or an honestly-documented PARTIAL boundary that does
not block UAT. The items below are the actual open list — carried forward from
`PRODUCTION_READINESS_REPORT.md`/`RELEASE_CERTIFICATION.md` where unresolved, none newly
introduced by Sprints A/B/C:

1. **SMS notification channel is still an unimplemented stub.** No real gateway (e.g. Twilio) integrated. Blocks UAT only if the client's UAT scope includes SMS alerting.
2. **GEE/USGS/NASA/Copernicus require real credentials.** All four fail immediately and honestly when unconfigured — confirm which of these UAT actually needs live before provisioning.
3. **No raster-ready output** (Sprint C requirement, honestly documented as not possible with current vector-only GIS deps — `rasterio`/GDAL-raster would be new scope, not a bug).
4. **No CRS reprojection** — uploaded Shapefiles must already be WGS84/EPSG:4326 (or another CRS the client explicitly accepts as-is); no on-ingest reprojection pipeline exists.
5. **Redis unavailability degrades `/health/ready`** — confirmed live in §0 (`redis: error`); confirm Redis is actually provisioned in the UAT environment, or confirm the app's behavior is acceptable without it.
6. **No rate limiting at the application layer** — mitigate at the reverse-proxy layer before any externally-reachable UAT environment.
7. **No access-token revocation/denylist** — open, documented tradeoff, Medium severity.
8. **Unhandled-exception responses leak `str(exc)` to the client** — Low severity, still open, contained fix recommended before a client-facing UAT (not just internal).
9. **No object storage (MinIO/S3)** — uploaded file bytes (including Shapefile ZIPs) travel as base64 on the `AcquisitionJob` row; confirm this is acceptable for UAT's expected upload volume/size before assuming it scales.
10. **No per-feature/pixel-level risk grading within a single Risk Layer** — every feature in a given risk layer currently carries the same assessment-level `risk_index` (Sprint C's `build_risk_layer` applies one classification uniformly across all features from the geometry dataset); if UAT expects visually differentiated risk per individual parcel/polygon, that is new scope, not a gap in what was built.

None of items 1–2, 5–9 are regressions — they were open at v1.2 and remain open. Items 3–4
and 10 are new-capability boundaries introduced by Sprint C's own honest scope decisions, not
defects.
