"""The estimates module's tables (Stories 8.1, 8.4 and 8.5). `opportunity_id`, `requirement_id`
and an Assumption's origin Gap and `accepted_by` hold ids owned by other modules without
foreign keys (AD-2)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.concurrency import RowVersioned
from app.platform.db import Base

_NOW = text("now()")


class DraftRow(Base):
    """One run of `estimates.draft_estimate` for an Opportunity. Inserted `queued` with its
    job; `error_code` is set only when `failed`."""

    __tablename__ = "estimates_drafts"
    __table_args__ = (
        Index(None, "opportunity_id", "created_at"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="status"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('model_unavailable', 'model_timeout', 'output_invalid', 'registry_agent_disabled')",
            name="error_code",
        ),
        CheckConstraint("(status = 'failed') = (error_code IS NOT NULL)", name="failed_has_code"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[UUID | None] = mapped_column(Uuid)
    """Story 9.1: the person who started it (`start_draft`); null when the platform queued
    it. The version it stores records them as its `created_by`."""


class EstimateVersionRow(RowVersioned, Base):
    """An Estimate Version of an Opportunity. An accepted draft inserts a `draft` version
    numbered one past the latest, and marks the earlier `draft` `superseded`. At most one
    `draft` per Opportunity. Story 8.3: a finished assessment run inserts one the same way
    (`source` `assessments`, `source_run_id` the run). `proposal_status` is the state of its
    Assumption proposals (Story 8.4); null for a version that never had them queued. Story
    8.6: submitting moves the draft to `submitted` and marks earlier `submitted` versions
    `superseded`. Story 9.1: a Review Request moves a submitted version to `in_review`, and
    cancelling its last pending request moves it back. Story 9.3: review decisions move an
    `in_review` version to `approved` or `rejected`."""

    __tablename__ = "estimates_estimate_versions"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "version"),
        Index(
            "uq_estimates_estimate_versions_one_draft",
            "opportunity_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'in_review', 'approved', 'rejected', 'superseded')",
            name="status",
        ),
        CheckConstraint(
            "status <> 'submitted' OR submitted_at IS NOT NULL", name="submitted_has_at"
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("uncovered_count >= 0 AND dropped_count >= 0", name="counts"),
        CheckConstraint("uncarried_edit_count >= 0", name="uncarried_edit_count"),
        CheckConstraint(
            "proposal_status IS NULL OR proposal_status IN "
            "('queued', 'running', 'succeeded', 'failed')",
            name="proposal_status",
        ),
        CheckConstraint("source IN ('model', 'assessments', 'challenge')", name="source"),
        CheckConstraint(
            "(source IN ('assessments', 'challenge')) = (source_run_id IS NOT NULL)",
            name="source_has_run",
        ),
        Index(
            "uq_estimates_estimate_versions_challenge_run",
            "source_run_id",
            unique=True,
            postgresql_where=text("source = 'challenge'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)
    template_version: Mapped[str] = mapped_column(Text)
    uncovered_count: Mapped[int] = mapped_column(Integer)
    dropped_count: Mapped[int] = mapped_column(Integer)
    proposal_status: Mapped[str | None] = mapped_column(Text)
    uncarried_edit_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    """Story 8.2: edited lines of the superseded draft that had no matching line here."""
    source: Mapped[str] = mapped_column(Text, server_default=text("'model'"))
    """Story 8.3: `model` (an accepted model draft) or `assessments` (built from the
    specialist Assessments when an assessment run finished)."""
    source_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    """Story 8.3: the assessment run (an assessments id) a version from the Assessments was
    built for; null for a model draft."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Story 8.6: when it was submitted; null for a version never submitted."""
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    """Story 9.6: the `node:<run>:<task>:<attempt>` key of the Challenge run node that wrote
    it (a replay finds the version by `source_run_id`); null otherwise."""
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    """Story 9.1: the person (an identity user id) who triggered the version (for one from the
    Assessments, the user who started the run); null when unknown, and then no author check
    applies to its reviews."""


