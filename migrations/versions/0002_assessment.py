"""Assessment context table + its permission-catalog grants.

Revision ID: 0002_assessment
Revises: 0001_identity_and_outbox
Create Date: 2026-01-03 00:00:00
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_assessment"
down_revision: Union[str, None] = "0001_identity_and_outbox"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "assessment"

# The four Assessment permission codes and which roles get them — mirrors
# georisk.contexts.identity.domain.value_objects.ROLE_PERMISSIONS's
# ASSESSMENT_* entries as of when this migration was written. Duplicated
# here as plain strings, never imported: a migration must be a frozen
# snapshot of intent at write time, not a live view of current application
# state, or it silently re-seeds whatever the domain module has grown to
# contain by the time it next runs against a fresh database — see
# CONTRIBUTING.md's migration guidance. 0001_identity_and_outbox.py
# originally got this wrong (it imported ROLE_PERMISSIONS live) and was
# corrected in this same sprint specifically because extending that dict
# with these four codes would otherwise have made 0001 re-seed them itself
# and collide with this migration's own inserts.
_ASSESSMENT_PERMISSIONS: dict[str, str] = {
    "assessment:view": "assessment:view",
    "assessment:manage": "assessment:manage",
    "assessment:archive": "assessment:archive",
    "assessment:cancel": "assessment:cancel",
}

_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "VIEWER": ("assessment:view",),
    "ANALYST": ("assessment:view", "assessment:manage", "assessment:archive", "assessment:cancel"),
    "ADMIN": ("assessment:view", "assessment:manage", "assessment:archive", "assessment:cancel"),
    "OWNER": ("assessment:view", "assessment:manage", "assessment:archive", "assessment:cancel"),
}


def upgrade() -> None:
    op.create_table(
        "assessment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("hazard_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancellation_reason", sa.Text, nullable=False, server_default=""),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        schema=SCHEMA,
    )
    op.create_index("ix_assessment_tenant_status", "assessment", ["tenant_id", "status"], schema=SCHEMA)
    op.create_index("ix_assessment_tenant_created_at", "assessment", ["tenant_id", "created_at"], schema=SCHEMA)

    _seed_assessment_permissions()


def _seed_assessment_permissions() -> None:
    """Adds this context's four permission codes to the existing
    ``identity.permission`` catalog (created by 0001) and grants them to
    the existing seeded roles — a data seed against another context's
    schema, not a code dependency on it (see this file's module docstring).
    Uses ``INSERT ... SELECT`` against ``identity.role`` rather than
    hardcoding role UUIDs, since those were generated randomly by 0001 and
    aren't known ahead of time.
    """
    permission_table = sa.table(
        "permission",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
        schema="identity",
    )
    permission_ids: dict[str, uuid.UUID] = {code: uuid.uuid4() for code in _ASSESSMENT_PERMISSIONS}
    op.bulk_insert(
        permission_table,
        [{"id": permission_ids[code], "code": code, "description": code} for code in _ASSESSMENT_PERMISSIONS],
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
        {"codes": list(_ASSESSMENT_PERMISSIONS.keys())},
    )
    connection.execute(
        sa.text("DELETE FROM identity.permission WHERE code = ANY(:codes)"),
        {"codes": list(_ASSESSMENT_PERMISSIONS.keys())},
    )
    op.drop_table("assessment", schema=SCHEMA)
