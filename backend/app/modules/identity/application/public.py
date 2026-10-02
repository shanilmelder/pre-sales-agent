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
from app.modules.identity.domain.policy import POLICY, Principal, Resource
from app.modules.identity.domain.roles import Role

__all__ = [
    "ACTION_NAME_RE",
    "POLICY",
    "Action",
    "CurrentPrincipal",
    "CurrentUser",
    "CurrentUserDep",
    "Principal",
    "Resource",
    "Role",
    "TokenIdentity",
    "TokenValidator",
    "UserProfile",
    "authorize",
]
