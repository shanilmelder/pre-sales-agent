"""The actuals module's tables (Story 10.1). No cross-module foreign keys except the
Opportunity (AD-2): `estimate_version_id`, `estimate_line_id`, `integration_type_ids`,
`work_package_id`, `recorded_by` and `closed_by` hold ids owned by other modules, read through
their public APIs."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")
_CAUSES = (
    "('unknown_requirement', 'integration_complexity', 'customer_delay', 'scope_change', "
    "'estimation_error', 'other')"
)


class ActualRow(Base):
    """One version of an Actual: a Baseline line's (or Unplanned work's) recorded effort,
    duration, cost, variance cause, failed Assumptions (`[{assumption_id, version}]`) and note,
    against `estimate_version_id`. Corrections insert the next `version` of the same
    `actual_group_id` with a `correction_reason`; only `is_current` ever changes (psa_app holds
    UPDATE on that column alone). Never deleted."""

    __tablename__ = "actuals_actuals"
    __table_args__ = (
        Index(None, "opportunity_id"),
        Index(
            "uq_actuals_actuals_current_group",
            "actual_group_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index(
            "uq_actuals_actuals_current_line",
            "estimate_line_id",
            unique=True,
            postgresql_where=text("is_current AND estimate_line_id IS NOT NULL"),
        ),
        UniqueConstraint("actual_group_id", "version"),
        CheckConstraint("kind IN ('milestone', 'final')", name="kind"),
        CheckConstraint(
            f"variance_cause IS NULL OR variance_cause IN {_CAUSES}", name="variance_cause"
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "effort_hours >= 0 AND (duration_days IS NULL OR duration_days >= 0)", name="effort"
        ),
        CheckConstraint(
            "(cost_minor IS NULL) = (currency IS NULL) AND (cost_minor IS NULL OR "
            "(cost_minor >= 0 AND currency ~ '^[A-Z]{3}$'))",
            name="cost",
        ),
        CheckConstraint(
            "(version = 1) = (correction_reason IS NULL)", name="correction_has_reason"
        ),
        CheckConstraint(
            "estimate_line_id IS NOT NULL OR variance_cause IN "
            "('scope_change', 'unknown_requirement', 'other')",
            name="unplanned_cause",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("opportunities_opportunities.id", name="fk_actuals_actuals_opportunity_id"),
    )
    estimate_version_id: Mapped[UUID] = mapped_column(Uuid)
    estimate_line_id: Mapped[UUID | None] = mapped_column(Uuid)
    actual_group_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(Boolean)
    integration_type_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'::uuid[]")
    )
    work_package_id: Mapped[UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    milestone_label: Mapped[str | None] = mapped_column(Text)
    effort_hours: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    duration_days: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(Text)
    variance_cause: Mapped[str | None] = mapped_column(Text)
    failed_assumptions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    note: Mapped[str | None] = mapped_column(Text)
    correction_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer)
    recorded_by: Mapped[UUID] = mapped_column(Uuid)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class DeliveryRow(Base):
    """The Opportunity's **Close delivery** (one row at most): every line of the Baseline
    `estimate_version_id` had a final Actual. Insert-only; its existence makes the derived
    status `delivered`."""

    __tablename__ = "actuals_deliveries"
    __table_args__ = (UniqueConstraint("opportunity_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("opportunities_opportunities.id", name="fk_actuals_deliveries_opportunity_id"),
    )
    estimate_version_id: Mapped[UUID] = mapped_column(Uuid)
    closed_by: Mapped[UUID] = mapped_column(Uuid)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
