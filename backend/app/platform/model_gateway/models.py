"""`platform_model_calls`: one row per ModelGateway call (AD-8).

Written by the gateway in its own Unit of Work after the call finishes, never while the
HTTP request is in flight (AD-25). Rows hold ids, the profile, model, digest, token counts,
latency and the outcome; never prompt or response text. The application role has SELECT
and INSERT only.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base


class PlatformModelCall(Base):
    __tablename__ = "platform_model_calls"
    __table_args__ = (
        CheckConstraint("outcome IN ('ok', 'invalid_output', 'error', 'timeout')", name="outcome"),
        CheckConstraint("priority IN ('interactive', 'background')", name="priority"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND latency_ms >= 0 AND attempts >= 0",
            name="counts",
        ),
        Index(None, "run_id"),
        Index(None, "opportunity_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agent_id: Mapped[str] = mapped_column(Text)
    config_version: Mapped[str] = mapped_column(Text)
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    task_id: Mapped[UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid)
    profile: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    model_digest: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
