"""The reviews module's tables (Stories 9.1, 9.3, 9.4 and 9.5). No cross-module foreign keys
(AD-2): `opportunity_id`, `target_id`, `estimate_version_id`, `reviewer_id`, `requested_by`,
`decided_by`, `escalated_to`, `alternative_version_id`, `replied_by`, `assessment_id`,
`challenger_id` and `workflow_run_id` hold ids owned by other modules. Decisions, replies and
Challenges reference their Review Request, and a linked request the one it is an alternative
to (in-module foreign keys)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.db import Base

_NOW = text("now()")


class ReviewRequestRow(Base):
    """A Review Request: one named reviewer asked to review one target (an Estimate Version,
    or one of its Assessments at `target_version`) for one review type, counting towards
    `estimate_version_id`. Inserted `pending`; only its status (and a cancel's reason) ever
    changes, bumping `row_version`. Never deleted. `linked_request_id` (Story 9.4): the request
    on an older version this one is an alternative to."""

    __tablename__ = "reviews_review_requests"
    __table_args__ = (
        Index(None, "opportunity_id"),
        Index(None, "estimate_version_id"),
        Index(None, "reviewer_id"),
        Index(
            "uq_reviews_review_requests_one_pending",
            "reviewer_id",
            "review_type",
            "target_kind",
            "target_id",
            "target_version",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        CheckConstraint("review_type IN ('engineering', 'pm', 'security')", name="review_type"),
        CheckConstraint("target_kind IN ('estimate_version', 'assessment')", name="target_kind"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'challenged', 'superseded', "
            "'cancelled')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)", name="cancelled_has_reason"
        ),
        CheckConstraint("message IS NULL OR char_length(message) <= 2000", name="message"),
        CheckConstraint("target_version >= 1", name="target_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    review_type: Mapped[str] = mapped_column(Text)
    target_kind: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID] = mapped_column(Uuid)
    target_version: Mapped[int] = mapped_column(Integer)
    estimate_version_id: Mapped[UUID] = mapped_column(Uuid)
    reviewer_id: Mapped[UUID] = mapped_column(Uuid)
    requested_by: Mapped[UUID] = mapped_column(Uuid)
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    linked_request_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "reviews_review_requests.id", name="fk_reviews_review_requests_linked_request_id"
        ),
    )


class ReviewDecisionRow(Base):
    """A Review Decision (Story 9.3): what the request's reviewer decided, why, on which
    version of the target, and (for an escalation) who the request went to. Append-only:
    `psa_app` may only SELECT and INSERT."""

    __tablename__ = "reviews_review_decisions"
    __table_args__ = (
        Index(None, "review_request_id", "decided_at"),
        CheckConstraint(
            "decision IN ('approved', 'rejected', 'challenged', 'evidence_requested', "
            "'alternative_requested', 'escalated')",
            name="decision",
        ),
        CheckConstraint(
            "decision = 'approved' OR (reason IS NOT NULL AND char_length(btrim(reason)) >= 1)",
            name="reason_required",
        ),
        CheckConstraint("reason IS NULL OR char_length(reason) <= 1000", name="reason"),
        CheckConstraint(
            "(decision = 'escalated') = (escalated_to IS NOT NULL)", name="escalated_has_target"
        ),
        CheckConstraint("target_version >= 1", name="target_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    review_request_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "reviews_review_requests.id", name="fk_reviews_review_decisions_review_request_id"
        ),
    )
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[UUID] = mapped_column(Uuid)
    target_version: Mapped[int] = mapped_column(Integer)
    escalated_to: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ReviewReplyRow(Base):
    """A reply (Story 9.4): the request's sender or the Opportunity's owner answering a request
    for evidence or an alternative, with a message, its Evidence (`[{kind, id, version}]`) and,
    after `alternative_requested`, the draft Estimate Version offered as the alternative.
    Append-only: `psa_app` may only SELECT and INSERT."""

    __tablename__ = "reviews_review_replies"
    __table_args__ = (
        Index(None, "review_request_id", "replied_at"),
        CheckConstraint(
            "char_length(btrim(message)) >= 1 AND char_length(message) <= 2000", name="message"
        ),
        CheckConstraint("jsonb_typeof(evidence) = 'array'", name="evidence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    review_request_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "reviews_review_requests.id", name="fk_reviews_review_replies_review_request_id"
        ),
    )
    message: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    alternative_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    replied_by: Mapped[UUID] = mapped_column(Uuid)
    replied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ChallengeRow(Base):
    """A Challenge (Story 9.5): someone disputes an Estimate Version, an Assessment or one of
    its Findings (`target_*`, at `target_version`: the Assessment's version for a Finding)
    with a reason, while `estimate_version_id` is the version in context. `suggested`: the
    Assessments the platform proposed rerunning, stored at raise (`[{agent, why, tag}]`);
    `confirmed`: the agents the owner confirmed. Only its status, `confirmed`,
    `decline_reason`, `workflow_run_id` and (Story 9.6) `new_version_id` ever change, bumping
    `row_version`. Never deleted."""

    __tablename__ = "reviews_challenges"
    __table_args__ = (
        Index(None, "opportunity_id"),
        Index(None, "review_request_id"),
        CheckConstraint(
            "target_kind IN ('estimate_version', 'assessment', 'finding')", name="target_kind"
        ),
        CheckConstraint(
            "status IN ('awaiting_confirmation', 'reassessing', 'completed', 'declined', 'failed')",
            name="status",
        ),
        CheckConstraint(
            "char_length(btrim(reason)) >= 1 AND char_length(reason) <= 1000", name="reason"
        ),
        CheckConstraint(
            "(status = 'declined') = (decline_reason IS NOT NULL)", name="declined_has_reason"
        ),
        CheckConstraint(
            "decline_reason IS NULL OR (char_length(btrim(decline_reason)) >= 1 "
            "AND char_length(decline_reason) <= 1000)",
            name="decline_reason",
        ),
        CheckConstraint(
            "status IN ('awaiting_confirmation', 'declined') OR workflow_run_id IS NOT NULL",
            name="run_when_confirmed",
        ),
        CheckConstraint("target_version >= 1", name="target_version"),
        CheckConstraint(
            "new_version_id IS NULL OR status = 'completed'", name="new_version_when_completed"
        ),
        Index(
            "ix_reviews_challenges_new_version_id",
            "new_version_id",
            postgresql_where=text("new_version_id IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    target_kind: Mapped[str] = mapped_column(Text)
    target_id: Mapped[UUID] = mapped_column(Uuid)
    target_version: Mapped[int] = mapped_column(Integer)
    assessment_id: Mapped[UUID | None] = mapped_column(Uuid)
    estimate_version_id: Mapped[UUID] = mapped_column(Uuid)
    review_request_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("reviews_review_requests.id", name="fk_reviews_challenges_review_request_id"),
    )
    challenger_id: Mapped[UUID] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text)
    suggested: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    confirmed: Mapped[list[str] | None] = mapped_column(JSONB)
    decline_reason: Mapped[str | None] = mapped_column(Text)
    workflow_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    new_version_id: Mapped[UUID | None] = mapped_column(Uuid)
    """Story 9.6: the Estimate Version the reassessment created (an estimates id, no foreign
    key, AD-2); set when it is `completed`."""
    status: Mapped[str] = mapped_column(Text)
    row_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
