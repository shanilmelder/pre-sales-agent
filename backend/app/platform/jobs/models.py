"""`platform_jobs`: the Postgres job queue (AD-29, AD-7).

One row per job. `priority` stores the class's rank (0 = interactive, 1 = background) so
claiming can order by it. `last_error` holds a short technical reason, never customer
content. The application role has SELECT, INSERT and UPDATE on this table, not DELETE.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, SmallInteger, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

JOB_STATUSES = ("queued", "running", "succeeded", "failed_retrying", "dead")
# Statuses a claim can pick up (`running` only once its lease has expired).
CLAIMABLE_STATUSES = ("queued", "failed_retrying", "running")


class PlatformJob(Base):
    __tablename__ = "platform_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed_retrying', 'dead')",
            name="status",
        ),
        CheckConstraint("priority IN (0, 1)", name="priority"),
        CheckConstraint("attempts >= 0", name="attempts"),
        # The claim index: only rows a claim can still pick up, in claim order.
        Index(
            "ix_platform_jobs_claim",
            "priority",
            "run_after",
            "created_at",
            postgresql_where=text("status IN ('queued', 'failed_retrying', 'running')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    job_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    priority: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    opportunity_id: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
