"""Data Acquisition context extension (Sprint 13): ``acquisition_job``
table — the "go fetch real data" aggregate Sprint 7's docstring
explicitly deferred ("AcquisitionJob/SensorStation/SensorReading remain
out of scope").

No new permission catalog grants — the ``AcquisitionJob`` surface reuses
the existing ``dataset:view``/``dataset:manage`` pair Sprint 7 already
seeded (0009_data_acquisition.py), since scheduling/executing an
acquisition job is part of the same tenant-level dataset-catalog surface
as ``Dataset``/``DatasetSource`` themselves.

Revision ID: 0015_acquisition_job
Revises: 0014_dashboard
Create Date: 2026-07-05 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_acquisition_job"
down_revision: Union[str, None] = "0014_dashboard"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "data_acquisition"


def upgrade() -> None:
    op.create_table(
        "acquisition_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("source_reference", sa.String, nullable=False),
        sa.Column("format", sa.String(20), nullable=False),
        sa.Column("dataset_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("declared_crs", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("raw_content_base64", sa.Text, nullable=True),
        sa.Column("provenance", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_acquisition_job_tenant_status",
        "acquisition_job",
        ["tenant_id", "status"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("acquisition_job", schema=SCHEMA)
