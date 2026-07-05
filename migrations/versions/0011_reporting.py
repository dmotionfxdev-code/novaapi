"""Reporting context: report table.

No new permission codes — the API reuses ``assessment:view``/
``assessment:manage`` (a ``Report`` is assessment-scoped evidence, the
same reasoning Sprint 5/7/8's read APIs already used).

Revision ID: 0011_reporting
Revises: 0010_prediction
Create Date: 2026-07-05 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_reporting"
down_revision: Union[str, None] = "0010_prediction"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "reporting"


def upgrade() -> None:
    op.create_table(
        "report",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by", sa.String(200), nullable=False),
        sa.Column("assessment_summary", postgresql.JSONB, nullable=True),
        sa.Column("risk_summary", postgresql.JSONB, nullable=True),
        sa.Column("predictor_summary", postgresql.JSONB, nullable=True),
        sa.Column("dataset_provenance", postgresql.JSONB, nullable=True),
        sa.Column("validation_summary", postgresql.JSONB, nullable=True),
        sa.Column("formula_versions", postgresql.JSONB, nullable=True),
        sa.Column("strategy_version", sa.String(50), nullable=True),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("finalized_by", sa.String(200), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_report_assessment", "report", ["assessment_id"], schema=SCHEMA)
    op.create_index(
        "ix_report_tenant_assessment_version",
        "report",
        ["tenant_id", "assessment_id", "version"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("report", schema=SCHEMA)
