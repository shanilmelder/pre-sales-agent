"""Read model for `GET /api/v1/me`."""

from pydantic import BaseModel

from app.modules.identity.application.provisioning import CurrentUser
from app.modules.identity.domain.roles import Role


class UserProfile(BaseModel):
    """The signed-in user, with the roles and permissions their access token carries
    (assigned in Auth0). Both are empty until an administrator assigns a role there."""

    id: str
    name: str
    email: str
    roles: list[Role]
    permissions: list[str]

    @classmethod
    def of(cls, user: CurrentUser) -> "UserProfile":
        return cls(
            id=str(user.id),
            name=user.name,
            email=user.email,
            roles=sorted(user.roles),
            permissions=sorted(p.value for p in user.permissions),
        )
