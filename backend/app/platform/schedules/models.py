"""`platform_schedules`: recurring work (AD-29; Story 5.2).

One row per schedule: the job type it enqueues (whose payload has no fields), how often,
and when it is next due. Rows are seeded by migrations. The application role has SELECT and
UPDATE of `next_run_at` and `last_enqueued_at` only.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base


class PlatformSchedule(Base):
    __tablename__ = "platform_schedules"
    __table_args__ = (CheckConstraint("interval_s > 0", name="interval_s"),)

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    job_type: Mapped[str] = mapped_column(Text)
    interval_s: Mapped[int] = mapped_column(Integer)
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
