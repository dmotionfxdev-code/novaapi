"""Notification & Early Warning context: alert_rule,
notification_subscription, notification tables + permission catalog
grants.

New permission catalog grants: three tenant-level catalog/history
surfaces (``AlertRule``, ``NotificationSubscription``, ``Notification``
history), each getting its own view/manage pair — matching
``workflow_template:view``/``manage``'s precedent for a catalog resource
that isn't assessment-nested evidence.

Revision ID: 0013_notification
Revises: 0012_validation_regression
Create Date: 2026-07-05 00:00:00
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_notification"
down_revision: Union[str, None] = "0012_validation_regression"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "notification"

# Frozen snapshot of intent at write time — never a live import from
# contexts/identity/domain (established migration-writing rule since
# 0002_assessment.py's docstring).
_NOTIFICATION_PERMISSIONS: tuple[str, ...] = (
    "alert_rule:view",
    "alert_rule:manage",
    "notification_subscription:view",
    "notification_subscription:manage",
    "notification:view",
    "notification:manage",
)

_ROLE_GRANTS: dict[str, tuple[str, ...]] = {
    "VIEWER": (
        "alert_rule:view",
        "notification_subscription:view",
        "notification:view",
    ),
    "ANALYST": (
        "alert_rule:view",
        "alert_rule:manage",
        "notification_subscription:view",
        "notification_subscription:manage",
        "notification:view",
        "notification:manage",
    ),
    "ADMIN": (
        "alert_rule:view",
        "alert_rule:manage",
        "notification_subscription:view",
        "notification_subscription:manage",
        "notification:view",
        "notification:manage",
    ),
    "OWNER": (
        "alert_rule:view",
        "alert_rule:manage",
        "notification_subscription:view",
        "notification_subscription:manage",
        "notification:view",
        "notification:manage",
    ),
}


def upgrade() -> None:
    op.create_table(
        "alert_rule",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("hazard_type", sa.String(30), nullable=True),
        sa.Column("stage_type", sa.String(40), nullable=True),
        sa.Column("metric_code", sa.String(100), nullable=False),
        sa.Column("operator", sa.String(30), nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_by", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_alert_rule_tenant_active", "alert_rule", ["tenant_id", "is_active"], schema=SCHEMA
    )

    op.create_table(
        "notification_subscription",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hazard_type", sa.String(30), nullable=True),
        sa.Column("channels", postgresql.JSONB, nullable=False),
        sa.Column("email_address", sa.String(320), nullable=True),
        sa.Column("phone_number", sa.String(30), nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_notification_subscription_tenant_active",
        "notification_subscription",
        ["tenant_id", "is_active"],
        schema=SCHEMA,
    )

    op.create_table(
        "notification",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assessment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_rule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("metric_code", sa.String(100), nullable=False),
        sa.Column("triggered_value", sa.Float, nullable=False),
        sa.Column("threshold", sa.Float, nullable=False),
        sa.Column("operator", sa.String(30), nullable=False),
        sa.Column("message", sa.String, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_notification_assessment", "notification", ["assessment_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_notification_tenant_created_at",
        "notification",
        ["tenant_id", "created_at"],
        schema=SCHEMA,
    )

    _seed_notification_permissions()


def _seed_notification_permissions() -> None:
    permission_table = sa.table(
        "permission",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
        schema="identity",
    )
    permission_ids: dict[str, uuid.UUID] = {
        code: uuid.uuid4() for code in _NOTIFICATION_PERMISSIONS
    }
    op.bulk_insert(
        permission_table,
        [
            {"id": permission_ids[code], "code": code, "description": code}
            for code in _NOTIFICATION_PERMISSIONS
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
        {"codes": list(_NOTIFICATION_PERMISSIONS)},
    )
    connection.execute(
        sa.text("DELETE FROM identity.permission WHERE code = ANY(:codes)"),
        {"codes": list(_NOTIFICATION_PERMISSIONS)},
    )
    op.drop_table("notification", schema=SCHEMA)
    op.drop_table("notification_subscription", schema=SCHEMA)
    op.drop_table("alert_rule", schema=SCHEMA)
