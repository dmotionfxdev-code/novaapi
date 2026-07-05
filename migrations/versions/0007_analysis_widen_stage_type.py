"""Analysis Engine: widen stage_result.stage_type.

Sprint 6 (Architecture Defect found onboarding WRRAS as a second hazard
strategy): the column was sized ``VARCHAR(20)`` against FIRAS's stage
names only. WRRAS's optional supporting-analysis stage
``BURN_OCCURRENCE_PROBABILITY`` is 27 characters — longer than the column
allows. Widened to ``VARCHAR(40)`` for headroom against future stage
names.

Revision ID: 0007_analysis_widen_stage_type
Revises: 0006_analysis_formula_versioning
Create Date: 2026-07-04 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_analysis_widen_stage_type"
down_revision: Union[str, None] = "0006_analysis_formula_versioning"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "analysis"


def upgrade() -> None:
    op.alter_column(
        "stage_result",
        "stage_type",
        type_=sa.String(40),
        existing_type=sa.String(20),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.alter_column(
        "stage_result",
        "stage_type",
        type_=sa.String(20),
        existing_type=sa.String(40),
        schema=SCHEMA,
    )
