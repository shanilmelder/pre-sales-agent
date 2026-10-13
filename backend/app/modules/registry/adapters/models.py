"""The registry module's tables (Stories 7.1 and 7.6). An Agent's `created_by` holds
identity's user ids without foreign keys (AD-2)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
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


class AgentRow(RowVersioned, Base):
    """An Agent: its unique `agent_id`, name and status. Its configuration lives in the
    immutable config version rows; the newest is current. Never deleted."""

    __tablename__ = "registry_agents"
    __table_args__ = (
        UniqueConstraint("agent_id"),
        CheckConstraint("agent_id ~ '^[a-z][a-z0-9_]*_agent$'", name="agent_id"),
        CheckConstraint("status IN ('active', 'disabled', 'eval_only')", name="status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agent_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class ConfigVersionRow(Base):
    """One immutable config version of an Agent, numbered 1, 2, … per Agent. Insert-only:
    the app role has no UPDATE or DELETE on it."""

    __tablename__ = "registry_agent_config_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "version"),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint(
            "prompt_version >= 1 AND input_schema_version >= 1 AND output_schema_version >= 1",
            name="versions",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    agent_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("registry_agents.agent_id", name="fk_registry_agent_config_versions_agent_id"),
    )
    version: Mapped[int] = mapped_column(Integer)
    semver: Mapped[str] = mapped_column(Text)
    model_profile: Mapped[str] = mapped_column(Text)
    model_digest: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[int] = mapped_column(Integer)
    input_schema_version: Mapped[int] = mapped_column(Integer)
    output_schema_version: Mapped[int] = mapped_column(Integer)
    contract_version: Mapped[str] = mapped_column(Text)
    tool_permissions: Mapped[list[str]] = mapped_column(JSONB)
    budgets: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)


class EvalResultRow(Base):
    """One evaluation result (Story 7.6). Insert-only: the app role has no UPDATE or DELETE.
    A passed row is `accepted` and becomes the comparison point for the next eval."""

    __tablename__ = "registry_eval_results"
    __table_args__ = (
        Index(None, "accepted", "created_at"),
        CheckConstraint("reference_set_version ~ '^[0-9a-f]{12}$'", name="reference_set_version"),
        CheckConstraint(
            "opportunity_count >= 0 AND draft_count >= 0 AND pending_count >= 0 "
            "AND tokens >= 0 AND gpu_seconds >= 0 AND cost_minor >= 0",
            name="counts",
        ),
        CheckConstraint("cost_currency ~ '^[A-Z]{3}$'", name="cost_currency"),
        CheckConstraint("passed OR NOT accepted", name="accepted"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    reference_set_version: Mapped[str] = mapped_column(Text)
    config_version_ids: Mapped[dict[str, Any]] = mapped_column(JSONB)
    model_digests: Mapped[dict[str, Any]] = mapped_column(JSONB)
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(JSONB)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB)
    bars: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    failures: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    opportunity_count: Mapped[int] = mapped_column(Integer)
    draft_count: Mapped[int] = mapped_column(Integer)
    pending_count: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(BigInteger)
    gpu_seconds: Mapped[float] = mapped_column(Float)
    cost_minor: Mapped[int] = mapped_column(BigInteger)
    cost_currency: Mapped[str] = mapped_column(Text)
    passed: Mapped[bool] = mapped_column(Boolean)
    accepted: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=_NOW)
