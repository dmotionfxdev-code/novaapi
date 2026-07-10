# Sprint B — Real ESRI Shapefile Import — Deliverables Report

**Objective**: Replace the placeholder Shapefile validation with a genuine ESRI Shapefile ingestion pipeline so uploaded GIS datasets become real Data Acquisition datasets and immediately participate in Sprint A's real Analysis pipeline.

**Backend only.** No frontend exists in this repository, so nothing there was touched. No changes to Assessment, FIRAS formulas, WRRAS formulas, Prediction logic, or Reporting.

---

## 1. What the codebase actually had (traced, not assumed)

`src/georisk/contexts/data_acquisition/domain/validation.py`'s `validate_shapefile()`, before this sprint:

```python
_SHAPEFILE_MAGIC = b"\x00\x00\x27\x0a"

def validate_shapefile(content: bytes) -> tuple[list[str], dict[str, object]]:
    if len(content) < 100 or content[:4] != _SHAPEFILE_MAGIC:
        return ["Content does not start with a valid Shapefile (.shp) header"], {}
    return [], {"byte_size": len(content)}
```

This checked exactly one thing: the first 4 bytes of a single blob equal the ESRI file-code magic number (9994, big-endian), and the blob is at least 100 bytes. It never parsed geometries, attributes, CRS, geometry type, feature count, or bounding box, and had no concept of a Shapefile being multiple files (`.shp`/`.shx`/`.dbf`/`.prj`) — the existing pipeline only ever passed it one file's raw bytes. Proven empirically (not assumed) during this sprint: GDAL's own Shapefile driver doesn't even use this magic number to decide readability — a file with its first 4 bytes zeroed out (which this validator would reject outright) still parses correctly via `pyogrio`, since GDAL trusts the `.dbf`/`.shx` structure instead. This confirmed the validator was checking something cosmetic, exactly matching the sprint brief's premise.

2 existing unit tests (`test_validate_shapefile_accepts_valid_header`, `test_validate_shapefile_rejects_short_content`) tested only this placeholder behavior — updated (not "kept passing unchanged", since the behavior they tested was intentionally replaced) to test the new real completeness check instead; see §6.

---

## 2. Library selection: `pyogrio` + `shapely`

