"""The assessments module's tables: Red Team Reviews (Story 6.5), Critic Reviews (Story 6.4)
and specialist Assessments (Epic 5 slice 5A). `opportunity_id`, `estimate_version_id`,
`requirement_id`, `line_id` and an Assessment's or a Review's `run_id` (a Workflow Run, owned
by `workflows` since Story 5.2) hold ids owned by other modules without foreign keys
(AD-2)."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")


class RedTeamRunRow(Base):
    """One run of `assessments.red_team_review` for an Opportunity. Inserted `queued` with its
    job; `error_code` is set only when `failed`."""

    __tablename__ = "assessments_red_team_runs"
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


class ReviewRow(Base):
    """A Review of an Opportunity: `red_team` (Story 6.5) or `critic` (Story 6.4). An accepted
    run inserts a `current` review numbered one past the latest of its kind, and marks the
    earlier `current` one `superseded`. At most one `current` per Opportunity and kind.
    `estimate_version_id`: the Estimate Version a Red Team Review reviewed (null when there
    was none). `run_id`: the assessment run (a Workflow Run, owned by `workflows`: no foreign
    key, AD-2) a Critic Review reviewed; null for a Red Team Review."""

    __tablename__ = "assessments_reviews"
    __table_args__ = (
        UniqueConstraint("opportunity_id", "kind", "version"),
        Index(
            "uq_assessments_reviews_one_current",
            "opportunity_id",
            "kind",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
        CheckConstraint("kind IN ('red_team', 'critic')", name="kind"),
        CheckConstraint("status IN ('current', 'superseded')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("dropped_count >= 0", name="dropped_count"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    estimate_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text)
    dropped_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    run_id: Mapped[UUID | None] = mapped_column(Uuid)


REVIEW_CATEGORIES = (
    # Red Team (Story 6.5)
    "integration_harder",
    "requirement_incomplete",
    "capability_overstated",
    "hidden_dependency",
    # Critic (Story 6.4)
    "coverage",
    "unsupported_claim",
    "timeline",
    "dependency",
    "risk_coverage",
)


class FindingRow(Base):
    """A Finding of a Review. Its text and links are insert-only; since Story 6.6 it has a
    status (`open`, `resolved` or `overridden`), changed only by a person's resolve or
    override command (`psa_app` may UPDATE `status`, `resolution` and `row_version` only).
    `fingerprint`, `security_discipline`, `policy_ref` and `previous_override_id` are set at
    acceptance by code: the hash that recognises the same Finding in a later Review, whether
    it cites a Security Agent Finding, the mandatory security Checklist item that makes it
    not overridable (`{kind: checklist_item, checklist_id, version, item_id}`), and the
    override of an earlier Finding with the same fingerprint (shown, never applied).
    `resolution`: `{kind: evidence_supplied | addressed, reason, by, at}` once `resolved`."""

    __tablename__ = "assessments_findings"
    __table_args__ = (
        UniqueConstraint("review_id", "position"),
        CheckConstraint(
            "category IN (" + ", ".join(f"'{c}'" for c in REVIEW_CATEGORIES) + ")",
            name="category",
        ),
        CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name="severity"),
        CheckConstraint("position >= 1", name="position"),
        CheckConstraint("status IN ('open', 'resolved', 'overridden')", name="status"),
        CheckConstraint(
            "(status = 'resolved') = (resolution IS NOT NULL)", name="resolved_has_resolution"
        ),
        CheckConstraint("row_version >= 1", name="row_version"),
        Index("ix_assessments_findings_fingerprint", "fingerprint"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    review_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_reviews.id", ondelete="CASCADE", name="fk_assessments_findings_review_id"
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    argument: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    fingerprint: Mapped[str] = mapped_column(Text)
    security_discipline: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    policy_ref: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    previous_override_id: Mapped[UUID | None] = mapped_column(Uuid)
    """An `assessments_finding_overrides` id, kept without a foreign key (shown only)."""
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    row_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))


class FindingOverrideRow(Base):
    """A person overrode a Critic or Red Team Finding with a reason (Story 6.6): the Review
    kind and version it belonged to, who, when, why, and the policy basis that allowed it
    (`owner`, `head_of_delivery` or `security_reviewer`). At most one per Finding.
    Insert-only."""

    __tablename__ = "assessments_finding_overrides"
    __table_args__ = (
        CheckConstraint("review_kind IN ('red_team', 'critic')", name="review_kind"),
        CheckConstraint(
            "policy_basis IN ('owner', 'head_of_delivery', 'security_reviewer')",
            name="policy_basis",
        ),
        Index("uq_assessments_finding_overrides_finding_id", "finding_id", unique=True),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_finding_overrides_finding_id",
        ),
    )
    review_kind: Mapped[str] = mapped_column(Text)
    review_version: Mapped[int] = mapped_column(Integer)
    overridden_by: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text)
    policy_basis: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class FindingEvidenceRow(Base):
    """An Evidence reference a person supplied to resolve a Finding (Story 6.6): `kind`
    (`requirement` or `source_document`), the id and version, in the order given.
    Insert-only."""

    __tablename__ = "assessments_finding_evidence"
    __table_args__ = (
        CheckConstraint("kind IN ('requirement', 'source_document')", name="kind"),
        CheckConstraint("position >= 1", name="position"),
    )

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_finding_evidence_finding_id",
        ),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[UUID] = mapped_column(Uuid)
    ref_version: Mapped[int] = mapped_column(Integer)


class FindingRequirementRow(Base):
    """A Finding challenges a Requirement at a version. Insert-only."""

    __tablename__ = "assessments_finding_requirements"

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_finding_requirements_finding_id",
        ),
        primary_key=True,
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_version: Mapped[int] = mapped_column(Integer)


class FindingLineRow(Base):
    """A Finding challenges a line of the reviewed Estimate Version. Insert-only."""

    __tablename__ = "assessments_finding_lines"

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_finding_lines_finding_id",
        ),
        primary_key=True,
    )
    line_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)


class FindingTargetRow(Base):
    """A Critic Finding cites a specialist Finding at its Assessment's version (Story 6.4).
    `assessment_finding_id` and `assessment_id` are `assessments_assessment_findings` and
    `assessments_assessments` ids, kept without foreign keys so the link reads as it was.
    Insert-only."""

    __tablename__ = "assessments_finding_targets"

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_finding_targets_finding_id",
        ),
        primary_key=True,
    )
    assessment_finding_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    assessment_id: Mapped[UUID] = mapped_column(Uuid)
    assessment_version: Mapped[int] = mapped_column(Integer)


# --- specialist Assessments (Epic 5 slice 5A) ----------------------------------------------

_AGENTS = "('engineering_agent', 'pm_agent', 'security_agent')"
_SEVERITIES = "('low', 'medium', 'high', 'critical')"


class AssessmentRow(Base):
    """A specialist agent's Assessment of an Opportunity. A succeeded task inserts a
    `current` one numbered one past the agent's latest, and marks the earlier `current` one
    `superseded`. At most one `current` per Opportunity and agent. `config_version_id`: the
    registry config version that produced it (Story 7.1)."""

    __tablename__ = "assessments_assessments"
    __table_args__ = (
        UniqueConstraint(
            "opportunity_id", "agent", "version", name="uq_assessments_assessments_version"
        ),
        Index(
            "uq_assessments_assessments_one_current",
            "opportunity_id",
            "agent",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
        CheckConstraint(f"agent IN {_AGENTS}", name="agent"),
        CheckConstraint("status IN ('current', 'superseded')", name="status"),
        CheckConstraint(
            "recommendation IN ('proceed', 'proceed_with_conditions', 'do_not_proceed')",
            name="recommendation",
        ),
        CheckConstraint("confidence IN ('high', 'medium', 'low')", name="confidence"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("dropped_count >= 0", name="dropped_count"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    agent: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    run_id: Mapped[UUID] = mapped_column(Uuid)
    """The Workflow Run whose task produced it (owned by `workflows`: no foreign key, AD-2)."""
    config_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "registry_agent_config_versions.id",
            name="fk_assessments_assessments_config_version_id",
        ),
    )
    status: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text)
    confidence_basis: Mapped[str] = mapped_column(Text)
    dropped_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class AssessmentFindingRow(Base):
    """A Finding of an Assessment. Insert-only. `injection_suspected` (Story 5.4): a
    Requirement it cites read like an injected instruction when the agent read it."""

    __tablename__ = "assessments_assessment_findings"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "position", name="uq_assessments_assessment_findings_position"
        ),
        CheckConstraint("kind IN ('risk', 'constraint', 'dependency', 'opportunity')", name="kind"),
        CheckConstraint(f"severity IN {_SEVERITIES}", name="severity"),
        CheckConstraint("position >= 1", name="position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    assessment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_assessments.id",
            ondelete="CASCADE",
            name="fk_assessments_assessment_findings_assessment_id",
        ),
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    injection_suspected: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class AssessmentFindingRequirementRow(Base):
    """An Assessment Finding cites a Requirement at a version. Insert-only."""

    __tablename__ = "assessments_assessment_finding_requirements"
    __table_args__ = (
        # The default names would pass PostgreSQL's 63-character limit.
        PrimaryKeyConstraint(
            "finding_id", "requirement_id", name="pk_assessments_assessment_finding_reqs"
        ),
    )

    finding_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_assessment_findings.id",
            ondelete="CASCADE",
            name="fk_assessments_assessment_finding_reqs_finding_id",
        ),
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid)
    requirement_version: Mapped[int] = mapped_column(Integer)


class AssessmentEffortRow(Base):
    """An Assessment's effort for one Requirement (at a version), in person-hours to 0.1 h.
    Insert-only."""

    __tablename__ = "assessments_effort"
    __table_args__ = (
        UniqueConstraint(
            "assessment_id", "requirement_id", name="uq_assessments_effort_requirement"
        ),
        CheckConstraint("hours >= 0.5 AND hours <= 2000", name="hours"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    assessment_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "assessments_assessments.id",
            ondelete="CASCADE",
            name="fk_assessments_effort_assessment_id",
        ),
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid)
    requirement_version: Mapped[int] = mapped_column(Integer)
    hours: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    basis: Mapped[str] = mapped_column(Text)
