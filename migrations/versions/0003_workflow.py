"""Workflow Engine: workflow_template table, Assessment table extensions,
and this sprint's permission-catalog grants.

Revision ID: 0003_workflow
Revises: 0002_assessment
Create Date: 2026-01-10 00:00:00
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_workflow"
down_revision: Union[str, None] = "0002_assessment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "assessment"

# Frozen snapshot of intent at write time — never a live import from
# contexts/identity/domain (CONTRIBUTING.md's migration guidance,
# established after 0001's original mistake; see 0002_assessment.py's
# docstring for the incident this rule comes from).
_WORKFLOW_TEMPLATE_PERMISSIONS: tuple[str, ...] = (
    "workflow_template:manage",
    "workflow_template:view",
)

_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "VIEWER": ("workflow_template:view",),
    "ANALYST": ("workflow_template:view",),
    "ADMIN": ("workflow_template:view", "workflow_template:manage"),
    "OWNER": ("workflow_template:view", "workflow_template:manage"),
}


def upgrade() -> None:
    op.create_table(
        "workflow_template",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("hazard_type", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage_definitions", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_workflow_template_hazard_status",
        "workflow_template",
        ["hazard_type", "status"],
        schema=SCHEMA,
    )

    op.add_column(
        "assessment",
        sa.Column("workflow_template_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "assessment",
        sa.Column(
            "workflow_progress",
            postgresql.JSONB,
            nullable=False,
            server_default="{}",
        ),
        schema=SCHEMA,
    )

    _seed_workflow_template_permissions()


def _seed_workflow_template_permissions() -> None:
    permission_table = sa.table(
        "permission",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
        schema="identity",
    )
    permission_ids: dict[str, uuid.UUID] = {
        code: uuid.uuid4() for code in _WORKFLOW_TEMPLATE_PERMISSIONS
    }
    op.bulk_insert(
        permission_table,
        [
            {"id": permission_ids[code], "code": code, "description": code}
            for code in _WORKFLOW_TEMPLATE_PERMISSIONS
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
        {"codes": list(_WORKFLOW_TEMPLATE_PERMISSIONS)},
    )
    connection.execute(
        sa.text("DELETE FROM identity.permission WHERE code = ANY(:codes)"),
        {"codes": list(_WORKFLOW_TEMPLATE_PERMISSIONS)},
    )
    op.drop_column("assessment", "workflow_progress", schema=SCHEMA)
    op.drop_column("assessment", "workflow_template_id", schema=SCHEMA)
    op.drop_table("workflow_template", schema=SCHEMA)