Considered `pyogrio`, `Fiona`, and raw `GDAL/OGR` (the brief's three suggestions).

| | `pyogrio` (chosen) | `Fiona` | `osgeo.ogr` |
|---|---|---|---|
| Install | Self-contained manylinux wheel, bundles GDAL 3.12.4 | Self-contained wheel also available, but heavier | Requires matching system `libgdal`/`gdal-config` — fragile outside a matched environment |
| Maintenance | Actively developed; now the GeoPandas project's own recommended reader | Legacy path; GeoPandas itself recommends migrating off it | N/A (raw bindings, no ergonomics layer) |
| Read path | Vectorized reads via the OGR C API (fast, no per-feature Python object overhead) | Per-feature Python objects (slower) | Manual, verbose |
| Fits this project's deployment target | Yes — shared-hosting cPanel target has no system GDAL; this project's established discipline (`pgserver` embedded Postgres, GEE via pure API calls) already favors zero-system-dependency choices | Yes, functionally | No — the exact fragility this project's discipline avoids |

`shapely` (GEOS bindings, also a self-contained wheel) was added alongside `pyogrio` for one specific, empirically-justified reason: **the ESRI Shapefile format has no distinct "MultiPolygon" shape-type code** — a disjoint-multi-ring feature and a single-ring feature both use shape type 5 ("Polygon"). Verified directly:

```
>>> pyogrio.read_info("multi_ring.shp")["geometry_type"]
'Polygon'          # WRONG — this is actually a true MultiPolygon
>>> shapely.wkb.loads(actual_feature_wkb).geom_type
'MultiPolygon'      # CORRECT — read from the feature's real WKB
```

`infrastructure/shapefile_importer.py` therefore reads each feature's actual WKB via `pyogrio.raw.read()` and inspects its real type via `shapely`, rather than trusting the header-level `geometry_type` pyogrio's `read_info()` reports. This is the one piece of genuine engineering judgment this sprint required beyond "call the library" — found by testing, not assumed from documentation.

Both libraries are added to `pyproject.toml`'s dependencies (`pyogrio==0.13.0`, `shapely==2.1.2`), `requirements.lock`/`requirements-dev.lock`/`requirements.txt` regenerated for real via `pip-compile` (not hand-edited), and confined to `infrastructure/shapefile_importer.py` — the import-linter's "External GIS/GEE libraries only imported behind data_acquisition's infrastructure layer" contract was extended (`forbidden_modules = ["ee", "requests", "pyogrio", "shapely"]`) and re-verified passing (4/4 kept) with these two libraries in place, mirroring exactly the precedent Sprint 13/14 set for `requests`/`ee`.

`pyshp` (a pure-Python Shapefile *writer*, unrelated to the reader above) was added as a **dev-only** dependency purely to generate genuine `.shp`/`.shx`/`.dbf` test fixtures — never imported by production code.

---

## 3. Source-code changes

| File | Change |
|---|---|
| `domain/errors.py` | 5 new domain errors: `IncompleteShapefileDatasetError`, `CorruptedShapefileError`, `InvalidShapefileCrsError`, `UnsupportedShapefileGeometryError`, `EmptyShapefileDatasetError` — all `ValidationFailedError` subclasses, matching this context's existing convention. |
| `domain/validation.py` | `validate_shapefile` → `validate_shapefile_archive`: a genuine ZIP-completeness check using only stdlib `zipfile` (still pure domain logic — no GIS library needed to check file *names*). Confirms the archive is a valid ZIP, contains exactly one `.shp`, and that its `.shx`/`.dbf`/`.prj` companions are present — naming exactly which is missing if not. |
| `infrastructure/shapefile_importer.py` (new) | The real parser. `parse_shapefile_archive(content: bytes) -> ShapefileImportResult` reads geometries, attributes, the real per-feature geometry type, the real CRS (via `.prj` WKT resolution), feature count, and bounding box — all via `pyogrio`/`shapely`. Raises the 5 domain errors above for every genuine failure mode; never lets a raw, untyped GDAL exception escape (empirically found: a severely truncated `.shp` raises a bare `IndexError` from pyogrio's own internals, not one of `pyogrio.errors`'s typed exceptions). |
| `domain/entities.py` (`AcquisitionJob`) | 5 new optional fields (`shapefile_geometry_type`, `shapefile_feature_count`, `shapefile_bounding_box`, `shapefile_crs`, `shapefile_attributes`), mirroring Sprint 14's `extracted_features`/`skipped_features` precedent exactly. `complete()` gained matching optional parameters and enriches its existing `ProvenanceEntry` description with filename/CRS/geometry type/feature count/bounding box/importer version (requirement #5) — no new provenance mechanism, the existing one. |
| `infrastructure/models.py`, `infrastructure/mappers.py` | ORM columns + domain↔ORM mapping for the 5 new fields. |
| `migrations/versions/0017_shapefile_import.py` (new) | 5 new nullable columns on the existing `acquisition_job` table — no new table, no new permission grants. |
| `application/handlers.py` (`ExecuteAcquisitionJobHandler`) | After the existing `validate_dataset_content` structural/CRS check passes, a SHAPEFILE-format job is additionally parsed via `parse_shapefile_archive`; its 4 specific exception types are caught and become a `FAILED` job with a clear message (requirement #6) — no generic exception ever surfaces. Also fixes a real, general (not Shapefile-specific) latent bug found while implementing the "duplicate upload" requirement: every prior format always called `Dataset.catalog()` fresh, which would create two ambiguous version-1 rows under the same `(tenant, name)` on a repeat upload. Now checks for an existing dataset by name first and calls `Dataset.revise()` instead — reusing `Dataset.catalog()`/`Dataset.revise()` exactly as they exist, never bypassed. |
| `interface/schemas.py` (`AcquisitionJobResponse`) | 5 new response fields (additive only, mirroring `extracted_features`/`skipped_features`) — exposes the genuinely parsed geometry type/feature count/bounding box/CRS/attributes over the existing, unchanged endpoint. |
| `api/analysis_ports.py` (Sprint A's `CompositionRootIndicatorInputProvider`) | One new branch: if a resolved `AcquisitionJob` has `shapefile_attributes` (Shapefile-sourced), those become the raw indicator inputs — checked before falling through to the JSON-decode path (which would fail on a Shapefile job's ZIP-bytes `raw_content_base64`). No stub, no second provider, no duplicate pipeline — the exact same real provider Sprint A built, now aware of a second real data shape. |
| `pyproject.toml` | New dependencies (§2), import-linter contract extension, 2 new `mypy` overrides (`pyogrio.*`, `shapely.*` — both untyped, matching the existing `ee.*`/`geoalchemy2.*` override pattern). |

**API contract**: the existing `POST /api/v1/acquisition-jobs` → `POST /api/v1/acquisition-jobs/{id}/actions/execute` endpoints are completely unchanged in shape; `format: "SHAPEFILE"` now means "a ZIP archive's bytes" rather than "a single `.shp` file's bytes" — an unavoidable, minimal semantic change (a Shapefile is inherently multi-file; there was no way to satisfy requirement #2's "must contain .shp/.shx/.dbf/.prj" otherwise without a new endpoint or field, which the brief explicitly said to avoid). No frontend exists in this repo to require any change.

---

## 4. Test suite

Full validation performed against a fresh, real PostgreSQL instance (pgserver), following this project's established methodology (scratch copy, Python-3.10-sandbox compat shims, `pip install -e ".[dev]"`, `alembic upgrade head`, full `pytest`, `ruff`, `mypy`, `lint-imports`, a live `uvicorn` boot + real HTTP smoke test).

| Metric | Before Sprint B | After Sprint B |
|---|---|---|
| Tests passing | 499 | **515** |
| Tests skipped | 1 (real GEE connectivity) | 1 (unchanged) |
| Tests failing | 0 | **0** |
| `ruff check .` | clean | **clean** |
| `mypy src/` | clean (272 files) | **clean (273 files)** |
| `lint-imports` | 4/4 kept | **4/4 kept** (verifies `pyogrio`/`shapely` stay confined to `data_acquisition/infrastructure`) |

### New/updated tests

`tests/unit/test_data_acquisition_validation.py` — 2 old placeholder tests replaced, 7 new pure-domain tests for `validate_shapefile_archive` (complete archive, not-a-zip, missing `.dbf`/`.shx`/`.prj`, no `.shp`, multiple `.shp`).

`tests/integration/test_shapefile_import.py` (new, 11 tests) — every genuinely-parsed `.shp`/`.shx`/`.dbf` fixture is written by `pyshp` (a real writer), zipped exactly like a real upload, and driven through the real `ExecuteAcquisitionJobHandler`:

- `test_valid_point_shapefile_is_genuinely_parsed_and_catalogued` — 2-feature Point shapefile; asserts genuine `geometry_type="Point"`, `feature_count=2`, real bounding box, real attributes.
- `test_valid_polygon_shapefile_is_genuinely_parsed_and_catalogued` — same for Polygon.
- `test_valid_multipolygon_shapefile_is_genuinely_detected_and_catalogued` — a single feature with two disjoint rings; asserts `geometry_type="MultiPolygon"` — the exact case that proves per-feature WKB inspection is genuinely happening (the Shapefile header alone reports "Polygon").
- `test_missing_dbf_is_rejected_with_clear_error` / `_missing_shx_` / `_missing_prj_` — each asserts the specific missing filename appears in the job's error.
- `test_corrupted_shapefile_is_rejected_with_clear_error` — all 4 components present, `.shp` severely truncated.
- `test_invalid_crs_is_rejected_with_clear_error` — all 4 components present, `.prj` content is garbage text GDAL can't resolve.
- `test_empty_shapefile_is_rejected_with_clear_error` — a complete, parseable, zero-feature archive.
- `test_duplicate_upload_creates_a_new_dataset_version_not_a_collision` — the same `source_reference` uploaded twice; asserts the first `Dataset` is `SUPERSEDED`, the second is `CATALOGUED` at `version + 1`, and `get_latest` resolves to the second.
- `test_upload_catalog_analysis_end_to_end_with_real_shapefile` — the full chain in one test: a Point shapefile whose 6 DBF fields are named exactly `nir_pre`/`swir_pre`/`nir_post`/`swir_post`/`red_pre`/`red_post` (WRRAS's real `BURN_SEVERITY` leaf-stage indicator codes — chosen because they're the one WRRAS/FIRAS stage whose codes all fit within a classic DBF field name's 10-character limit, so no field-name truncation/aliasing is needed) is uploaded, catalogued as `"WILDFIRE:BURN_SEVERITY"`, and fed through a real `AnalysisStageExecutor` + `CompositionRootIndicatorInputProvider` — asserts the persisted `StageResult`'s raw inputs equal the genuinely-uploaded values and a `COMPLETE` status with real computed indicators.

Existing `tests/integration/test_data_acquisition_handlers.py` (17 tests, including the pre-existing CSV/GeoTIFF/GEE pipeline tests) and `test_data_acquisition_repositories.py` re-run unchanged and passing — proving the general `Dataset.catalog()`-vs-`revise()` duplicate-upload fix didn't disturb any other format's behavior.

---

## 5. Live HTTP verification (real server, real Postgres, no shortcuts)

Booted `passenger_wsgi:application` via a real ASGI server against a fresh Postgres instance, then drove the entire chain over genuine HTTP:

**Upload → Extract → Parse → Validate → Catalog:**

```
POST /api/v1/tenants, /api/v1/auth/token                     → real tenant + token
POST /api/v1/dataset-sources  (LOCAL_UPLOAD)                  → real DatasetSource
POST /api/v1/acquisition-jobs (format=SHAPEFILE, a real       → SCHEDULED
     2-feature Polygon .zip: two flood-risk zones near
     Kigoma, genuine lon/lat coordinates + zone_name/risk_lvl
     attributes, real WGS84 .prj)
POST /api/v1/acquisition-jobs/{id}/actions/execute            → COMPLETED
```

Response (excerpted, genuinely returned by the API — not asserted in a test, this is the live HTTP body):

```json
{
  "status": "COMPLETED",
  "shapefile_geometry_type": "Polygon",
  "shapefile_feature_count": 2,
  "shapefile_bounding_box": [29.6, -4.9, 29.85, -4.7],
  "shapefile_crs": "EPSG:4326",
  "shapefile_attributes": {"zone_name": "Kigoma Riverside", "risk_lvl": 0.82}
}
```

The bounding box `[29.6, -4.9, 29.85, -4.7]` is exactly the real extent of the two polygons uploaded — decisive, hard-to-fake proof the geometries were genuinely read (a magic-byte check could never produce this).

**Catalog → Analysis**, using a second real upload (BURN_SEVERITY-fielded, same live HTTP flow), then the real production code path (`AnalysisStageExecutor` + `CompositionRootIndicatorInputProvider`, invoked directly against the same live database — there is no HTTP route to trigger WRRAS's optional `BURN_SEVERITY` stage at all, a pre-existing Sprint 6 platform characteristic, not a Sprint B gap: these 3 optional WRRAS stages were deliberately kept outside every WorkflowTemplate to avoid blocking `VALIDATED` forever, so they're reachable only via direct command invocation, exactly what this step demonstrates):

```
outcome.success: True
raw inputs (from genuinely-uploaded Shapefile attributes):
  nir_pre = 0.45   swir_pre = 0.2   nir_post = 0.25
  swir_post = 0.3  red_pre = 0.08   red_post = 0.18
computed indicators:
  nbr_pre=0.3846  nbr_post=-0.0909  dnbr=0.4755  rbr=0.3432
  bai_pre=6.5574  bai_post=23.5294  dbai=16.972
```

The computed NBR/dNBR/RBR/BAI values are real WRRAS `BurnSeverityCalculator` output, driven entirely by the values genuinely read from the uploaded Shapefile's attribute table — proving the full **Upload → Catalog → Analysis** chain works with zero stub, zero duplicate pipeline, exactly requirement #8's ask.

---

## 6. Confirmation: genuinely parsed, not header-checked

- **Before**: `validate_shapefile(content: bytes)` checked 4 magic bytes + a minimum length. Proven (not assumed) that GDAL itself ignores this exact magic number when actually reading a Shapefile — a file with it zeroed out still parses correctly via `pyogrio`.
- **After**: `parse_shapefile_archive` reads real geometries (`pyogrio.raw.read`'s per-feature WKB), real attributes (the same call's field arrays), the real per-feature geometry type (via `shapely.wkb.loads(...).geom_type` — proven necessary and correct via the MultiPolygon test case above, where the header-level type is provably wrong), the real CRS (GDAL's own `.prj` WKT resolution, not the merely-declared `declared_crs`), the real feature count, and the real bounding box (GDAL's own `total_bounds`, not hand-computed).
- No custom binary parser was written anywhere — `pyogrio`/`shapely` (mature, independently-verified, widely-used libraries) do 100% of the actual Shapefile/WKB decoding. The only original code is: ZIP-completeness checking (stdlib `zipfile`, format-agnostic), mapping GDAL's results onto this platform's domain errors/`AcquisitionJob` fields, and wiring the result into the existing `Dataset.catalog()`/`ProvenanceEntry`/`CompositionRootIndicatorInputProvider` machinery.

---

## 7. Updated capability matrix

| Format | Structural validation | Semantic parsing | Feeds Analysis (Sprint A) |
|---|---|---|---|
| GeoJSON | Pure-domain (`validate_geojson`) | Not parsed beyond top-level `type`/`features` shape | Via JSON `raw_content_base64` decode |
| CSV | Pure-domain (`validate_csv`) | Row/column count only | Via JSON `raw_content_base64` decode (not CSV-parsed for indicators) |
| GeoTIFF | Pure-domain (`validate_geotiff`, TIFF magic bytes) | Not parsed | N/A (no indicator path) |
| **Shapefile** | Pure-domain ZIP completeness (`validate_shapefile_archive`) | **Real, via `pyogrio`/`shapely`: geometries, attributes, per-feature geometry type, CRS, feature count, bounding box** | **Yes — `shapefile_attributes` (Sprint B, this report)** |
| JSON | Pure-domain (`validate_json`) | Not parsed | Via JSON `raw_content_base64` decode |
| GEE (any `RemoteSensingSource`) | N/A (real `ee` API call) | Real, via `infrastructure/gee_connector.py` + `domain/feature_extraction.py` | Via `extracted_features` (Sprint 14) |

---

## 8. Total passing tests

**515 passing, 1 skipped, 0 failing** (was 499/1/0 after Sprint A) — net +16: +11 new integration tests in `test_shapefile_import.py`, +5 net in `test_data_acquisition_validation.py` (7 new, 2 replaced-not-kept since they tested the now-deleted placeholder behavior).
