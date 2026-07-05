# Security Retest Report — Data Acquisition Tenant-Isolation Fix

**Scope**: closes the single **High**-severity finding from `SECURITY_REVIEW.md` §3 ("Multi-Tenant Isolation") that was flagged as blocking production deployment. No other findings from that review are in scope for this retest — per instruction, this pass targets only the High-severity item.

---

## 1. Exact Code Path Traced

**Vulnerable handlers**: `CatalogDatasetHandler.handle` and `ScheduleAcquisitionJobHandler.handle`, both in `src/georisk/contexts/data_acquisition/application/handlers.py`.

Both handlers accept a `dataset_source_id` from the request and resolve it like this (identical shape in both, before the fix):

```python
dataset_source_id = DatasetSourceId.from_string(command.dataset_source_id)
source = await self._source_repo.get_by_id(dataset_source_id)
if source is None:
    raise DatasetSourceNotFoundError(f"DatasetSource {dataset_source_id} not found")
# ... proceeds to use `source` without any further check ...
```

`SqlAlchemyDatasetSourceRepository.get_by_id` (`infrastructure/repositories.py`) fetches strictly by primary key:

```python
async def get_by_id(self, dataset_source_id: DatasetSourceId) -> DatasetSource | None:
    model = await self._session.get(DatasetSourceModel, dataset_source_id.value)
    return mappers.dataset_source_to_domain(model) if model else None
```

