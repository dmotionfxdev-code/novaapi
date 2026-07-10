# Sprint A — Backend API: Real Data Integration — Validation Report

**Objective**: Replace all stub providers so Analysis and Prediction use real uploaded datasets instead of synthetic reference data.

**Constraints honored**: backend only (no frontend touched — none exists in this repo); FIRAS formulas unmodified; WRRAS formulas unmodified; Assessment aggregate unmodified; all architecture boundaries and the composition-root pattern preserved.

---

## 1. What changed

### 1.1 Analysis: `IndicatorInputProvider`

- **New file**: `src/georisk/api/analysis_ports.py` — `CompositionRootIndicatorInputProvider`, a real implementation of Analysis's `IndicatorInputProvider` port. Composition-root code (outside `contexts.analysis` and `contexts.data_acquisition`, same role as every other `api/*_ports.py` file), since Analysis reading Data Acquisition crosses the peer-independence boundary import-linter enforces.
- **Real data source**: for a given `(hazard_type, stage_type, assessment_id)`, it resolves the assessment's tenant, then looks up the tenant's own cataloged Data Acquisition `Dataset` named `f"{hazard_type}:{stage_type}"` (e.g. `"FLOOD:HAZARD"`, `"WILDFIRE:VULNERABILITY"`) via `DatasetRepository.get_latest` — the exact per-tenant "current version by name" lookup Sprint 7 already built. It then recovers that dataset's originating `AcquisitionJob` and returns either its GEE `extracted_features` (Sprint 14) or its decoded `raw_content_base64` JSON payload (Local Upload) verbatim.
- **Never fabricates**: a missing dataset, a missing originating job, or an undecodable payload all raise a clear, typed error (`MissingIndicatorDatasetError`, `InvalidIndicatorPayloadError`) rather than falling back to any default. `RecordStageResultHandler`'s existing try/except (unchanged) converts this into `StageResult.FAILED` with the error message preserved — the Workflow Engine's existing retry mechanism handles it exactly like any other calculator input failure, no new error-handling path required.
- **New repository method**: `StageResultRepository.list_all_indicators_by_assessment(tenant_id, hazard_type, *, limit=200)` (domain protocol in `contexts/analysis/domain/repositories.py`, SQLAlchemy implementation in `contexts/analysis/infrastructure/repositories.py`) — merges every one of a tenant's real assessments' COMPLETE stage snapshots (across all stage types) into one row per assessment. Used by Prediction's real provider (below), not by the indicator input provider itself.

### 1.2 Prediction: `PredictionDataProvider`

- **Protocol extended** (`contexts/prediction/application/ports.py`): `generate_observations` now takes `tenant_id: str` and `hazard_type: str | None` in addition to the existing `variables`/`sample_count`/`seed` — needed so a real implementation can scope its lookup to the requesting tenant and hazard strategy. `StubPredictionDataProvider` accepts and ignores both (kept, for reference and for existing unit tests that construct it directly without calling the method).
- **Call site updated** (`contexts/prediction/application/handlers.py`, `RunPredictionHandler.handle`): passes `tenant_id=command.tenant_id, hazard_type=selection.hazard_type` through.
- **New real implementation**: `CompositionRootPredictionDataProvider` in `src/georisk/api/prediction_ports.py` (extending the existing Sprint 8 composition-root file, per its own docstring's precedent). For each real assessment row returned by `list_all_indicators_by_assessment`, it projects out exactly the requested variable codes; an assessment missing any requested code is excluded from the result rather than padded with a guessed value. Raises `MissingHazardTypeError` if the `VariableSelection` has no `hazard_type` (there is then no specific hazard strategy's history to read).

### 1.3 Wiring (`src/georisk/api/app.py`)

- `app.state.prediction_data_provider = CompositionRootPredictionDataProvider(app.state.db)` (was `StubPredictionDataProvider()`).
- `analysis_executor = AnalysisStageExecutor(app.state.db, strategy_registry, CompositionRootIndicatorInputProvider(app.state.db))` (previously omitted the third argument, silently falling back to `StubIndicatorInputProvider()` inside `AnalysisStageExecutor.__init__`).
- `StubPredictionDataProvider`/`StubIndicatorInputProvider` imports removed from `api/app.py` entirely.

### 1.4 What was deliberately left alone

- `StubIndicatorInputProvider`/`StubPredictionDataProvider` classes themselves are **not deleted** — they remain in `contexts/analysis/application/ports.py` / `contexts/prediction/application/ports.py` as documented placeholders, still used by unit/integration tests that exercise calculator wiring in isolation from Data Acquisition (e.g. `test_analysis_handlers.py`, `test_wrras_handlers.py`, `test_prediction_handlers.py`) and by `AnalysisStageExecutor`'s own optional-parameter default (used only when a caller — exclusively test code — constructs it without an explicit `input_provider`). **Production runtime (`api/app.py`) never instantiates either stub** — see §3 for direct proof.
- FIRAS/WRRAS calculator code (`contexts/analysis/strategies/firas/**`, `contexts/analysis/strategies/wrras/**`) — untouched.
- `contexts.assessment` (the Assessment aggregate, Workflow Engine) — untouched.
- No frontend exists in this repository; nothing outside `georisk-platform`'s backend was touched.