class EstimateLineRow(Base):
    """A work item of an Estimate Version. Its title, section, basis and links are
    insert-only; a person may edit its effort and role mix on a `draft` version (Story 8.2),
    which records who, when and why (`edited_*`; all or none) and bumps `row_version`.
    `edit_carried_from_version`: the version number a re-draft carried the edit from."""

    __tablename__ = "estimates_estimate_lines"
    __table_args__ = (
        UniqueConstraint("version_id", "position"),
        CheckConstraint(
            "section IN ('functional', 'integration', 'data', 'security', 'non_functional', "
            "'commercial')",
            name="section",
        ),
        CheckConstraint("effort_hours >= 0", name="effort_hours"),
        CheckConstraint("position >= 1", name="position"),
        CheckConstraint(
            "(edited_at IS NULL) = (edited_by IS NULL) AND "
            "(edited_at IS NULL) = (edit_reason IS NULL)",
            name="edited_has_by",
        ),
        CheckConstraint(
            "edit_carried_from_version IS NULL OR edited_at IS NOT NULL",
            name="carried_was_edited",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        Uuid,
        # Named explicitly: the convention's name would pass Postgres' 63-character limit.
        ForeignKey(
            "estimates_estimate_versions.id",
            ondelete="CASCADE",
            name="fk_estimates_estimate_lines_version_id",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    effort_hours: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    role_mix: Mapped[dict[str, Any]] = mapped_column(JSONB)
    basis: Mapped[str] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    edited_by: Mapped[UUID | None] = mapped_column(Uuid)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edit_reason: Mapped[str | None] = mapped_column(Text)
    edit_carried_from_version: Mapped[int | None] = mapped_column(Integer)


class LineRequirementRow(Base):
    """A line covers a Requirement at a version. Insert-only."""

    __tablename__ = "estimates_line_requirements"

    line_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_lines.id",
            ondelete="CASCADE",
            name="fk_estimates_line_requirements_line_id",
        ),
        primary_key=True,
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_version: Mapped[int] = mapped_column(Integer)


class AssumptionRow(RowVersioned, Base):
    """An Assumption of an Estimate Version (Story 8.4): a `condition` (no hours) or a
    `contingency` (hours, optionally linked to one of the version's lines), made from one
    origin (`origin_ref`: `{kind: "gap", id, row_version}`). Inserted unaccepted; accepting
    sets `accepted_by` and `accepted_at` together. `position` keeps the proposal order.
    `carried_from` (Story 8.7): the accepted Assumption of the superseded version this one
    was copied from by a re-draft, null for a proposal. Story 8.5: a person may edit its kind,
    wording, hours and line on a `draft` version, which clears the acceptance and bumps
    `row_version`; `changed_by` is the person behind its latest accept or edit. Deleted only
    when its Gap is converted to a Risk while it is unaccepted."""

    __tablename__ = "estimates_assumptions"
    __table_args__ = (
        UniqueConstraint("version_id", "position"),
        CheckConstraint("kind IN ('condition', 'contingency')", name="kind"),
        CheckConstraint(
            "(kind = 'contingency') = (amount_hours IS NOT NULL)", name="contingency_has_hours"
        ),
        CheckConstraint("amount_hours IS NULL OR amount_hours > 0", name="amount_hours"),
        CheckConstraint("kind = 'contingency' OR line_id IS NULL", name="condition_has_no_line"),
        CheckConstraint("(accepted_by IS NULL) = (accepted_at IS NULL)", name="accepted_has_by"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_versions.id",
            ondelete="CASCADE",
            name="fk_estimates_assumptions_version_id",
        ),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    wording: Mapped[str] = mapped_column(Text)
    amount_hours: Mapped[Decimal | None] = mapped_column(Numeric(10, 1))
    line_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_lines.id",
            ondelete="CASCADE",
            name="fk_estimates_assumptions_line_id",
        ),
    )
    origin_ref: Mapped[dict[str, Any]] = mapped_column(JSONB)
    accepted_by: Mapped[UUID | None] = mapped_column(Uuid)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    carried_from: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_assumptions.id",
            ondelete="SET NULL",
            name="fk_estimates_assumptions_carried_from",
        ),
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    changed_by: Mapped[UUID | None] = mapped_column(Uuid)


class RiskRow(RowVersioned, Base):
    """A Risk of an Estimate Version (Story 8.5), made from one Gap (`origin_ref`: `{kind:
    "gap", id, row_version}`) by a person (`created_by`): a description and a `likelihood` and
    `impact` (`low|medium|high`). Never accepted and never a blocker. A person may edit it on
    a `draft` version (`changed_by`, `row_version`). `carried_from`: the Risk of the
    superseded draft a re-draft copied it from."""

    __tablename__ = "estimates_risks"
    __table_args__ = (
        UniqueConstraint("version_id", "position"),
        CheckConstraint("likelihood IN ('low', 'medium', 'high')", name="likelihood"),
        CheckConstraint("impact IN ('low', 'medium', 'high')", name="impact"),
        CheckConstraint("char_length(description) BETWEEN 1 AND 500", name="description"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_versions.id",
            ondelete="CASCADE",
            name="fk_estimates_risks_version_id",
        ),
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    likelihood: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    origin_ref: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    changed_by: Mapped[UUID | None] = mapped_column(Uuid)
    carried_from: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_risks.id",
            ondelete="SET NULL",
            name="fk_estimates_risks_carried_from",
        ),
    )


class BaselineRow(Base):
    """Story 9.7 (AD-26): an approved Estimate Version a person set as the Opportunity's
    Baseline, with the version it replaced (`previous_version_id`, null for the first), when
    (`set_at`) and by whom (`set_by`, an identity user id). Insert-only: the current Baseline is
    the Opportunity's latest row; written only by `estimates.set_baseline`. Unlike the other
    tables here, `opportunity_id` is keyed to the Opportunity (Story 9.7's spec)."""

    __tablename__ = "estimates_baselines"
    __table_args__ = (
        Index(
            "ix_estimates_baselines_opportunity_id_set_at",
            "opportunity_id",
            text("set_at DESC"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("opportunities_opportunities.id", name="fk_estimates_baselines_opportunity_id"),
    )
    estimate_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_versions.id", name="fk_estimates_baselines_estimate_version_id"
        ),
    )
    previous_version_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "estimates_estimate_versions.id", name="fk_estimates_baselines_previous_version_id"
        ),
    )
    set_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    set_by: Mapped[UUID] = mapped_column(Uuid)
