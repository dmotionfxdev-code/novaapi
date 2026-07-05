"""Identity context tables + the platform-wide outbox table.

Revision ID: 0001_identity_and_outbox
Revises: 0000_baseline
Create Date: 2026-01-02 00:00:00
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_identity_and_outbox"
down_revision: Union[str, None] = "0000_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "identity"


def upgrade() -> None:
    # --- Platform-wide outbox (Infrastructure Architecture §8/§9) --------
    op.create_table(
        "outbox_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregate_type", sa.String(100), nullable=False),
        sa.Column("aggregate_id", sa.String(100), nullable=False),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sequence_number", sa.BigInteger, nullable=False),
        sa.Column("relayed_at", sa.DateTime(timezone=True), nullable=True),
        schema="public",
    )
    op.create_index(
        "ix_outbox_event_aggregate",
        "outbox_event",
        ["aggregate_type", "aggregate_id", "sequence_number"],
        schema="public",
    )
    op.create_index("ix_outbox_event_unrelayed", "outbox_event", ["relayed_at"], schema="public")
    op.create_index("ix_outbox_event_tenant", "outbox_event", ["tenant_id", "occurred_at"], schema="public")

    # --- Platform-wide idempotency dedupe store (Application Layer §11) ---
    op.create_table(
        "idempotency_key",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("command_type", sa.String(150), nullable=False),
        sa.Column("response_body", postgresql.JSONB, nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", "command_type", name="uq_idempotency_key_command_type"),
        schema="public",
    )

    # --- identity.tenant ---------------------------------------------------
    op.create_table(
        "tenant",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(50), nullable=False, server_default=""),
        sa.Column("address", sa.Text, nullable=False, server_default=""),
        sa.Column("logo_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )

    # --- identity.role / identity.permission / identity.role_permission ---
    op.create_table(
        "role",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        schema=SCHEMA,
    )
    op.create_table(
        "permission",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        schema=SCHEMA,
    )
    op.create_table(
        "role_permission",
        sa.Column(
            "role_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.role.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "permission_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.permission.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        schema=SCHEMA,
    )

    # --- identity.user -------------------------------------------------------
    op.create_table(
        "user",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.tenant.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.role.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("email", name="uq_user_email"),
        schema=SCHEMA,
    )
    op.create_index("ix_user_tenant_id", "user", ["tenant_id"], schema=SCHEMA)

    # --- identity.refresh_token ------------------------------------------
    op.create_table(
        "refresh_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replaced_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.refresh_token.id"), nullable=True
        ),
        schema=SCHEMA,
    )
    op.create_index("ix_refresh_token_user_id", "refresh_token", ["user_id"], schema=SCHEMA)
    op.create_index("ix_refresh_token_expires_at", "refresh_token", ["expires_at"], schema=SCHEMA)

    # --- identity.password_reset_token ------------------------------------
    op.create_table(
        "password_reset_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_password_reset_token_user_id", "password_reset_token", ["user_id"], schema=SCHEMA)

    # --- identity.invitation_token -----------------------------------------
    op.create_table(
        "invitation_token",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey(f"{SCHEMA}.user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index("ix_invitation_token_user_id", "invitation_token", ["user_id"], schema=SCHEMA)

    _seed_roles_and_permissions()


def _seed_roles_and_permissions() -> None:
    """Seeds the role catalog and Identity's OWN permission codes as they
    stood at the time this migration was written.

    Sprint 2 correction: this function originally imported
    ``ROLE_PERMISSIONS``/``PermissionCode``/``RoleName`` live from
    ``contexts.identity.domain.value_objects`` on the theory that the
    migration and any in-process check would then never drift apart. That
    reasoning was wrong for a migration specifically: those names are
    *mutable over time* as more contexts extend the shared permission
    catalog (exactly as Sprint 2's Assessment migration, 0002, does). Left
    as a live import, this function would silently re-seed every
    permission code that exists *today* — including ones added by later
    migrations — the next time it ran against a fresh database, colliding
    with those later migrations' own inserts on the ``code`` unique
    constraint. A migration must be a frozen snapshot of intent at the
    time it was written, never a live view of current application state;
    see CONTRIBUTING.md's migration guidance and 0002_assessment.py's
    module docstring, which states the correct pattern this function now
    also follows: hardcoded literals, not an import.
    """
    role_table = sa.table(
        "role",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        schema=SCHEMA,
    )
    permission_table = sa.table(
        "permission",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("description", sa.Text),
        schema=SCHEMA,
    )
    role_permission_table = sa.table(
        "role_permission",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("permission_id", postgresql.UUID(as_uuid=True)),
        schema=SCHEMA,
    )

    role_names = ("OWNER", "ADMIN", "ANALYST", "VIEWER")
    identity_permission_codes = (
        "tenant:manage",
        "user:invite",
        "user:manage_role",
        "user:manage_status",
        "user:view",
        "role:view",
    )
    # Identity's own role grants, as seeded at Sprint 1 — a frozen snapshot,
    # not the (now larger, Sprint-2-extended) live ROLE_PERMISSIONS dict.
    role_grants: dict[str, tuple[str, ...]] = {
        "VIEWER": ("user:view", "role:view"),
        "ANALYST": ("user:view", "role:view"),
        "ADMIN": ("user:view", "role:view", "user:invite", "user:manage_role", "user:manage_status"),
        "OWNER": (
            "user:view",
            "role:view",
            "user:invite",
            "user:manage_role",
            "user:manage_status",
            "tenant:manage",
        ),
    }

    role_ids: dict[str, uuid.UUID] = {name: uuid.uuid4() for name in role_names}
    permission_ids: dict[str, uuid.UUID] = {code: uuid.uuid4() for code in identity_permission_codes}

    op.bulk_insert(
        role_table,
        [{"id": role_ids[name], "name": name, "description": f"System role: {name.title()}"} for name in role_names],
    )
    op.bulk_insert(
        permission_table,
        [{"id": permission_ids[code], "code": code, "description": code} for code in identity_permission_codes],
    )
    op.bulk_insert(
        role_permission_table,
        [
            {"role_id": role_ids[role_name], "permission_id": permission_ids[code]}
            for role_name, codes in role_grants.items()
            for code in codes
        ],
    )


def downgrade() -> None:
    op.drop_table("invitation_token", schema=SCHEMA)
    op.drop_table("password_reset_token", schema=SCHEMA)
    op.drop_table("refresh_token", schema=SCHEMA)
    op.drop_table("user", schema=SCHEMA)
    op.drop_table("role_permission", schema=SCHEMA)
    op.drop_table("permission", schema=SCHEMA)
    op.drop_table("role", schema=SCHEMA)
    op.drop_table("tenant", schema=SCHEMA)
    op.drop_table("idempotency_key", schema="public")
    op.drop_table("outbox_event", schema="public")
