"""`authorize`: every authorization decision goes through here (AD-15).

Call it first inside each command and query, never in the UI.
"""

from app.modules.identity.actions import Action
from app.modules.identity.domain.policy import Principal, Resource, is_allowed
from app.platform.errors import ForbiddenError


def authorize(actor: Principal, action: Action, resource: Resource | None = None) -> None:
    """Return None if allowed; raise `ForbiddenError` (403 `forbidden`) otherwise."""
    if not is_allowed(actor, action, resource):
        raise ForbiddenError("You are not allowed to perform this action.")
