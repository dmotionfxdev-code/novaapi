# Sprint C — Risk Layer Generation & Spatial Visualization — Deliverables Report

**Objective**: Analysis must produce genuine spatial outputs (GeoJSON/vector layers) representing the calculated risk, generated from the real geometries Sprint B's Shapefile import introduced — no fake maps, no placeholder GeoJSON.

**Backend only.** No frontend exists in this repository. No changes to Assessment, FIRAS formulas, WRRAS formulas, Prediction, Validation, or Reporting.

---

## 1. What the codebase actually had (traced first, per instruction)

Before this sprint, Analysis produced only numeric `StageResult`/`IndicatorSet` output — confirmed by reading `contexts/analysis/domain/entities.py` in full: the `StageResult` aggregate has no geometry field, no spatial concept anywhere. Sprint B's real Shapefile importer (`infrastructure/shapefile_importer.py`) reads every feature's real WKB geometry inside `parse_shapefile_archive()`, but **only ever kept the first feature's attributes** (`first_feature_attributes`, for `CompositionRootIndicatorInputProvider`) — the per-feature geometries themselves were computed transiently (to detect the true geometry type) and then **discarded**, never persisted anywhere. The only trace of them left after Sprint B is the original uploaded ZIP, still sitting in `AcquisitionJob.raw_content_base64` (confirmed by reading `domain/entities.py`: `schedule()`/`start()`/`complete()`/`fail()` never clear or mutate this field). This is the concrete basis for this sprint's design: **re-parse the already-validated, already-stored original archive** to recover every feature's real geometry, rather than inventing a new storage mechanism or fabricating anything.

---

## 2. Architecture decisions

### 2.1 Risk Layer Generator is business-formula-free by construction

`contexts/analysis/infrastructure/risk_layer_generator.py` never imports `pyogrio`/`shapely`, never touches `strategies/firas`/`strategies/wrras`, and never computes a risk index — it only ever copies a `risk_index` value it's handed. Its only original logic is (1) shaping already-resolved geometry+attribute dicts into an RFC 7946 `FeatureCollection`, and (2) a generic, documented, hazard-agnostic `classify_risk()` threshold function (LOW/MODERATE/HIGH/SEVERE) — explicitly labeled as a presentation convenience, not a FIRAS/WRRAS formula substitute.

### 2.2 Geometry source naming convention: `f"{hazard_type}:RISK"`

