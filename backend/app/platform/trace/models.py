"""`platform_trace_events`: the append-only trace (AD-12).

The application DB role has SELECT and INSERT only on this table; rows are written only by
`app.platform.trace.append`.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base


class TraceEvent(Base):
    __tablename__ = "platform_trace_events"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'agent', 'system')", name="actor_type"),
        Index(None, "opportunity_id", "occurred_at"),
        Index(None, "subject_type", "subject_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid)
    workflow_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    actor_type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[UUID] = mapped_column(Uuid)
    subject_version: Mapped[int | None] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
