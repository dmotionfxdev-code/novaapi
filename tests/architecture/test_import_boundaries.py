"""Proves the import-boundary guardrails (pyproject.toml's `[tool.importlinter]`
contracts) actually work — both that they pass on the current, clean
codebase, and that they genuinely reject real violations.

Sprint 0 Review finding #25 / Remediation #25: the original draft left the
negative case as an unimplemented stub (`...`). This is the real
implementation — Roadmap Sprint 0's own acceptance criterion is "CI blocks
a PR that imports a contexts/* internal module from outside its own
context," proven by a test, not merely asserted in prose.

Sprint 2 update: Sprint 0/1 originally put `identity` in the same
`independence` contract as every other context, and this file's negative
case exercised exactly that (`assessment` importing `identity`). Sprint 2
corrected that — Domain Model §7 classifies Identity as a *shared kernel*
relative to everyone else, not a peer under mutual independence — so
`assessment` importing `identity` is now legitimate and would no longer
fail. This file now proves both halves of the corrected rule: peer
contexts still can't import each other (`assessment` -> `geospatial`), and
identity still can't depend on anyone downstream of it
(`identity` -> `assessment`), which is the new asymmetric guarantee the
`forbidden` contract exists to enforce.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.architecture

REPO_ROOT = Path(__file__).resolve().parents[2]
PEER_VIOLATION_MODULE = (
    REPO_ROOT
    / "src"
    / "georisk"
    / "contexts"
    / "assessment"
    / "domain"
    / "_boundary_violation_fixture.py"
)
SHARED_KERNEL_VIOLATION_MODULE = (
    REPO_ROOT
    / "src"
    / "georisk"
    / "contexts"
    / "identity"
    / "domain"
    / "_boundary_violation_fixture.py"
)


def _run_lint_imports() -> subprocess.CompletedProcess[str]:
    # `importlinter` is a package with no runnable `__main__`, so
    # `python -m importlinter` does not work (confirmed by hand while
    # validating this test — an earlier draft tried exactly that and failed
    # with "No module named importlinter.__main__"). The correct, and
    # CI-identical, invocation is its `lint-imports` console script
    # (see .github/workflows/ci.yml's import-boundaries job and
    # importlinter's own packaging metadata: `lint-imports =
    # importlinter.cli:lint_imports_command`).
    return subprocess.run(
        ["lint-imports"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _write_and_check_violation(
    module_path: Path, import_line: str
) -> subprocess.CompletedProcess[str]:
    assert not module_path.exists(), (
        f"Fixture file {module_path} already present before the test ran — a "
        "previous run may have failed to clean up. Remove it and re-run."
    )
    module_path.write_text(
        f"# Deliberately violates an import-boundary contract for this test.\n{import_line}\n"
    )
    try:
        return _run_lint_imports()
    finally:
        module_path.unlink(missing_ok=True)
        pycache_dir = module_path.parent / "__pycache__"
        if pycache_dir.exists():
            for cached in pycache_dir.glob(f"{module_path.stem}.*"):
                cached.unlink(missing_ok=True)


def test_import_linter_passes_on_the_current_clean_codebase() -> None:
    result = _run_lint_imports()
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_linter_rejects_a_peer_context_importing_another_peer() -> None:
    """`assessment` importing `geospatial` — both are peer contexts under
    the `independence` contract; neither may import the other's internals.
    """
    result = _write_and_check_violation(
        PEER_VIOLATION_MODULE, "import georisk.contexts.geospatial.domain  # noqa: F401"
    )
    assert result.returncode != 0, (
        "Expected lint-imports to reject a peer-to-peer cross-context import, but "
        "it passed — the independence contract is not actually enforcing the "
        "isolation rule it claims to."
    )
    assert "assessment" in result.stdout.lower() or "geospatial" in result.stdout.lower()


def test_import_linter_rejects_identity_depending_on_a_downstream_context() -> None:
    """`identity` importing `assessment` — identity is a shared kernel
    every other context may depend on, but the reverse direction must stay
    forbidden, or "shared kernel" degrades into an ordinary circular
    dependency between two contexts that both happen to import each other.
    """
    result = _write_and_check_violation(
        SHARED_KERNEL_VIOLATION_MODULE, "import georisk.contexts.assessment.domain  # noqa: F401"
    )
    assert result.returncode != 0, (
        "Expected lint-imports to reject identity depending on assessment, but it "
        "passed — the shared-kernel asymmetry (everyone may depend on identity, "
        "identity depends on no one) is not actually being enforced."
    )
    assert "identity" in result.stdout.lower() or "assessment" in result.stdout.lower()


def test_import_linter_still_allows_a_peer_context_depending_on_identity() -> None:
    """The whole point of Sprint 2's correction: `assessment` importing
    `identity` must be LEGAL now, not a violation — this is what an earlier
    version of this test file incorrectly exercised as the negative case.
    """
    module_path = (
        REPO_ROOT
        / "src"
        / "georisk"
        / "contexts"
        / "assessment"
        / "domain"
        / "_shared_kernel_dependency_fixture.py"
    )
    assert not module_path.exists()
    module_path.write_text("import georisk.contexts.identity.domain.value_objects  # noqa: F401\n")
    try:
        result = _run_lint_imports()
        assert result.returncode == 0, (
            "assessment depending on identity should be legal under the "
            "shared-kernel relationship (Domain Model §7), but lint-imports "
            f"rejected it:\n{result.stdout}{result.stderr}"
        )
    finally:
        module_path.unlink(missing_ok=True)
        pycache_dir = module_path.parent / "__pycache__"
        if pycache_dir.exists():
            for cached in pycache_dir.glob(f"{module_path.stem}.*"):
                cached.unlink(missing_ok=True)
