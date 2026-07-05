# Contributing

## Standards

- Type hints are mandatory on every function signature (`mypy` is a CI gate, not a suggestion).
- No comments explaining *what* code does — names carry that. A comment is justified only for a non-obvious *why* (a workaround, an external constraint, a deliberately counterintuitive ordering).
- Naming: `CreateAssessment` (a command), `CreateAssessmentHandler` (its handler), `AssessmentRepository` (a domain-layer interface), `SqlAlchemyAssessmentRepository` (its infrastructure implementation), `GetAssessmentWorkspace` (a query). A file's name matches the one concept it defines — no `utils.py`, no `helpers.py` under `contexts/`.
- One transaction per command handler (Application Layer §9). A handler that loads two aggregate repositories is a review-blocking finding, not a style nitpick.
- Every external adapter wraps its calls behind the interface its context's domain layer defines — enforced by the `forbidden` import-linter contract in `pyproject.toml` for the libraries it currently covers (`ee`, `requests`); extend that contract's `forbidden_modules` list as new external SDKs are introduced.
- Commits follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`) as team practice — not yet CI-enforced.

## Architecture Decision Records

Any decision that deviates from or extends `docs/architecture/`'s eleven design documents gets a short ADR in `docs/architecture/adr/NNNN-title.md`: a paragraph of context, the decision, the consequence.

## Database migrations

- Single linear Alembic history — no branching heads. `alembic heads` must report exactly one head; CI checks this.
- Large-table migrations use the online-migration pattern: add nullable, backfill in batches, add constraint `NOT VALID`, then `VALIDATE CONSTRAINT` separately.
- Autogenerate output is **always reviewed manually** before commit, never applied blind — this matters especially for anything RLS- or generated-column-related (Roadmap Sprint 11 onward).
- No `DELETE`/`UPDATE` grants are ever added for the application role on append-only tables (`outbox_event`, and `audit_entry` once it exists) — this is a database-level guarantee, not a code-review one.
- **A migration's seed data must be a frozen snapshot of intent at the time it was written — never a live import from `contexts/*/domain`.** A migration that imports a mutable catalog (e.g. `PermissionCode`, `ROLE_PERMISSIONS`) and iterates over "all current members" will silently re-seed whatever that catalog has grown to contain by the time it next runs against a fresh database, colliding with every later migration that added to the same catalog on the table's unique constraints. Hardcode the literal values the migration seeds, even though that means duplicating a handful of strings that also appear in application code. (Caught in Roadmap Sprint 2: `0001_identity_and_outbox.py` originally imported `ROLE_PERMISSIONS` live; extending that dict in Sprint 2 for a second context's permissions would have made 0001 re-seed them and collide with `0002_assessment.py`'s own inserts. Fixed by freezing 0001's seed data as of Sprint 1.)

## The one Sprint 0 landmine to know about

`migrations/versions/0000_baseline.py` creates logical schemas using an f-string-interpolated `CREATE SCHEMA` statement. This is safe **only** because the schema names come from a hardcoded tuple in that same file. If Roadmap Sprint 11's schema-per-tenant provisioning is ever implemented by copying this pattern with a tenant-supplied identifier substituted in, it becomes a SQL-injection vector at exactly the point where tenant isolation is being built. Any dynamic schema/identifier name must be strictly validated against an allowlist (never free-text) before being used in DDL. (Sprint 0 Review finding #7 / Remediation Plan #7.)

## Testing

- `pytest -m unit` — pure logic, no I/O.
- `pytest -m integration` — needs a real Postgres/Redis (`docker compose up postgres redis` first, or let CI's service containers provide them).
- `pytest -m architecture` — import-boundary and structural rules; includes both a positive case (the current codebase passes) and a negative case (a deliberately-violating fixture module is proven to fail the linter).
