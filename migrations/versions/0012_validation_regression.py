"""Validation context: regression validation extension.

Sprint 10 ("Regression Validation Extension"): adds ``mode`` (every
pre-existing row is unambiguously ``CLASSIFICATION`` — no other mode
existed before this migration, so the server default backfills a known
fact, not a guess), plus ``regression_metrics``/``model_metadata`` JSONB
columns, populated only for ``REGRESSION``-mode runs. No new permission
codes — the new ``run-regression`` action reuses ``validation:manage``/
``validation:view`` exactly like the existing classification action.

Revision ID: 0012_validation_regression
Revises: 0011_reporting
Create Date: 2026-07-05 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_validation_regression"
down_revision: Union[str, None] = "0011_reporting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "validation"


def upgrade() -> None:
    op.add_column(
        "validation_run",
        sa.Column(
            "mode", sa.String(20), nullable=False, server_default="CLASSIFICATION"
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "validation_run",
        sa.Column("regression_metrics", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "validation_run",
        sa.Column("model_metadata", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("validation_run", "model_metadata", schema=SCHEMA)
    op.drop_column("validation_run", "regression_metrics", schema=SCHEMA)
    op.drop_column("validation_run", "mode", schema=SCHEMA)
