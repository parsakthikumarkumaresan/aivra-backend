"""Canonical role vocabulary (spec section 6).

Organization roles apply within a tenant via ``organizations.models.OrganizationMember``.
Platform roles are AIVRA-internal and independent of any customer organization
membership — they gate ``/internal/...`` routes (spec section 10.2/14).
"""

from __future__ import annotations

from enum import StrEnum


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    HR_MANAGER = "hr_manager"
    RECRUITER = "recruiter"
    VIEWER = "viewer"
    CUSTOMER_VOICE_USER = "customer_voice_user"


class PlatformRole(StrEnum):
    AIVRA_ADMIN = "aivra_admin"
    AIVRA_ENGINEER = "aivra_engineer"


# Roles that may manage organization membership/billing.
ORG_MANAGEMENT_ROLES = frozenset({OrgRole.OWNER, OrgRole.ADMIN})

# Roles that may act on HR workflows (approvals, screening decisions, scheduling).
HR_OPERATOR_ROLES = frozenset({OrgRole.OWNER, OrgRole.ADMIN, OrgRole.HR_MANAGER, OrgRole.RECRUITER})

# Roles that may view but not mutate.
READ_ONLY_ROLES = frozenset({OrgRole.VIEWER})

# Platform roles allowed into internal Voice engineering routes.
INTERNAL_VOICE_ROLES = frozenset({PlatformRole.AIVRA_ADMIN, PlatformRole.AIVRA_ENGINEER})
