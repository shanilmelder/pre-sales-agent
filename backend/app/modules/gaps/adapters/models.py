"""The gaps module's tables (Story 4.3). `opportunity_id` and `requirement_id` hold ids owned
by other modules without foreign keys (AD-2)."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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
_FALSE = text("false")
_TRUE = text("true")
"""`QuestionRow` has a `text` column, which shadows `text()` inside its class body."""


DISMISSED_FIELDS = (
    "CASE WHEN status = 'dismissed' THEN "
    "dismiss_reason_kind IS NOT NULL AND dismissed_by IS NOT NULL AND dismissed_at IS NOT NULL "
    "AND (dismiss_reason_kind = 'not_relevant' OR dismiss_note IS NOT NULL) "
    "ELSE dismiss_reason_kind IS NULL AND dismiss_note IS NULL AND dismissed_by IS NULL "
    "AND dismissed_at IS NULL END"
)
"""The dismissal fields are set only while a Gap is `dismissed`, and then all of them (the
note only for `other`, where it is required)."""

QUESTION_APPROVED_IFF_STATUS = (
    "(status IN ('approved', 'sent', 'unanswered', 'answered')) = (approved_by IS NOT NULL)"
)
"""A question's approval is recorded while it is approved, and kept once it is sent or
answered."""
QUESTION_SENT_FIELDS = (
    "(status IN ('sent', 'unanswered', 'answered')) = (sent_on IS NOT NULL) "
    "AND (sent_on IS NULL) = (sent_by IS NULL)"
)
"""When and by whom a question was sent is set only while `sent | unanswered | answered`, both
or neither."""
ANSWERED_FIELDS = (
    "(status = 'answered') = (answered_on IS NOT NULL) "
    "AND (answered_on IS NULL) = (answered_by IS NULL) "
    "AND (answered_on IS NULL) = (answer_passage_id IS NULL)"
)
"""When, by whom and with which passage a question or Gap was answered (Story 4.7) is set
only while `answered`, all or none."""


class DetectionRow(Base):
    """One run of `gaps.detect_gaps` for an Opportunity. Inserted `queued` with its job;
    `error_code` is set only when `failed`. Counts are set when it succeeds."""

    __tablename__ = "gaps_detections"
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
    gap_count: Mapped[int | None] = mapped_column(Integer)
    dropped_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GapRow(RowVersioned, Base):
    """A Gap of an Opportunity. Story 4.2: the detection also raises `mandatory_checklist`
    Gaps, unique per (Opportunity, Checklist id, item id), which are never superseded.
    Detection inserts `open`, `detected` Gaps, and a later
    detection marks them `superseded`. Accepting an Assumption made from an `open` Gap marks it
    `converted`, recording the Assumption's kind in `converted_to` (Story 8.4). Story 4.4: a
    person may change an `open` Gap's impact, dismiss it (`dismiss_*` / `dismissed_*`, set only
    while `dismissed`, a note required for `other`) and reopen it. `changed_by`: the person
    behind its latest change; `touched_by_human`: set by an impact change or a reopen, so a
    later detection keeps it."""

    __tablename__ = "gaps_gaps"
    __table_args__ = (
        Index(None, "opportunity_id", "status"),
        CheckConstraint(
            "category IN ('data_volumes', 'versions_and_platforms', 'integration_details', "
            "'security_and_compliance', 'non_functional', 'scope_and_ownership', "
            "'commercial', 'other')",
            name="category",
        ),
        CheckConstraint("impact IN ('high', 'medium', 'low')", name="impact"),
        CheckConstraint("origin IN ('detected', 'mandatory_checklist')", name="origin"),
        CheckConstraint(
            "status IN ('open', 'superseded', 'converted', 'dismissed', 'answered')",
            name="status",
        ),
        CheckConstraint(
            "converted_to IS NULL OR converted_to IN ('condition', 'contingency')",
            name="converted_to",
        ),
        CheckConstraint(
            "(status = 'converted') = (converted_to IS NOT NULL)", name="converted_has_kind"
        ),
        CheckConstraint(
            "dismiss_reason_kind IS NULL OR dismiss_reason_kind IN ('not_relevant', 'other')",
            name="dismiss_reason_kind",
        ),
        CheckConstraint(DISMISSED_FIELDS, name="dismissed_fields"),
        CheckConstraint(ANSWERED_FIELDS, name="answered_fields"),
        Index(
            "uq_gaps_gaps_mandatory_item",
            "opportunity_id",
            text("(trigger ->> 'checklist_id')"),
            text("(trigger ->> 'item_id')"),
            unique=True,
            postgresql_where=text("origin = 'mandatory_checklist'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB)
    why_it_matters: Mapped[str] = mapped_column(Text)
    impact: Mapped[str] = mapped_column(Text)
    impact_basis: Mapped[str] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    detection_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("gaps_detections.id"))
    converted_to: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    dismiss_reason_kind: Mapped[str | None] = mapped_column(Text)
    dismiss_note: Mapped[str | None] = mapped_column(Text)
    dismissed_by: Mapped[UUID | None] = mapped_column(Uuid)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_by: Mapped[UUID | None] = mapped_column(Uuid)
    touched_by_human: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    answered_on: Mapped[date | None] = mapped_column(Date)
    answered_by: Mapped[UUID | None] = mapped_column(Uuid)
    answer_passage_id: Mapped[UUID | None] = mapped_column(Uuid)
    checklist_applies: Mapped[bool] = mapped_column(Boolean, server_default=_TRUE)
    """Story 4.2: for a `mandatory_checklist` Gap in any status, whether its Checklist item
    is still a mandatory item of an applicable version (set by every detection); true for
    every other Gap."""
    why_entry_id: Mapped[UUID | None] = mapped_column(Uuid)
    """Story 4.2: the catalogue entry (Integration Type or Work Package) the Gap's
    `why_it_matters` names, from its Checklist item; no foreign key (AD-2)."""


class GapHistoryRow(Base):
    """One human (or conversion) change of a Gap (Story 4.4). Insert-only. `actor_id`: the
    person, or null when no person made it. `old_impact` / `new_impact` for
    `impact_changed`, `reason_kind` for `dismissed`, `reason` (the reason or dismissal note)
    for `impact_changed`, `dismissed` and `reopened`."""

    __tablename__ = "gaps_gap_history"
    __table_args__ = (
        Index(None, "gap_id", "at"),
        CheckConstraint(
            "kind IN ('impact_changed', 'dismissed', 'reopened', 'converted', 'answered')",
            name="kind",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    gap_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("gaps_gaps.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[UUID | None] = mapped_column(Uuid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
    old_impact: Mapped[str | None] = mapped_column(Text)
    new_impact: Mapped[str | None] = mapped_column(Text)
    reason_kind: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)


class GapRequirementRow(Base):
    """A Gap relates to a Requirement at a version. Insert-only."""

    __tablename__ = "gaps_gap_requirements"

    gap_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("gaps_gaps.id", ondelete="CASCADE"), primary_key=True
    )
    requirement_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    requirement_version: Mapped[int] = mapped_column(Integer)


class QuestionRow(RowVersioned, Base):
    """The Clarification Question drafted for a Gap (one per Gap in the demo). Story 4.5: a
    person may edit its text and topic (`edited_by_human`) and approve it (`approved_by` /
    `approved_at`); editing an approved question returns it to `drafted`. Story 4.6: an
    approved question may be marked `sent` (`sent_on` / `sent_by`), then `unanswered`; the
    approval fields are set while `approved | sent | unanswered`, the sent fields while
    `sent | unanswered`. `changed_by`: the person behind its latest change."""

    __tablename__ = "gaps_clarification_questions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('drafted', 'approved', 'sent', 'unanswered', 'answered', 'superseded')",
            name="status",
        ),
        CheckConstraint("(approved_at IS NULL) = (approved_by IS NULL)", name="approved_has_by"),
        CheckConstraint(QUESTION_APPROVED_IFF_STATUS, name="approved_iff_status"),
        CheckConstraint(QUESTION_SENT_FIELDS, name="sent_fields"),
        CheckConstraint(ANSWERED_FIELDS, name="answered_fields"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    gap_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("gaps_gaps.id", ondelete="CASCADE"), unique=True
    )
    text: Mapped[str] = mapped_column(Text)
    topic: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=_NOW
    )
    approved_by: Mapped[UUID | None] = mapped_column(Uuid)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_by_human: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    changed_by: Mapped[UUID | None] = mapped_column(Uuid)
    sent_on: Mapped[date | None] = mapped_column(Date)
    sent_by: Mapped[UUID | None] = mapped_column(Uuid)
    answered_on: Mapped[date | None] = mapped_column(Date)
    answered_by: Mapped[UUID | None] = mapped_column(Uuid)
    answer_passage_id: Mapped[UUID | None] = mapped_column(Uuid)
    from_checklist: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    """Story 4.2: drafted from a mandatory Checklist item's wording, not by the agent."""


