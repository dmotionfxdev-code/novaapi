"""Geospatial context: aoi, sampling_campaign tables.

No new permission codes — the API reuses ``assessment:view``/
``assessment:manage`` (AOI and SamplingCampaign are assessment-scoped
evidence, the same reasoning Sprint 5's Analysis Engine read API already
used for ``StageResult``).

Revision ID: 0008_geospatial
Revises: 0007_analysis_widen_stage_type
Create Date: 2026-07-05 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_geospatial"
down_revision: Union[str, None] = "0007_analysis_widen_stage_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "geospatial"


def upgrade() -> None:
    op.create_table(
        "aoi",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("geometry", postgresql.JSONB, nullable=False),
        sa.Column("metadata_name", sa.String(200), nullable=False),
        sa.Column("metadata_source", sa.String(20), nullable=False),
        sa.Column("metadata_notes", sa.String, nullable=False, server_default=""),
        sa.Column("area_m2", sa.Float, nullable=False),
        sa.Column("perimeter_m", sa.Float, nullable=False),
        sa.Column("centroid_longitude", sa.Float, nullable=False),
        sa.Column("centroid_latitude", sa.Float, nullable=False),
        sa.Column("bbox", postgresql.JSONB, nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_aoi_assessment_version", "aoi", ["assessment_id", "version"], schema=SCHEMA
    )
    op.create_index(
        "ix_aoi_tenant_assessment_status",
        "aoi",
        ["tenant_id", "assessment_id", "status"],
        schema=SCHEMA,
    )

    op.create_table(
        "sampling_campaign",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aoi_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("strategy", postgresql.JSONB, nullable=False),
        sa.Column("strata", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("sample_points", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_sampling_campaign_tenant_assessment",
        "sampling_campaign",
        ["tenant_id", "assessment_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("sampling_campaign", schema=SCHEMA)
    op.drop_table("aoi", schema=SCHEMA)
