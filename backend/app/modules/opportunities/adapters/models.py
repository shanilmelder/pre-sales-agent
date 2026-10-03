"""The opportunities module's tables. `owner_id` and `user_id` hold identity user ids
without foreign keys: modules never reference each other's tables (AD-2)."""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Index, Text, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base


class OpportunityRow(RowVersioned, Base):
    __tablename__ = "opportunities_opportunities"
    __table_args__ = (Index(None, "owner_id"), Index(None, "created_at", "id"))

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    customer_name: Mapped[str] = mapped_column(Text)
    products: Mapped[list[str]] = mapped_column(ARRAY(Text))
    industry: Mapped[str] = mapped_column(Text)
    target_proposal_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class CollaboratorRow(Base):
    __tablename__ = "opportunities_collaborators"
    __table_args__ = (Index(None, "user_id"),)

    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "opportunities_opportunities.id",
            ondelete="CASCADE",
            # The convention's name would pass Postgres' 63-character limit.
            name="fk_opportunities_collaborators_opportunity_id",
        ),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
