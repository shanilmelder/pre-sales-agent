"""Map a validated token to a platform user, provisioning it on first sight.

Runs in the request's Unit of Work. The first valid token for an unknown `sub` creates a
user with no roles and appends `identity.user.provisioned` (no Opportunity, empty payload:
the trace never holds names or emails). Roles are read on every request, so role changes
apply on the user's next request.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.modules.identity.adapters import repository
from app.modules.identity.application.authentication import TokenIdentity, authenticate
from app.modules.identity.domain.policy import Principal
from app.modules.identity.domain.roles import Role
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import IdentityUserProvisioned
from app.platform.uow import UnitOfWork, UoW

USER_SUBJECT = "identity.user"
_ROLE_VALUES = frozenset(role.value for role in Role)
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CurrentUser:
    """The signed-in platform user and the principal used for authorization."""

    id: UUID
    name: str
    email: str
    principal: Principal

    @property
    def roles(self) -> frozenset[Role]:
        return self.principal.roles


def user_actor(user_id: UUID) -> Actor:
    return Actor("user", str(user_id))


async def provision_or_load(uow: UnitOfWork, identity: TokenIdentity) -> CurrentUser:
    user = await repository.get_by_sub(uow, identity.sub)
    if user is None:
        user_id = new_id()
        inserted = await repository.insert_if_absent(
            uow, user_id=user_id, auth0_sub=identity.sub, name=identity.name, email=identity.email
        )
        if inserted:
            await trace.append(
                uow,
                actor=user_actor(user_id),
                payload=IdentityUserProvisioned(),
                subject_type=USER_SUBJECT,
                subject_id=user_id,
                subject_version=1,
            )
            _log.info("identity.user_provisioned", extra={"user_id": str(user_id)})
        # A concurrent first request may have inserted it instead; read whichever row won.
        user = await repository.get_by_sub(uow, identity.sub)
        if user is None:
            raise RuntimeError("provisioned user not found")

    stored = await repository.load_roles(uow, user.id)
    if any(value not in _ROLE_VALUES for value in stored):
        _log.warning("identity.unknown_roles_ignored", extra={"user_id": str(user.id)})
    roles = frozenset(Role(value) for value in stored if value in _ROLE_VALUES)
    return CurrentUser(
        id=user.id,
        name=user.name,
        email=user.email,
        principal=Principal(actor=user_actor(user.id), roles=roles),
    )


async def get_current_user(
    identity: Annotated[TokenIdentity, Depends(authenticate)], uow: UoW
) -> CurrentUser:
    """FastAPI dependency. `identity` is resolved first, so the token (and any JWKS fetch)
    is validated before the Unit of Work opens."""
    return await provision_or_load(uow, identity)


async def get_current_principal(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> Principal:
    return user.principal


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
"""Handler parameter type: the signed-in user (401/503 problem+json otherwise)."""

CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
"""Handler parameter type: the caller's `Principal`, for `authorize`."""
