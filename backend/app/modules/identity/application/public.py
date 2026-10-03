"""identity's public API. Other modules import identity only from here."""

from app.modules.identity.actions import ACTION_NAME_RE, Action
from app.modules.identity.application.authentication import TokenIdentity, TokenValidator
from app.modules.identity.application.authorize import authorize
from app.modules.identity.application.profile import UserProfile
from app.modules.identity.application.provisioning import (
    CurrentPrincipal,
    CurrentUser,
    CurrentUserDep,
)
from app.modules.identity.application.role_admin import (
    DEFAULT_PAGE_SIZE,
    LAST_ADMINISTRATOR_DETAIL,
    MAX_PAGE,
    MAX_PAGE_SIZE,
    AdminUser,
    AdminUserPage,
    assign_role,
    get_user,
    list_users,
    remove_role,
)
from app.modules.identity.domain.policy import POLICY, Principal, Resource
from app.modules.identity.domain.roles import Role

__all__ = [
    "ACTION_NAME_RE",
    "DEFAULT_PAGE_SIZE",
    "LAST_ADMINISTRATOR_DETAIL",
    "MAX_PAGE",
    "MAX_PAGE_SIZE",
    "POLICY",
    "Action",
    "AdminUser",
    "AdminUserPage",
    "CurrentPrincipal",
    "CurrentUser",
    "CurrentUserDep",
    "Principal",
    "Resource",
    "Role",
    "TokenIdentity",
    "TokenValidator",
    "UserProfile",
    "assign_role",
    "authorize",
    "get_user",
    "list_users",
    "remove_role",
]
