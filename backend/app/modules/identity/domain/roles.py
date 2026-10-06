"""Platform roles.

Roles are assigned in Auth0 (RBAC) and reach the API in the access token's namespaced roles
claim. Each value must equal the Auth0 role name exactly; a role in the token that is not
listed here is ignored. Roles drive the resource-scoped rules (owner/collaborator grants
and the sales-representative exclusions) and landing pages; what a role may do on its own
is the set of Auth0 permissions given to it.
"""

from enum import StrEnum


class Role(StrEnum):
    PRESALES_ENGINEER = "presales_engineer"
    SALES_REPRESENTATIVE = "sales_representative"
    ENGINEERING_REVIEWER = "engineering_reviewer"
    PM_REVIEWER = "pm_reviewer"
    SECURITY_REVIEWER = "security_reviewer"
    COMMERCIAL = "commercial"
    DELIVERY_MANAGER = "delivery_manager"
    HEAD_OF_DELIVERY = "head_of_delivery"
    PLATFORM_ADMINISTRATOR = "platform_administrator"