**No `tenant_id` filter exists in this query, by design** — it is shared with the legitimate "resolve a possibly-global source" case (`DatasetSource.tenant_id: TenantId | None`; `None` means a platform-wide source any tenant may reference, e.g. a public CHIRPS registration — `domain/entities.py`'s own docstring). The design is correct; what's missing is the **caller-side check** every other cross-aggregate reference in this codebase performs after such a fetch (e.g. Assessment's `_assert_same_tenant`, which every other context's query/handler layer calls after an equivalent `get_by_id`). `CatalogDatasetHandler`/`ScheduleAcquisitionJobHandler` were the only two call sites in the entire codebase that fetched a `DatasetSource` by ID and skipped this check.

**Consequence**: any authenticated tenant supplying a `DatasetSourceId` belonging to a *different* tenant's *private* (`tenant_id` set, not `None`) `DatasetSource` would have that reference accepted at face value — `source is None` is the only guard, and a private cross-tenant source is never `None`.

## 2. Exploit Scenario, Quantified

Reproduced against a real PostgreSQL instance (embedded `pgserver`, not simulated), using the actual application handlers with no mocking:

1. Tenant A registers a private `DatasetSource` (`POST /dataset-sources`, provider `USER_UPLOAD`) — `tenant_id` is set to Tenant A's ID.
2. Tenant B (a different, unrelated tenant, holding only its own valid JWT) discovers or guesses that `DatasetSourceId` — realistic vectors include: sequential/enumerable exposure in logs, shared support tickets, browser history, or simple brute-force guessing of a 128-bit UUID is not the concern here, the concern is Tenant B *already possessing* the ID through any leak, since even a single leaked ID is enough.
3. Tenant B calls `POST /datasets` (catalog a dataset) or `POST /acquisition-jobs` (schedule an acquisition job) referencing that `DatasetSourceId`, authenticated as itself.

**Before the fix**: both requests succeeded (`201 Created`) — Tenant B's dataset/job now permanently references Tenant A's private `DatasetSource`, and Tenant B has confirmed (via the success response) that a `DatasetSource` with that exact ID exists, which of the two provider types it uses, and can continue to catalog arbitrary further datasets against it indefinitely.

**Live reproduction evidence** (`CatalogDatasetHandler` path, direct handler invocation against real Postgres, before the fix):
```
[setup] Tenant A registered private DatasetSource 4b80a04b-4e5e-4758-ad4f-24c7aa297dff (tenant_id=8d0388be-d3f6-4bbd-9676-9d9ee20252b5)
[EXPLOIT] Tenant B successfully catalogued Dataset 5198fee1-f618-454f-a8f7-e38a2dcc9137 referencing Tenant A's PRIVATE DatasetSource 4b80a04b-4e5e-4758-ad4f-24c7aa297dff — tenant isolation BYPASSED
```
(`ScheduleAcquisitionJobHandler` path reproduced identically with a `LOCAL_UPLOAD`-provider source.)

**Impact classification**: information disclosure (confirms existence + provider type of a private cross-tenant resource) plus unauthorized reference/write (Tenant B permanently attaches its own data to Tenant A's registry entry, which could pollute Tenant A's provenance graph or be used to correlate/interfere with Tenant A's data pipeline). Rated **High**, not Critical, because it does not expose Tenant A's actual dataset *content* — `DatasetSource` itself carries only a name/provider/description, no payload — but it is a genuine, unauthenticated-relative-to-tenant-boundary access control failure, which is the exact class of bug multi-tenant SaaS platforms must not ship with.

## 3. Smallest Safe Fix

Added one small helper function and two one-line call sites — no new abstractions, no changes to any other handler, query, repository, or entity:

```python
def _assert_dataset_source_visible_to_tenant(source: DatasetSource, tenant_id: TenantId) -> None:
    """A DatasetSource is visible to a tenant if it's global (tenant_id=None)
    or privately owned by that same tenant — mirrors list_available's
    existing SQL-level visibility rule, applied as a single-entity check.
    Fails exactly like "not found" (never "forbidden"), matching every
    other cross-tenant check in this codebase."""
    if source.tenant_id is not None and source.tenant_id != tenant_id:
        raise DatasetSourceNotFoundError(f"DatasetSource {source.id} not found")
```

Called immediately after the existing `if source is None` check in both `CatalogDatasetHandler.handle` and `ScheduleAcquisitionJobHandler.handle`:
```python
source = await self._source_repo.get_by_id(dataset_source_id)
if source is None:
    raise DatasetSourceNotFoundError(f"DatasetSource {dataset_source_id} not found")
_assert_dataset_source_visible_to_tenant(source, tenant_id)   # <-- the fix
```

**Why this is the smallest safe fix**:
- Reuses the existing `DatasetSourceNotFoundError` (already imported, already mapped to HTTP 404) — no new error type, no new HTTP status code, no client-visible behavior change for legitimate callers.
- Correctly preserves the two legitimate access patterns: same-tenant access to a private source, and any-tenant access to a global (`tenant_id=None`) source — both explicitly re-verified below.
- Fails as "not found," not "forbidden" — does not leak that a cross-tenant private source exists, consistent with API Resource Model §9 and every other tenant check in the codebase.
- Touches exactly one file (`handlers.py`), two call sites, zero changes to domain entities, repositories, migrations, request/response schemas, or any other context.

## 4. Verification

### 4.1 Exploit blocked (same reproduction script, after the fix)
```
[setup] Tenant A registered private DatasetSource e8538233-6484-4289-b727-0ac2cba55f8f (tenant_id=92b32a05-b0a1-4590-a49c-a8b0ea0541b2)
[BLOCKED] Tenant B's attempt was rejected: DatasetSourceNotFoundError: DatasetSource e8538233-6484-4289-b727-0ac2cba55f8f not found
[setup] Tenant A registered private DatasetSource 5ef27f38-d7bb-4825-a7de-84ce38be4963 (tenant_id=92b32a05-b0a1-4590-a49c-a8b0ea0541b2)
[BLOCKED] Tenant B's attempt was rejected: DatasetSourceNotFoundError: DatasetSource 5ef27f38-d7bb-4825-a7de-84ce38be4963 not found
```

### 4.2 Legitimate access patterns unaffected (same real-Postgres environment)
```
[OK] Same-tenant catalog succeeded: Dataset 2ac7516b-46a5-4427-a22c-9b6b57adb602
[OK] Any-tenant access to global source succeeded: Dataset e333d8cc-ccdd-44f3-9372-3188b3cd29be
[OK] Same-tenant job scheduling succeeded: AcquisitionJob 66d8c71f-7580-452d-ad4e-16d73abe6363
```

### 4.3 Live HTTP re-verification (full app, real PostgreSQL, real JWT auth — not just the handler layer)
```
POST /api/v1/datasets  (Tenant B, referencing Tenant A's private DatasetSource)
→ HTTP 404
{"type":"https://docs.firas.dev/errors/DatasetSourceNotFoundError","title":"DatasetSourceNotFoundError",
 "status":404,"detail":"DatasetSource 2f9d41d8-509b-4351-b818-858443216f68 not found", ...}
```

### 4.4 Permanent regression tests added
Four new tests in `tests/integration/test_data_acquisition_handlers.py` (real Postgres, not mocked):
- `test_catalog_dataset_rejects_cross_tenant_private_dataset_source`
- `test_catalog_dataset_allows_global_dataset_source_from_any_tenant`
- `test_schedule_acquisition_job_rejects_cross_tenant_private_dataset_source`
- `test_schedule_acquisition_job_allows_same_tenant_private_dataset_source`

### 4.5 Full test suite

| Check | Before fix (Sprint 14 baseline) | After fix |
|---|---|---|
| Tests passing | 487 | **491** (+4 new regression tests) |
| Tests skipped | 1 (real GEE connectivity, no live credentials) | 1 (unchanged) |
| Tests failing | 0 | **0** |
| `ruff check src/ tests/` | clean | clean |
| `mypy src/` | 0 errors (271 files) | 0 errors (271 files) |
| `lint-imports` | 4/4 contracts kept | 4/4 contracts kept |

All checks re-run against a freshly created PostgreSQL database (embedded `pgserver`) — not assumed from the fix alone.

## 5. Scope Discipline

This retest and fix touch exactly one concern: the High-severity tenant-isolation gap. No new features were introduced, no existing business logic/formulas were changed, no other `SECURITY_REVIEW.md` finding (rate limiting, access-token revocation, upload size limits, exception-detail leakage, password complexity) was addressed here — those remain tracked in `PRODUCTION_READINESS_REPORT.md`'s recommendations, as originally scoped.

## 6. Updated Status

`SECURITY_REVIEW.md` §3's High finding is **resolved and verified**. With this fix applied, there are **no remaining High-severity findings blocking production deployment**. `PRODUCTION_READINESS_REPORT.md` and `FINAL_RELEASE_CHECKLIST.md` should be considered superseded on this specific point — the "Fix before launch" item for tenant isolation is now closed.
