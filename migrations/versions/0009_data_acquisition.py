"""Data Acquisition context: dataset_source, dataset, predictor_variable,
variable_selection tables — the catalog/registry scope of Sprint 7
("Geospatial Context and Dataset Management"). No GEE integration, no
``AcquisitionJob``/``SensorStation``/``SensorReading`` tables yet — those
remain out of scope per this sprint's explicit instruction.

New permission catalog grants: ``dataset:view``/``dataset:manage`` cover
the whole catalog/registry surface (DatasetSource, Dataset,
PredictorVariable, VariableSelection) as one pair, the same "one pair per
catalog-level context surface" precedent ``workflow_template:view``/
``workflow_template:manage`` set in Sprint 3 — these are tenant-level
catalog resources, not assessment-nested evidence, so they don't reuse
``assessment:view``/``assessment:manage`` the way Geospatial's AOI/
SamplingCampaign API does.

Revision ID: 0009_data_acquisition
Revises: 0008_geospatial
Create Date: 2026-07-05 00:00:00
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_data_acquisition"
down_revision: Union[str, None] = "0008_geospatial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "data_acquisition"

# Frozen snapshot of intent at write time — never a live import from
# contexts/identity/domain (established migration-writing rule since
# 0002_assessment.py's docstring).
_DATASET_PERMISSIONS: tuple[str, ...] = ("dataset:view", "dataset:manage")

_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "VIEWER": ("dataset:view",),
    "ANALYST": ("dataset:view",),
    "ADMIN": ("dataset:view", "dataset:manage"),
    "OWNER": ("dataset:view", "dataset:manage"),
}


def upgrade() -> None:
    op.create_table(
        "dataset_source",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("description", sa.String, nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_dataset_source_tenant", "dataset_source", ["tenant_id"], schema=SCHEMA
    )

    op.create_table(
        "dataset",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("metadata_name", sa.String(200), nullable=False),
        sa.Column("dataset_type", sa.String(30), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("acquisition_date", sa.Date, nullable=False),
        sa.Column("spatial_resolution_m", sa.Float, nullable=True),
        sa.Column("temporal_resolution", sa.String(20), nullable=True),
        sa.Column("crs", sa.String(30), nullable=False),
        sa.Column("spatial_coverage", sa.String(500), nullable=False),
        sa.Column("temporal_coverage_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("temporal_coverage_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_method", sa.String(30), nullable=False),
        sa.Column("model_used", sa.String(200), nullable=True),
        sa.Column("provenance", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("readiness", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("catalogued_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_dataset_tenant_name_version",
        "dataset",
        ["tenant_id", "metadata_name", "version"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_dataset_tenant_status", "dataset", ["tenant_id", "status"], schema=SCHEMA
    )

    op.create_table(
        "predictor_variable",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("variable_role", sa.String(20), nullable=False),
        sa.Column("data_type", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(50), nullable=False, server_default=""),
        sa.Column("value_min", sa.Float, nullable=True),
        sa.Column("value_max", sa.Float, nullable=True),
        sa.Column("is_required_for_mlr", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("linked_dataset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_predictor_variable_tenant_category",
        "predictor_variable",
        ["tenant_id", "category"],
        schema=SCHEMA,
    )

    op.create_table(
        "variable_selection",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("hazard_type", sa.String(20), nullable=True),
        sa.Column("selected_variable_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_variable_selection_tenant", "variable_selection", ["tenant_id"], schema=SCHEMA
    )

    _seed_dataset_permissions()


def _seed_dataset_permissions() -> None:
    permission_table = sa.table(
        "permission",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
        schema="identity",
    )
    permission_ids: dict[str, uuid.UUID] = {code: uuid.uuid4() for code in _DATASET_PERMISSIONS}
    op.bulk_insert(
        permission_table,
        [
            {"id": permission_ids[code], "code": code, "description": code}
            for code in _DATASET_PERMISSIONS
        ],
    )

    connection = op.get_bind()
    for role_name, codes in _ROLE_GRANTS.items():
        for code in codes:
            connection.execute(
                sa.text(
                    "INSERT INTO identity.role_permission (role_id, permission_id) "
                    "SELECT r.id, :permission_id FROM identity.role r WHERE r.name = :role_name"
                ),
                {"permission_id": permission_ids[code], "role_name": role_name},
            )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM identity.role_permission WHERE permission_id IN "
            "(SELECT id FROM identity.permission WHERE code = ANY(:codes))"
        ),
        {"codes": list(_DATASET_PERMISSIONS)},
    )
    connection.execute(
        sa.text("DELETE FROM identity.permission WHERE code = ANY(:codes)"),
        {"codes": list(_DATASET_PERMISSIONS)},
    )
    op.drop_table("variable_selection", schema=SCHEMA)
    op.drop_table("predictor_variable", schema=SCHEMA)
    op.drop_table("dataset", schema=SCHEMA)
    op.drop_table("dataset_source", schema=SCHEMA)