The hardest real design question this sprint faced: which uploaded dataset supplies a hazard type's risk-layer geometries? Reusing Sprint A's own indicator-input dataset slots (`f"{hazard_type}:HAZARD"`/`"EXPOSURE"`/`"VULNERABILITY"`) was considered and rejected — those must supply FIRAS's/WRRAS's own flat/nested indicator vocabulary exactly, and Sprint B's own investigation already proved most of that vocabulary exceeds a classic DBF field name's 10-character limit (only WRRAS's `BURN_SEVERITY` fit entirely). A Shapefile cataloged under one of those slots would silently break indicator parsing.

Traced instead: `RISK` is a **derived** stage — `HazardStrategy.input_dependencies()` declares it reads prior `StageResult`s, confirmed directly in `RecordStageResultHandler._gather_inputs`: the `IndicatorInputProvider` branch only runs when a stage has **no** declared dependencies. This means nothing in the platform ever calls `CompositionRootIndicatorInputProvider.provide_raw_inputs()` for a dataset named `f"{hazard_type}:RISK"` — it is genuinely uncontested, safe space. `api/risk_layer_ports.py`'s module docstring documents this reasoning in full.

### 2.3 New `RiskLayer` aggregate, not a `StageResult` field

A new aggregate (`contexts/analysis/domain/entities.py::RiskLayer`), own repository/table (`risk_layer`, migration `0018_risk_layer`), rather than adding a `geojson` field to `StageResult` — most `StageResult` rows (every non-RISK stage, and any RISK stage with no Shapefile-sourced geometry available) will never have one, and the two artifacts have independent lifecycles once the RISK stage can be re-run without necessarily re-uploading geometry. Same "insert-only, `get_latest` wins" versioning discipline as `StageResult`/`Dataset`/`PredictionRun`.

### 2.4 Composition-root orchestration, cross-context WKB→GeoJSON conversion stays in Data Acquisition

`shapefile_importer.py` gained `read_all_features()` (returns every feature's real geometry, converted to GeoJSON via `shapely.geometry.mapping()`, plus real attributes) — the ONLY new function that touches a GIS library, staying inside Data Acquisition's infrastructure layer per the import-linter's existing "External GIS/GEE libraries only imported behind data_acquisition's infrastructure layer" contract (re-verified 4/4 kept, **no changes needed** to that contract — Sprint C introduces zero new third-party dependencies, reusing exactly `pyogrio`/`shapely`/`pyshp` from Sprint B).

The new composition root `api/risk_layer_ports.py` (mirroring `api/analysis_ports.py`'s exact role) resolves the `f"{hazard_type}:RISK"` Dataset + its originating `AcquisitionJob`, calls `read_all_features()`, and hands the result to Analysis's own new `GenerateRiskLayerHandler` — which never imports `contexts.data_acquisition` itself.

### 2.5 Automatic generation, never blocking the real Analysis output

`AnalysisStageExecutor` (composition root) gained an optional `risk_layer_service` parameter; after a RISK stage completes successfully, it calls `generate_if_possible()` inside `contextlib.suppress(Exception)`. A missing/non-Shapefile geometry source is an expected, benign outcome the service itself already returns from silently — the `suppress` is belt-and-braces so risk-layer generation can **never** turn an already-successful FIRAS/WRRAS computation into a failed stage.

### 2.6 Raster: honestly not possible with current dependencies

Requirement #2 asked to expose raster metadata if technically possible, and to document honestly if not. Traced: this platform's only GIS-capable dependencies (`pyogrio`, `shapely`) are OGR/GEOS **vector**-side bindings — neither wraps GDAL's raster (GA) API, and no `rasterio`/raw `osgeo.gdal` dependency exists anywhere (Sprint 14 already documented the identical "no GDAL/rasterio" limitation for remote-sensing feature extraction). `RiskLayerResponse.raster_metadata` is included on every response with `available: false` and an honest `reason` string — never fabricated pixel data.

---

## 3. Source-code changes

| File | Change |
|---|---|
| `contexts/data_acquisition/infrastructure/shapefile_importer.py` | New `ShapefileFeature` dataclass + `read_all_features()` — reads EVERY feature's real geometry (GeoJSON via `shapely.geometry.mapping`) and attributes, reusing the exact `pyogrio.raw.read()` call Sprint B already proved correct. |
| `contexts/analysis/infrastructure/risk_layer_generator.py` (new) | `classify_risk()` + `build_risk_layer()` — the business-formula-free GeoJSON builder (requirement #1). |
| `contexts/analysis/domain/value_objects.py` | New `RiskLayerId(TypedId)`. |
| `contexts/analysis/domain/events.py` | New `RiskLayerGenerated` event. |
| `contexts/analysis/domain/errors.py` | New `RiskLayerNotFoundError`, `RiskLayerGenerationError`. |
| `contexts/analysis/domain/entities.py` | New `RiskLayer` aggregate + `.generate()` classmethod. |
| `contexts/analysis/domain/repositories.py` | New `RiskLayerRepository` protocol. |
| `contexts/analysis/infrastructure/models.py`, `mappers.py`, `repositories.py` | `RiskLayerModel` + mapper functions + `SqlAlchemyRiskLayerRepository` (mirrors `StageResultRepository` exactly). |
| `migrations/versions/0018_risk_layer.py` (new) | New `analysis.risk_layer` table. |
| `contexts/analysis/application/commands.py` | New `GenerateRiskLayerCommand` (carries already-resolved `features`/`geometry_type`/`crs` — never imports Data Acquisition). |
| `contexts/analysis/application/handlers.py` | New `GenerateRiskLayerHandler` — loads the target `StageResult`, reads its risk index generically (by position, never a hardcoded `"flood_risk_index"`-style code name), calls the generator, persists. |
| `contexts/analysis/application/queries.py` | New `GetLatestRiskLayerQuery`. |
| `contexts/analysis/application/ports.py` | New `RiskLayerGenerationPort` protocol. |
| `api/risk_layer_ports.py` (new) | `CompositionRootRiskLayerService` — the composition-root orchestrator (§2.4). |
| `api/workflow_stage_executors.py` | `AnalysisStageExecutor` gained the optional `risk_layer_service` param + the post-RISK auto-generation call (§2.5). |
| `api/app.py` | Wires `CompositionRootRiskLayerService` into `AnalysisStageExecutor`; registers the new `risk_layer_router`. |
| `contexts/analysis/interface/routes.py`, `schemas.py` | New `risk_layer_router` (3 endpoints, §4) + `RiskLayerResponse`/`RiskSummaryResponse`/`RasterMetadataResponse`. |

**Zero new third-party dependencies.** **Zero changes** to `pyproject.toml`, `requirements*.lock`, or the import-linter contract.

---

## 4. API endpoints (all read-only, `assessment:view` permission — same as `stage-results`)

| Endpoint | Returns |
|---|---|
| `GET /api/v1/assessments/{id}/risk-layer` | Metadata only (id, dataset_id, geometry_type, feature_count, bounding_box, crs, risk_index, risk_level, classification, formula_version, generated_at, raster_metadata) — never regenerates (requirement #6). |
| `GET /api/v1/assessments/{id}/risk-layer.geojson` | The raw RFC 7946 `FeatureCollection`, `Content-Type: application/geo+json`, a bare `Response` (not a Pydantic envelope) for streaming-friendliness (requirement #5/#7). |
| `GET /api/v1/assessments/{id}/risk-summary` | The non-spatial companion — just the computed-risk facts. |

Both `/stage-results` (existing) and these new routes are unchanged/additive — **zero existing API contracts modified**.

---

## 5. Test suite

| Metric | Before Sprint C | After Sprint C |
|---|---|---|
| Tests passing | 515 | **533** |
| Tests skipped | 1 | 1 (unchanged) |
| Tests failing | 0 | **0** |
| `ruff check .` | clean | **clean** |
| `mypy src/` | clean (273 files) | **clean (275 files)** |
| `lint-imports` | 4/4 kept | **4/4 kept** |

### New tests (18 total)

- `tests/unit/test_risk_layer_generator.py` (4) — classification thresholds, empty-features rejection, every-required-attribute-on-every-feature, full hazard-specific-indicator passthrough.
- `tests/unit/test_shapefile_read_all_features.py` (4) — every feature returned (not just first), genuine GeoJSON geometry matching uploaded coordinates, Point geometry shape, corrupted-archive error.
- `tests/integration/test_risk_layer.py` (8) — FIRAS → real GeoJSON risk layer (`risk_index≈0.1101`), WRRAS → real GeoJSON risk layer (`risk_index≈0.0926`), MultiPolygon dataset → `MultiPolygon` risk layer, Point dataset → `Point` risk layer, CRS preservation (non-4326 Web Mercator `.prj` preserved exactly, not silently forced to WGS84), source-attribute preservation, empty geometry dataset → no risk layer generated (RISK computation still succeeds), full upload→import→analysis→risk-layer chain.
- `tests/integration/test_risk_layer_api.py` (2) — the real HTTP download endpoint after a real workflow run (metadata + `.geojson` + `.risk-summary`, asserting `Content-Type: application/geo+json`), and a 404 before any RISK stage has completed.

---

## 6. Live HTTP verification (real server, real Postgres, no shortcuts)

Full chain over genuine HTTP against a freshly-booted `passenger_wsgi:application`:

```
POST /tenants, /auth/token                                    → real tenant + token
POST /dataset-sources + /acquisition-jobs (format=JSON)        → FLOOD:HAZARD/EXPOSURE/VULNERABILITY
     x3, execute                                                 catalogued (real FIRAS indicator inputs)
POST /dataset-sources + /acquisition-jobs (format=SHAPEFILE),  → FLOOD:RISK catalogued: geometry_type=Polygon,
     a real 2-polygon .zip (genuine Kigoma-area coordinates),     feature_count=2,
     execute                                                     bounding_box=[29.6,-4.9,29.85,-4.7]
POST /workflow-templates (HAZARD→EXPOSURE→VULNERABILITY→RISK) + publish
POST /assessments, mark-ready, start-workflow                  → assessment status: VALIDATED
```

**No manual regeneration step was ever called** — the risk layer was already there:

```json
GET /assessments/{id}/risk-layer  →
{
  "hazard_type": "FLOOD", "stage_type": "RISK", "geometry_type": "Polygon",
  "feature_count": 2, "crs": "EPSG:4326",
  "bounding_box": [29.6, -4.9, 29.85, -4.7],
  "risk_index": 0.1101, "risk_level": "LOW", "classification": "Low Risk",
  "formula_version": "fri-multiplicative-v2",
  "raster_metadata": {"available": false, "reason": "... vector-only (OGR/GEOS) ..."}
}
```

**Decisive independent verification** — the downloaded `.geojson` was fed to `pyogrio` (GDAL/OGR), a completely independent code path from this sprint's own generator:

```
Driver: GeoJSON
Geometry type: Polygon
Feature count: 2
CRS: EPSG:4326
Total bounds: (29.6, -4.9, 29.85, -4.7)     <- exactly the uploaded coordinates
Feature 0: geom_type=Polygon, valid=True, bounds=(29.6, -4.8, 29.7, -4.7)
Feature 1: geom_type=Polygon, valid=True, bounds=(29.8, -4.9, 29.85, -4.85)
```

This proves, independently of anything this sprint wrote: **feature count matches** the imported dataset (2), **coordinates match** the genuinely uploaded geometries exactly, **risk values originate from Analysis** (`0.1101` is FIRAS's real `fri-multiplicative-v2` output, not a placeholder), and **no fabricated geometries exist** (GDAL itself reports the bounds that exactly bound the two uploaded polygons).

---

## 7. Example generated GeoJSON (real, from the live smoke test above)

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[29.6, -4.8], [29.6, -4.7], [29.7, -4.7], [29.7, -4.8], [29.6, -4.8]]]
      },
      "properties": {
        "assessment_id": "1d4965e6-db68-4cf6-80bc-c15790683a1d",
        "hazard_type": "FLOOD",
        "stage_type": "RISK",
        "risk_index": 0.1101,
        "risk_level": "LOW",
        "classification": "Low Risk",
        "analysis_timestamp": "2026-07-09T22:42:37.086980+00:00",
        "formula_version": "fri-multiplicative-v2",
        "dataset_id": "387d64eb-5132-4cd8-8eca-3c06c259b6dc",
        "geometry_type": "Polygon",
        "flood_risk_index": 0.1101,
        "source_attributes": {"zone_name": "Kigoma Riverside", "population": 4200.0}
      }
    }
  ]
}
```

---

## 8. Updated capability matrix

| Capability | Status |
|---|---|
| GeoJSON FeatureCollection generation | **Real** — genuine features from Sprint B's uploaded geometries |
| Vector polygon layer | **Real** — verified (FIRAS test, live smoke test) |
| Point layer | **Real** — verified (WRRAS test) |
| Line layer | Supported by the same generic code path (`LineString`/`MultiLineString` are in `shapefile_importer.py`'s `_SUPPORTED_GEOMETRY_TYPES`); not separately fixture-tested this sprint since no LineString Shapefile fixture was built, but no special-casing exists to fail on it |
| MultiPolygon layer | **Real** — verified (per-feature WKB type detection, not header-level) |
| Raster output | **Honestly unavailable** — no `rasterio`/GDAL-raster dependency; documented via `raster_metadata.available=false` on every response |
| CRS preservation | **Real** — verified with a genuine non-EPSG:4326 (Web Mercator) `.prj`, preserved exactly |
| Attribute preservation | **Real** — original DBF attributes preserved under `source_attributes` on every feature |
| Automatic generation post-Analysis | **Real** — wired into `AnalysisStageExecutor`, zero manual step |
| Storage (no regeneration per request) | **Real** — persisted `risk_layer` table, read-only query serves it |
| Read-only API | **Real** — 3 endpoints, all additive, zero existing contracts changed |

---

## 9. What was NOT done / honest limitations

- No raster (GeoTIFF/pixel) generation — see §2.6.
- No reprojection — CRS is preserved as declared, never transformed to WGS84 if the source is something else (requirement #7 says "unless another CRS is explicitly required" — none was required here, so preservation, not forced conversion, is the correct behavior).
- The geometry-source dataset is tenant/hazard-type-scoped (matching Sprint A's own `f"{hazard_type}:{stage_type}"` convention precedent), not per-assessment — every assessment of the same hazard type currently shares the same uploaded geometry until it's revised, an explicit, documented design choice (§2.2), not an oversight.
