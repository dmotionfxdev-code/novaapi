"""Data Acquisition context extension (Sprint 14): Remote Sensing
Integration — extends the EXISTING ``acquisition_job`` table (Sprint 13)
with Google Earth Engine-specific columns rather than creating a new
table, since ``AcquisitionJob`` remains one aggregate whether its
provider is Local Upload, HTTP, or GEE.

No new permission catalog grants — reuses the existing ``dataset:view``/
``dataset:manage`` pair (same tenant-level catalog surface as every other
Data Acquisition table).

Revision ID: 0016_remote_sensing
Revises: 0015_acquisition_job
Create Date: 2026-07-05 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_remote_sensing"
down_revision: Union[str, None] = "0015_acquisition_job"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "data_acquisition"


def upgrade() -> None:
    op.add_column(
        "acquisition_job",
        sa.Column("remote_sensing_source", sa.String(20), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("aoi_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("temporal_start", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("temporal_end", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("comparison_temporal_start", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("comparison_temporal_end", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column(
            "requested_preprocessing", postgresql.JSONB, nullable=False, server_default="[]"
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("requested_indices", postgresql.JSONB, nullable=False, server_default="[]"),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("applied_preprocessing", postgresql.JSONB, nullable=False, server_default="[]"),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("extracted_features", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("skipped_features", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for column in (
        "skipped_features",
        "extracted_features",
        "applied_preprocessing",
        "requested_indices",
        "requested_preprocessing",
        "comparison_temporal_end",
        "comparison_temporal_start",
        "temporal_end",
        "temporal_start",
        "aoi_id",
        "remote_sensing_source",
    ):
        op.drop_column("acquisition_job", column, schema=SCHEMA)
