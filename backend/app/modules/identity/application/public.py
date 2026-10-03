"""identity's public API. Other modules import identity only from here."""

from app.modules.identity.actions import ACTION_NAME_RE, Action
from app.modules.identity.application.authentication import TokenIdentity, TokenValidator
from app.modules.identity.application.authorize import authorize, can
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
from app.modules.identity.application.user_search import (
    SEARCH_DEFAULT_LIMIT,
    SEARCH_MAX_LIMIT,
    SEARCH_MAX_QUERY,
    SEARCH_MIN_QUERY,
    UserSearchResult,
    UserSummary,
    search_users,
    user_names,
)
from app.modules.identity.domain.policy import (
    MEMBER_GRANTS,
    OPPORTUNITY_RESOURCE,
    OWNER_GRANTS,
    POLICY,
    Principal,
    Resource,
)
from app.modules.identity.domain.roles import Role

__all__ = [
    "ACTION_NAME_RE",
    "DEFAULT_PAGE_SIZE",
    "LAST_ADMINISTRATOR_DETAIL",
    "MAX_PAGE",
    "MAX_PAGE_SIZE",
    "MEMBER_GRANTS",
    "OPPORTUNITY_RESOURCE",
    "OWNER_GRANTS",
    "POLICY",
    "SEARCH_DEFAULT_LIMIT",
    "SEARCH_MAX_LIMIT",
    "SEARCH_MAX_QUERY",
    "SEARCH_MIN_QUERY",
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
    "UserSearchResult",
    "UserSummary",
    "assign_role",
    "authorize",
    "can",
    "get_user",
    "list_users",
    "remove_role",
    "search_users",
    "user_names",
]