---

## 2. Test results

Full suite re-run against a fresh, real PostgreSQL instance (pgserver, extension-less), following this project's established validation methodology (scratch copy, Python 3.10-sandbox compat shims, `pip install -e ".[dev]"`, `alembic upgrade head`, full `pytest`, `ruff`, `mypy`, `lint-imports`, a live `uvicorn` boot + real HTTP smoke test):

| Metric | Before Sprint A | After Sprint A |
|---|---|---|
| Tests passing | 491 | **499** |
| Tests skipped | 1 (real GEE connectivity) | 1 (unchanged) |
| Tests failing | 0 | **0** |
| New tests added | — | **8**, in `tests/integration/test_sprint_a_real_data_integration.py` |
| `ruff check .` | clean | **clean** |
| `mypy src/` | clean (271 files) | **clean (272 files)** |
| `lint-imports` | 4/4 kept | **4/4 kept** |

### 2.1 New tests (`tests/integration/test_sprint_a_real_data_integration.py`)

1. `test_real_indicator_input_provider_returns_uploaded_payload_verbatim` — a real cataloged `FLOOD:HAZARD` dataset's payload is returned unchanged by `CompositionRootIndicatorInputProvider`.
2. `test_indicator_input_provider_raises_when_no_dataset_cataloged` — no dataset → `MissingIndicatorDatasetError`, not fabricated data.
3. `test_analysis_stage_computes_from_real_uploaded_data_not_stub_values` — `AnalysisStageExecutor` wired with the real provider computes `flood_hazard_index` from genuinely uploaded values, and the persisted snapshot contains the uploaded payload verbatim; the computed value is asserted **not equal** to `StubIndicatorInputProvider`'s well-known `0.565`.
4. `test_analysis_stage_fails_honestly_when_no_dataset_uploaded` — missing data → `StageResult.FAILED` with the dataset name in the error, `indicators is None` (no fabrication).
5. `test_real_prediction_data_provider_reads_completed_analysis_outputs` — 3 real assessments, each with a distinct real `rainfall_index` (via `Dataset.revise()`), produce exactly 3 real observation rows with the expected values.
6. `test_real_prediction_data_provider_excludes_assessments_missing_a_code` — requesting a code no real assessment has ever produced returns an empty tuple, not a fabricated row.
7. `test_real_prediction_data_provider_requires_hazard_type` — `hazard_type=None` → `MissingHazardTypeError`.
8. `test_end_to_end_upload_catalog_analysis_prediction_validation` — the full chain in one test: 3 real dataset uploads (via `Dataset.revise()`) → 3 real `AnalysisStageExecutor` HAZARD-stage runs → a real, confirmed `VariableSelection` over `rainfall_index` → a real `RunPredictionHandler` Pearson-correlation run reading those exact 3 real observations (`model_metadata.sample_size == 3`, `run.status == COMPLETED`).

### 2.2 Pre-existing tests updated (setup only, zero assertion-logic changes beyond real-data equivalents of prior stub-derived values)

Removing the stub from **production** wiring (`api/app.py`) meant every pre-existing HTTP-level test that drives a full workflow/prediction through `create_app()`'s real lifespan — previously relying on the implicit stub for indicator/observation data — needed real data seeded first. A new shared helper, `tests/integration/_sprint_a_seed_helpers.py`, catalogs real Data Acquisition datasets whose payloads are **copied verbatim from `StubIndicatorInputProvider`'s own fixed dictionaries** — so every pre-existing assertion about an exact stub-derived indicator value (e.g. `flood_risk_index == 0.1101`, `wildfire_hazard_index == 0.58`) continues to hold unchanged, because the same numbers now arrive as a real, cataloged, tenant-uploaded dataset instead of a hardcoded object in the call path:

