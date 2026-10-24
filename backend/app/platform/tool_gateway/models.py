"""`platform_tool_calls`: one row per ToolGateway call (Story 5.4, AD-9).

Written by the gateway, never by a handler, so no tool call goes unrecorded: ids, the tool,
the outcome (`ok | denied | failed`) with its reason code, how many records came back, the
duration and, for the research fetch, the final HTTP status. Never page or customer text.
The application role has SELECT and INSERT only.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base


class PlatformToolCall(Base):
    __tablename__ = "platform_tool_calls"
    __table_args__ = (
        CheckConstraint("outcome IN ('ok', 'denied', 'failed')", name="outcome"),
        CheckConstraint(
            "reason IS NULL OR reason IN ('tool_not_permitted', 'out_of_scope', 'unknown_tool', "
            "'not_allowlisted', 'timeout', 'http_error', 'too_large', 'unsupported_content', "
            "'too_many_redirects', 'parse_failed')",
            name="reason",
        ),
        CheckConstraint("(outcome = 'ok') = (reason IS NULL)", name="reason_set"),
        CheckConstraint("result_count >= 0 AND duration_ms >= 0", name="counts"),
        Index(None, "run_id"),
        Index(None, "opportunity_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    task_id: Mapped[UUID | None] = mapped_column(Uuid)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    agent_id: Mapped[str] = mapped_column(Text)
    config_version_id: Mapped[UUID] = mapped_column(Uuid)
    tool: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
