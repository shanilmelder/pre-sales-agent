"""`authorize`: every authorization decision goes through here (AD-15).

Call it first inside each command and query, never in the UI. `can` asks the same policy
without raising, for callers that must answer differently (e.g. 404 instead of 403 so a
hidden resource's existence does not leak).
"""

from app.modules.identity.actions import Action
from app.modules.identity.domain.policy import (
    OverrideBasis,
    Principal,
    Resource,
    is_allowed,
    override_basis,
)
from app.platform.errors import ForbiddenError


def can(actor: Principal, action: Action, resource: Resource | None = None) -> bool:
    """True if the policy allows the action."""
    return is_allowed(actor, action, resource)


def authorize(actor: Principal, action: Action, resource: Resource | None = None) -> None:
    """Return None if allowed; raise `ForbiddenError` (403 `forbidden`) otherwise."""
    if not is_allowed(actor, action, resource):
        raise ForbiddenError("You are not allowed to perform this action.")


def finding_override_basis(
    actor: Principal, resource: Resource, *, security_discipline: bool
) -> OverrideBasis | None:
    """Story 6.6 (R1): why the actor may override a Finding of the Opportunity, or None."""
    return override_basis(actor, resource, security_discipline=security_discipline)