class AnswerMatchRow(RowVersioned, Base):
    """`clarification_agent`'s suggestion that a passage of a Source answers a question
    (Story 4.7): `suggested` until a person confirms it (`confirmed`, which answers the
    question) or says it is not an answer (`rejected`); `superseded` once the question is
    answered another way. One row per (question, passage), so a rejected pair is never
    suggested again. `injection_suspected`: the passage reads like an instruction to the
    platform. `passage_id` is an `intake_source_passages` id (no foreign key: AD-2)."""

    __tablename__ = "gaps_answer_matches"
    __table_args__ = (
        Index(None, "opportunity_id", "status"),
        UniqueConstraint("question_id", "passage_id"),
        CheckConstraint(
            "status IN ('suggested', 'confirmed', 'rejected', 'superseded')", name="status"
        ),
        CheckConstraint(
            "(status IN ('confirmed', 'rejected')) = (decided_by IS NOT NULL) "
            "AND (decided_by IS NULL) = (decided_at IS NULL)",
            name="decided_fields",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    opportunity_id: Mapped[UUID] = mapped_column(Uuid)
    question_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("gaps_clarification_questions.id", ondelete="CASCADE")
    )
    passage_id: Mapped[UUID] = mapped_column(Uuid)
    injection_suspected: Mapped[bool] = mapped_column(Boolean, server_default=_FALSE)
    status: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
