"""Analysis Engine: StageResult formula/strategy version tracking.

Sprint 5.2 (``GEORISK_SCOPE_REALIGNMENT.md`` §6): FIRAS's Risk and
Vulnerability formulas were corrected to match the approved specification
(multiplicative FRI, entropy-weighted FVI). ``strategy_version`` and
``formula_version`` let every future ``StageResult`` stay traceable to
exactly which formula generation produced it. Nullable — rows created
before this migration predate version tracking entirely and have no
recorded value to backfill; a NULL here honestly means "not tracked,"
never a guessed label.

Revision ID: 0006_analysis_formula_versioning
Revises: 0005_analysis
Create Date: 2026-07-04 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_analysis_formula_versioning"
down_revision: Union[str, None] = "0005_analysis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "analysis"


def upgrade() -> None:
    op.add_column(
        "stage_result",
        sa.Column("strategy_version", sa.String(50), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "stage_result",
        sa.Column("formula_version", sa.String(50), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("stage_result", "formula_version", schema=SCHEMA)
    op.drop_column("stage_result", "strategy_version", schema=SCHEMA)
