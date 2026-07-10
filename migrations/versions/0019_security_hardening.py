"""Identity context extension (Sprint D): genuine access-token revocation.

Two additive mechanisms, matching the two distinct revocation shapes Sprint
D requires:

* ``identity.user.token_generation`` — a per-user counter bumped on any
  bulk-revocation event (password reset, account suspend/deactivate,
  explicit "revoke all sessions"). Every access token embeds the
  generation value active at issue time (the ``gen`` JWT claim); a token
  whose ``gen`` no longer matches the user's current counter is stale and
  rejected, without needing to enumerate individual tokens.
* ``identity.revoked_access_token`` — a small denylist for revoking one
  specific token (logout), keyed by the JWT's own ``jti``. Deliberately not
  reusing the counter mechanism for this case: logout must end only the
  caller's current session, not every session for that user.

No existing table/column is altered or dropped — both additions are
backward compatible with every row already in the database (``token_
generation`` defaults to 0, matching what every already-issued token
implicitly carries as "no generation claim" during the brief upgrade
window, since 0 is also what the JWT decoder treats a missing ``gen``
claim as — see ``infrastructure/security.py``).

Revision ID: 0019_security_hardening
Revises: 0018_risk_layer
Create Date: 2026-07-10 00:00:00
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_security_hardening"
down_revision: Union[str, None] = "0018_risk_layer"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "identity"


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("token_generation", sa.Integer(), nullable=False, server_default="0"),
        schema=SCHEMA,
    )

    op.create_table(
        "revoked_access_token",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA}.user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_revoked_access_token_user_id",
        "revoked_access_token",
        ["user_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_revoked_access_token_user_id", table_name="revoked_access_token", schema=SCHEMA
    )
    op.drop_table("revoked_access_token", schema=SCHEMA)
    op.drop_column("user", "token_generation", schema=SCHEMA)
