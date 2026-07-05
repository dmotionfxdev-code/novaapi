"""Validation context: validation_run table + its permission-catalog
grants.

Revision ID: 0004_validation
Revises: 0003_workflow
Create Date: 2026-01-17 00:00:00
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_validation"
down_revision: Union[str, None] = "0003_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "validation"

# Frozen snapshot of intent at write time — never a live import from
# contexts/identity/domain (CONTRIBUTING.md's migration guidance).
_VALIDATION_PERMISSIONS: tuple[str, ...] = ("validation:view", "validation:manage")

_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "VIEWER": ("validation:view",),
    "ANALYST": ("validation:view", "validation:manage"),
    "ADMIN": ("validation:view", "validation:manage"),
    "OWNER": ("validation:view", "validation:manage"),
}


def upgrade() -> None:
    op.create_table(
        "validation_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject_id", sa.String(200), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("thresholds", postgresql.JSONB, nullable=False),
        sa.Column("metrics", postgresql.JSONB, nullable=True),
        sa.Column("verdict", sa.String(10), nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("issued_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_validation_run_tenant_assessment",
        "validation_run",
        ["tenant_id", "assessment_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_validation_run_tenant_created_at",
        "validation_run",
        ["tenant_id", "created_at"],
        schema=SCHEMA,
    )

    _seed_validation_permissions()


def _seed_validation_permissions() -> None:
    permission_table = sa.table(
        "permission",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
        schema="identity",
    )
    permission_ids: dict[str, uuid.UUID] = {code: uuid.uuid4() for code in _VALIDATION_PERMISSIONS}
    op.bulk_insert(
        permission_table,
        [
            {"id": permission_ids[code], "code": code, "description": code}
            for code in _VALIDATION_PERMISSIONS
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
        {"codes": list(_VALIDATION_PERMISSIONS)},
    )
    connection.execute(
        sa.text("DELETE FROM identity.permission WHERE code = ANY(:codes)"),
        {"codes": list(_VALIDATION_PERMISSIONS)},
    )
    op.drop_table("validation_run", schema=SCHEMA)