| File | Change |
|---|---|
| `test_analysis_api.py`, `test_wrras_api.py`, `test_workflow_api.py`, `test_validation_api.py` | Seed real FIRAS/WRRAS indicator datasets (stub-equivalent values) before starting a workflow. |
| `test_prediction_api.py`, `test_validation_regression_api.py`, `test_reporting_api.py`, `test_notification_api.py`, `test_dashboard_api.py` | Additionally seed real, non-collinear, multi-assessment `ndvi`/`wind_speed`/`burned_area` observations (via real `AnalysisStageExecutor` runs, not direct row inserts) so `CompositionRootPredictionDataProvider` has genuine correlation/regression data — replacing what `StubPredictionDataProvider` used to fabricate on demand. Exact `sample_size` assertions (previously always `1000`, matching the stub's on-demand-fabricate-anything behavior) were updated to the real observation count actually seeded (`10`) — the only assertion values that could not stay numerically identical, because a real provider can only report as many observations as real history exists, never an arbitrary requested count. |

No assertion about FIRAS/WRRAS formula output, API response shape, or HTTP status code was changed.

---

## 3. Proof no stub provider remains in production runtime

**Static** (`grep -rn "Stub\(IndicatorInputProvider\|PredictionDataProvider\)(" src/`): the only remaining *instantiations* are `workflow_stage_executors.py`'s `AnalysisStageExecutor.__init__`'s optional-parameter default (`input_provider if input_provider is not None else StubIndicatorInputProvider()`) — used only when a caller omits the third constructor argument, which `api/app.py` never does — and the stub classes' own definitions. `api/app.py` contains zero remaining references to either stub class after this sprint.

**Dynamic** (executed against the real, fully-booted app — not assumed from reading the code):

```python
app = create_app(settings=settings)
async with app.router.lifespan_context(app):
    assert not isinstance(app.state.prediction_data_provider, StubPredictionDataProvider)
    for stage_type, executor in app.state.stage_executor._overrides.items():
        assert not isinstance(executor._input_provider, StubIndicatorInputProvider)
```

Output:
```
prediction_data_provider type: CompositionRootPredictionDataProvider
HAZARD: input_provider type = CompositionRootIndicatorInputProvider
EXPOSURE: input_provider type = CompositionRootIndicatorInputProvider
VULNERABILITY: input_provider type = CompositionRootIndicatorInputProvider
RISK: input_provider type = CompositionRootIndicatorInputProvider
RESILIENCE: input_provider type = CompositionRootIndicatorInputProvider
CONFIRMED: no stub provider is wired into production runtime.
```

**Live HTTP** (see §4) — the actual computed indicator value differs from the stub's well-known constant, which is only possible if real data, not the stub, drove the computation.

---

## 4. End-to-end demonstration (live HTTP, real PostgreSQL, no shortcuts)

Booted `passenger_wsgi:application` via a real ASGI server against the same fresh Postgres instance used for the full test run, then drove the entire chain over genuine HTTP:

1. **Register tenant** → `POST /api/v1/tenants`, login → `POST /api/v1/auth/token`.
2. **Upload**: `POST /api/v1/dataset-sources` (LOCAL_UPLOAD) → `POST /api/v1/acquisition-jobs` with `source_reference: "FLOOD:HAZARD"` and a base64 JSON payload of `{rainfall_index: 0.93, water_level_index: 0.88, slope_index: 0.81, drainage_index: 0.77, land_use_index: 0.90, soil_index: 0.85}` — deliberately far from the old stub's fixed values.
3. **Catalog**: `POST /api/v1/acquisition-jobs/{id}/actions/execute` → `"status": "COMPLETED"`, a real `Dataset` cataloged under the name `"FLOOD:HAZARD"`.
4. **Analysis**: published a HAZARD-only FIRAS workflow template, created and started an assessment → `"status": "VALIDATED"`.
5. **Result**: `GET /api/v1/assessments/{id}/stage-results/HAZARD` returns the six raw indicators **exactly as uploaded** (`rainfall_index: 0.93`, ..., `soil_index: 0.85`) and a computed `flood_hazard_index: 0.8645` — decisively different from `StubIndicatorInputProvider`'s well-known `flood_hazard_index: 0.565`, proving the real uploaded values, not any stub, drove this computation.

This is the literal "Upload dataset → Catalog → Analysis" chain; "→ Prediction → Validation" is covered by the automated `test_end_to_end_upload_catalog_analysis_prediction_validation` test (§2.1 item 8) and by every passing `test_validation_*_api.py`/`test_prediction_api.py` test, all now running against real, seeded Analysis history rather than a stub.

---

## 5. API contracts

Zero changes to any HTTP request/response schema, route path, or status code. The only non-additive signature change anywhere is `PredictionDataProvider.generate_observations`'s two new keyword arguments (`tenant_id`, `hazard_type`) — an internal application-layer port, not part of any external API contract, and additive/keyword-only so no existing call site broke without an explicit, deliberate update (§1.2).

## 6. Known limitations of this sprint's real-data model

- **Naming convention, not a new domain concept**: a tenant's indicator dataset for a given `(hazard_type, stage_type)` is identified by `Dataset.metadata.name == f"{hazard_type}:{stage_type}"` (e.g. `"WILDFIRE:VULNERABILITY"`). This is a lightweight convention layered on Sprint 7's existing `DatasetRepository.get_latest(tenant_id, name)` lookup — it required no change to the Data Acquisition domain model, but it does mean a tenant must know to catalog datasets under this exact name for the real provider to find them.
- **One current dataset per (tenant, hazard_type, stage_type)**: `get_latest` always resolves the newest non-superseded version. Re-uploading (via `Dataset.revise()`) before running a new assessment gives that assessment fresh inputs, but two assessments run without an intervening revision see the same input snapshot — an accurate reflection of "this is the tenant's current best data for this stage," not a limitation introduced by this sprint's design choices beyond what Sprint 7's versioning model already implies.
- **Prediction's real observation count is bounded by real history**: unlike the stub (which fabricated exactly `sample_count` rows on demand), the real provider can only return as many observations as the tenant has real completed assessments for that hazard type. This is the entire point of Sprint A, not a defect — but it does mean a tenant with few real assessments gets correlation/regression fits with correspondingly few data points, same as any real statistical analysis.
