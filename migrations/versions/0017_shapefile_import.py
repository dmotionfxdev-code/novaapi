"""Data Acquisition context extension (Sprint B): real ESRI Shapefile
ingestion — extends the EXISTING ``acquisition_job`` table (Sprint 13/14's
own precedent for format-specific derived metadata, e.g.
``extracted_features``/``skipped_features``) with five new nullable
columns recording what the genuine ``pyogrio``/``shapely``-backed parse
(``infrastructure/shapefile_importer.py``) determined: geometry type,
feature count, bounding box, CRS, and the first feature's attribute row
(used by ``CompositionRootIndicatorInputProvider`` to feed Analysis).

No new permission catalog grants — reuses the existing ``dataset:view``/
``dataset:manage`` pair (same tenant-level catalog surface as every other
Data Acquisition table).

Revision ID: 0017_shapefile_import
Revises: 0016_remote_sensing
Create Date: 2026-07-09 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_shapefile_import"
down_revision: Union[str, None] = "0016_remote_sensing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "data_acquisition"


def upgrade() -> None:
    op.add_column(
        "acquisition_job",
        sa.Column("shapefile_geometry_type", sa.String(30), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("shapefile_feature_count", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("shapefile_bounding_box", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("shapefile_crs", sa.String(30), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "acquisition_job",
        sa.Column("shapefile_attributes", postgresql.JSONB, nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    for column in (
        "shapefile_attributes",
        "shapefile_crs",
        "shapefile_bounding_box",
        "shapefile_feature_count",
        "shapefile_geometry_type",
    ):
        op.drop_column("acquisition_job", column, schema=SCHEMA)
