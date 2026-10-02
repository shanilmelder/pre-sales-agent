"""Read model for `GET /api/v1/me`."""

from pydantic import BaseModel

from app.modules.identity.application.provisioning import CurrentUser
from app.modules.identity.domain.roles import Role


class UserProfile(BaseModel):
    """The signed-in user. `roles` is empty until an administrator assigns one."""

    id: str
    name: str
    email: str
    roles: list[Role]

    @classmethod
    def of(cls, user: CurrentUser) -> "UserProfile":
        return cls(id=str(user.id), name=user.name, email=user.email, roles=sorted(user.roles))
