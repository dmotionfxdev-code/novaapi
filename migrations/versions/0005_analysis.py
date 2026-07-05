"""Analysis Engine: stage_result table.

No new permission codes — the read API reuses ``assessment:view``
(a ``StageResult`` is read-only evidence about an assessment a caller can
already see, the same reasoning Sprint 3's workflow-progress endpoint
already used).

Revision ID: 0005_analysis
Revises: 0004_validation
Create Date: 2026-01-24 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_analysis"
down_revision: Union[str, None] = "0004_validation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "analysis"


def upgrade() -> None:
    op.create_table(
        "stage_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hazard_type", sa.String(20), nullable=False),
        sa.Column("stage_type", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("indicators", postgresql.JSONB, nullable=True),
        sa.Column("confidence_tier", sa.String(10), nullable=True),
        sa.Column("snapshot", postgresql.JSONB, nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("issued_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_stage_result_assessment_stage_version",
        "stage_result",
        ["assessment_id", "stage_type", "version"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_stage_result_tenant_hazard_stage",
        "stage_result",
        ["tenant_id", "hazard_type", "stage_type"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("stage_result", schema=SCHEMA)
