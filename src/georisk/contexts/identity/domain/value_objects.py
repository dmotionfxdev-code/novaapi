"""Value objects for the Identity context.

Typed IDs follow the shared_kernel.ids.TypedId pattern (Domain Model §3) —
a UserId can never be accidentally passed where a TenantId is expected.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class TenantId(TypedId):
    pass


class UserId(TypedId):
    pass


class RoleId(TypedId):
    pass


class PermissionId(TypedId):
    pass


class RefreshTokenId(TypedId):
    pass


class PasswordResetTokenId(TypedId):
    pass


class InvitationTokenId(TypedId):
    pass


class RoleName(StrEnum):
    """The platform's fixed role catalog (API Resource Model §12's RBAC
    table). System-seeded, not user-creatable in this sprint — per-tenant
    custom roles are not part of any approved design document and are
    explicitly out of scope.
    """

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class PermissionCode(StrEnum):
    """The platform's permission catalog. Every bounded context that needs
    authorization checks adds its own codes here as it lands — Permission
    is generic, shared infrastructure that Identity owns because
    authorization is resolved here, not because every permission concerns
    identity itself. Sprint 1 predicted this exact extension in its own
    docstring; Sprint 2 (Assessment) is the first context to actually do
    it. Each block below is one context's contribution — grouped and
    commented so the catalog stays legible as more contexts land, since
    ``Role.permissions: frozenset[PermissionCode]`` needs one closed,
    centrally-verifiable type rather than each context inventing its own
    incompatible permission-code representation.
    """

    # --- Identity (Roadmap Sprint 1) ---
    TENANT_MANAGE = "tenant:manage"
    USER_INVITE = "user:invite"
    USER_MANAGE_ROLE = "user:manage_role"
    USER_MANAGE_STATUS = "user:manage_status"
    USER_VIEW = "user:view"
    ROLE_VIEW = "role:view"

    # --- Assessment (Roadmap Sprint 2) ---
    ASSESSMENT_VIEW = "assessment:view"
    ASSESSMENT_MANAGE = "assessment:manage"
    ASSESSMENT_ARCHIVE = "assessment:archive"
    ASSESSMENT_CANCEL = "assessment:cancel"

    # --- Workflow Engine (Roadmap Sprint 3) ---
    # WorkflowTemplate is a global, platform-owned catalog (Platform
    # Architecture §5), not tenant data — these two codes gate the
    # authoring surface (create/publish templates) separately from viewing
    # it. Starting/advancing a *specific* assessment's workflow reuses the
    # existing ASSESSMENT_MANAGE/ASSESSMENT_VIEW codes above, since that's
    # already "manage/view this tenant's assessment" — no new code needed
    # for that half.
    WORKFLOW_TEMPLATE_MANAGE = "workflow_template:manage"
    WORKFLOW_TEMPLATE_VIEW = "workflow_template:view"

    # --- Validation (Roadmap Sprint 4, brought forward per explicit
    # instruction — originally scheduled Sprint 7) ---
    VALIDATION_VIEW = "validation:view"
    VALIDATION_MANAGE = "validation:manage"

    # --- Data Acquisition (Sprint 7 — the roadmap's "Sprint 9 — GIS
    # Engine" catalog/registry scope, run as this team's 7th executed
    # sprint per the roadmap's own parallelization note). One view/manage
    # pair for the whole catalog surface (DatasetSource, Dataset,
    # PredictorVariable, VariableSelection), matching
    # WORKFLOW_TEMPLATE_VIEW/MANAGE's precedent for a tenant-level catalog
    # resource that isn't assessment-nested. Geospatial's AOI/
    # SamplingCampaign API reuses ASSESSMENT_VIEW/MANAGE instead (assessment-
    # nested evidence, same reasoning Analysis's StageResult read API used)
    # — no new codes needed there.
    DATASET_VIEW = "dataset:view"
    DATASET_MANAGE = "dataset:manage"

    # --- Notification & Early Warning (Sprint 11). Three tenant-level
    # catalog/history surfaces (AlertRule, NotificationSubscription,
    # Notification history), each getting its own view/manage pair —
    # matching WORKFLOW_TEMPLATE/DATASET's precedent, since none of these
    # are assessment-nested evidence the way Geospatial's AOI is.
    ALERT_RULE_VIEW = "alert_rule:view"
    ALERT_RULE_MANAGE = "alert_rule:manage"
    NOTIFICATION_SUBSCRIPTION_VIEW = "notification_subscription:view"
    NOTIFICATION_SUBSCRIPTION_MANAGE = "notification_subscription:manage"
    NOTIFICATION_VIEW = "notification:view"
    NOTIFICATION_MANAGE = "notification:manage"

    # --- Dashboard & Visualization (Sprint 12). Read-only by construction
    # (Sprint 12's "Use projection/read-model approach only") — a single
    # view code, no manage counterpart, since there is nothing to manage:
    # every dashboard route is a GET computed fresh from other contexts'
    # already-persisted data.
    DASHBOARD_VIEW = "dashboard:view"


class UserStatus(StrEnum):
    """User lifecycle status (this sprint's "User Status Management"
    requirement). Transitions enforced by ``User`` aggregate methods, not
    by direct assignment — see Domain Model §6's pattern applied here at
    context scale.
    """

    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


# Every role's granted permissions — the seed data both the migration and
# any in-process authorization check without a DB round trip agree on.
# Single source of truth; each context's migration seed step reads the
# slice of this mapping relevant to the codes IT owns (Assessment's
# migration, for instance, seeds only the ASSESSMENT_* grants below — it
# never re-seeds Identity's own permissions, which Identity's migration
# already owns).
#
# Assessment grants (Roadmap Sprint 2) match API Resource Model §12's RBAC
# table exactly: Viewer can only view; Analyst/Admin/Owner can run the full
# assessment lifecycle (create, mark-ready, start, validate, report,
# archive, cancel).
ROLE_PERMISSIONS: dict[RoleName, frozenset[PermissionCode]] = {
    RoleName.VIEWER: frozenset(
        {
            PermissionCode.USER_VIEW,
            PermissionCode.ROLE_VIEW,
            PermissionCode.ASSESSMENT_VIEW,
            PermissionCode.WORKFLOW_TEMPLATE_VIEW,
            PermissionCode.VALIDATION_VIEW,
            PermissionCode.DATASET_VIEW,
        }
    ),
    RoleName.ANALYST: frozenset(
        {
            PermissionCode.USER_VIEW,
            PermissionCode.ROLE_VIEW,
            PermissionCode.ASSESSMENT_VIEW,
            PermissionCode.ASSESSMENT_MANAGE,
            PermissionCode.ASSESSMENT_ARCHIVE,
            PermissionCode.ASSESSMENT_CANCEL,
            PermissionCode.WORKFLOW_TEMPLATE_VIEW,
            PermissionCode.VALIDATION_VIEW,
            PermissionCode.VALIDATION_MANAGE,
            PermissionCode.DATASET_VIEW,
        }
    ),
    RoleName.ADMIN: frozenset(
        {
            PermissionCode.USER_VIEW,
            PermissionCode.ROLE_VIEW,
            PermissionCode.USER_INVITE,
            PermissionCode.USER_MANAGE_ROLE,
            PermissionCode.USER_MANAGE_STATUS,
            PermissionCode.ASSESSMENT_VIEW,
            PermissionCode.ASSESSMENT_MANAGE,
            PermissionCode.ASSESSMENT_ARCHIVE,
            PermissionCode.ASSESSMENT_CANCEL,
            PermissionCode.WORKFLOW_TEMPLATE_VIEW,
            PermissionCode.WORKFLOW_TEMPLATE_MANAGE,
            PermissionCode.VALIDATION_VIEW,
            PermissionCode.VALIDATION_MANAGE,
            PermissionCode.DATASET_VIEW,
            PermissionCode.DATASET_MANAGE,
        }
    ),
    RoleName.OWNER: frozenset(
        {
            PermissionCode.USER_VIEW,
            PermissionCode.ROLE_VIEW,
            PermissionCode.USER_INVITE,
            PermissionCode.USER_MANAGE_ROLE,
            PermissionCode.USER_MANAGE_STATUS,
            PermissionCode.TENANT_MANAGE,
            PermissionCode.ASSESSMENT_VIEW,
            PermissionCode.ASSESSMENT_MANAGE,
            PermissionCode.ASSESSMENT_ARCHIVE,
            PermissionCode.ASSESSMENT_CANCEL,
            PermissionCode.WORKFLOW_TEMPLATE_VIEW,
            PermissionCode.WORKFLOW_TEMPLATE_MANAGE,
            PermissionCode.VALIDATION_VIEW,
            PermissionCode.VALIDATION_MANAGE,
            PermissionCode.DATASET_VIEW,
            PermissionCode.DATASET_MANAGE,
        }
    ),
}


@dataclass(frozen=True, slots=True)
class ContactInfo:
    """Domain Model §3 — Tenant's contact details, validated as a unit."""

    email: str
    phone: str = ""
    address: str = ""

    def __post_init__(self) -> None:
        if "@" not in self.email:
            raise ValueError(f"ContactInfo.email is not a valid email address: {self.email!r}")


@dataclass(frozen=True, slots=True)
class Branding:
    """Domain Model §3 — Tenant's display identity."""

    logo_url: str = ""
