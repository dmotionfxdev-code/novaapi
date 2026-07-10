"""Analysis context extension (Sprint C): the ``risk_layer`` table — a
new aggregate, not an extension of the existing ``stage_result`` table
(unlike Sprint 14/B's pattern of extending ``acquisition_job``), since a
``RiskLayer`` has its own independent lifecycle/versioning from the
``StageResult`` it's derived from and most ``StageResult`` rows (every
non-RISK stage, and any RISK stage with no Shapefile-sourced geometry
dataset available) will never have one.

No new permission catalog grants — the new read-only routes reuse the
existing ``assessment:view`` permission, same as ``stage_result``'s own
routes.

Revision ID: 0018_risk_layer
Revises: 0017_shapefile_import
Create Date: 2026-07-10 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_risk_layer"
down_revision: Union[str, None] = "0017_shapefile_import"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "analysis"


def upgrade() -> None:
    op.create_table(
        "risk_layer",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hazard_type", sa.String(20), nullable=False),
        sa.Column("stage_type", sa.String(40), nullable=False),
        sa.Column("stage_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("geometry_type", sa.String(30), nullable=False),
        sa.Column("feature_count", sa.Integer(), nullable=False),
        sa.Column("bounding_box", postgresql.JSONB, nullable=False),
        sa.Column("crs", sa.String(30), nullable=False),
        sa.Column("risk_index", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("classification", sa.String(50), nullable=False),
        sa.Column("formula_version", sa.String(50), nullable=False),
        sa.Column("geojson", postgresql.JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_risk_layer_assessment_stage_version",
        "risk_layer",
        ["assessment_id", "stage_type", "version"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ix_risk_layer_assessment_stage_version", table_name="risk_layer", schema=SCHEMA)
    op.drop_table("risk_layer", schema=SCHEMA)
