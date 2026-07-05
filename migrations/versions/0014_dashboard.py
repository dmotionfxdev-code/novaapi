"""Dashboard & Visualization context: permission catalog grant only — no
tables. Sprint 12 is a pure projection/read-model layer with no aggregate
of its own to persist (every dashboard is computed fresh, on demand, from
other contexts' already-persisted data), so there is nothing to
``CREATE TABLE`` here.

New permission catalog grant: a single ``dashboard:view`` code, granted to
every role including VIEWER — a dashboard is inherently a read/
observability feature, and unlike every other tenant-level catalog
surface in this codebase there is no corresponding "manage" verb, because
there is nothing to manage.

Revision ID: 0014_dashboard
Revises: 0013_notification
Create Date: 2026-07-05 00:00:00
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_dashboard"
down_revision: Union[str, None] = "0013_notification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of intent at write time — never a live import from
# contexts/identity/domain (established migration-writing rule since
# 0002_assessment.py's docstring).
_DASHBOARD_PERMISSIONS: tuple[str, ...] = ("dashboard:view",)

_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "VIEWER": ("dashboard:view",),
    "ANALYST": ("dashboard:view",),
    "ADMIN": ("dashboard:view",),
    "OWNER": ("dashboard:view",),
}


def upgrade() -> None:
    _seed_dashboard_permissions()


def _seed_dashboard_permissions() -> None:
    permission_table = sa.table(
        "permission",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
        schema="identity",
    )
    permission_ids: dict[str, uuid.UUID] = {
        code: uuid.uuid4() for code in _DASHBOARD_PERMISSIONS
    }
    op.bulk_insert(
        permission_table,
        [
            {"id": permission_ids[code], "code": code, "description": code}
            for code in _DASHBOARD_PERMISSIONS
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
        {"codes": list(_DASHBOARD_PERMISSIONS)},
    )
    connection.execute(
        sa.text("DELETE FROM identity.permission WHERE code = ANY(:codes)"),
        {"codes": list(_DASHBOARD_PERMISSIONS)},
    )
