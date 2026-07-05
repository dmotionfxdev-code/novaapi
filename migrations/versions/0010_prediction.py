"""Prediction context: prediction_run table.

No new permission codes — the API reuses ``assessment:view``/
``assessment:manage`` (a ``PredictionRun`` is assessment-scoped evidence,
the same reasoning Sprint 5's Analysis Engine and Sprint 7's Geospatial
read APIs already used).

Revision ID: 0010_prediction
Revises: 0009_data_acquisition
Create Date: 2026-07-05 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_prediction"
down_revision: Union[str, None] = "0009_data_acquisition"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "prediction"


def upgrade() -> None:
    op.create_table(
        "prediction_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("variable_selection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sampling_campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("model_metadata", postgresql.JSONB, nullable=True),
        sa.Column("correlation_result", postgresql.JSONB, nullable=True),
        sa.Column("regression_result", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("issued_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_prediction_run_assessment", "prediction_run", ["assessment_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_prediction_run_tenant_selection_method",
        "prediction_run",
        ["tenant_id", "variable_selection_id", "method", "version"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("prediction_run", schema=SCHEMA)
