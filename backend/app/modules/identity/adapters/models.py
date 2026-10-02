"""identity's tables: platform users and their roles.

Roles live here, not in Auth0 RBAC. `identity_user_roles.role` holds `Role` values.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base


class IdentityUser(RowVersioned, Base):
    __tablename__ = "identity_users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    auth0_sub: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class IdentityUserRole(Base):
    __tablename__ = "identity_user_roles"

    user_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("identity_users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(Text, primary_key=True)
