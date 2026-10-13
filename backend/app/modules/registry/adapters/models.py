"""The registry module's tables (Story 7.1). `created_by` holds identity's user ids without
foreign keys (AD-2)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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
