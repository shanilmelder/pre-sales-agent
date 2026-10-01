"""Append-only trace (AD-12): catalogue rules, `append`, and the DB role can't tamper."""

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast
from uuid import UUID

import psycopg
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from pydantic import ConfigDict, ValidationError
from sqlalchemy.engine import Engine

from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.trace.catalogue import (
    CATALOGUE,
    IdentityUserProvisioned,
    TracePayload,
    is_valid_event_type,
    register,
)
from app.platform.uow import UnitOfWork, UoW
from tests.conftest import make_client, run_async

USER = Actor("user", "u-1")

# --- catalogue -----------------------------------------------------------------------------


def test_catalogue_seeded_with_identity_user_provisioned() -> None:
    assert CATALOGUE["identity.user.provisioned"] is IdentityUserProvisioned


def test_every_event_type_matches_naming_rule() -> None:
    for name, cls in CATALOGUE.items():
        assert is_valid_event_type(name), name
        assert cls.event_type == name


@pytest.mark.parametrize(
    "good",
    ["identity.user.provisioned", "identity.user.role_assigned", "opportunities.opportunity.won"],
)
def test_event_type_rule_accepts(good: str) -> None:
    assert is_valid_event_type(good)


@pytest.mark.parametrize(
    "bad",
    [
        "identity.user.provision",  # not past tense
        "identity.user",  # two segments
        "identity.user.role.assigned",  # four segments
        "Identity.user.provisioned",  # uppercase
        "identity.user-x.provisioned",  # hyphen
    ],
)
def test_event_type_rule_rejects(bad: str) -> None:
    assert not is_valid_event_type(bad)


def test_every_payload_rejects_extra_fields() -> None:
    for cls in CATALOGUE.values():
        assert cls.model_config.get("extra") == "forbid"
        with pytest.raises(ValidationError):
            cls.model_validate({"unexpected": "x"})


def test_register_rejects_bad_name_and_duplicates() -> None:
    class BadName(TracePayload):
        event_type: ClassVar[str] = "identity.user.provision"

    class Duplicate(TracePayload):
        event_type: ClassVar[str] = "identity.user.provisioned"

    with pytest.raises(ValueError, match="must match"):
        register(BadName)
    with pytest.raises(ValueError, match="already registered"):
        register(Duplicate)
    assert CATALOGUE["identity.user.provisioned"] is IdentityUserProvisioned


def test_register_rejects_payload_allowing_extra_fields() -> None:
    class Lenient(TracePayload):
        model_config = ConfigDict(extra="ignore")
        event_type: ClassVar[str] = "identity.user.renamed"

    with pytest.raises(ValueError, match="must forbid extra fields"):
        register(Lenient)
    assert "identity.user.renamed" not in CATALOGUE


# --- append ----------------------------------------------------------------------------------


class _RecordingSession:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1


class NotCatalogued(TracePayload):
    event_type: ClassVar[str] = "identity.user.renamed"


class Impostor(TracePayload):
    """Claims a catalogued event_type with a different model."""

    event_type: ClassVar[str] = "identity.user.provisioned"


@pytest.mark.parametrize("payload", [NotCatalogued(), Impostor()])
def test_append_rejects_unknown_payload_before_writing(payload: TracePayload) -> None:
    session = _RecordingSession()
    uow = UnitOfWork(cast(Any, session))

    async def scenario() -> None:
        await trace.append(
            uow, actor=USER, payload=payload, subject_type="identity.user", subject_id=new_id()
        )

    with pytest.raises(trace.UnknownTraceEventError):
        run_async(scenario())
    assert session.calls == 0


def test_appended_event_is_committed_once_with_v7_id_and_utc_time(
    db_app: FastAPI, sync_engine: Engine
) -> None:
    subject = new_id()

    @db_app.post("/api/v1/test/provision/{subject_id}")
    async def provision(subject_id: UUID, uow: UoW) -> dict[str, str]:
        event_id = await trace.append(
            uow,
            actor=USER,
            payload=IdentityUserProvisioned(),
            subject_type="identity.user",
            subject_id=subject_id,
        )
        return {"event_id": str(event_id)}

    with make_client(db_app) as client:
        resp = client.post(f"/api/v1/test/provision/{subject}")
    assert resp.status_code == 200

    with sync_engine.connect() as conn:
        rows = (
            conn.execute(
                sa.text("SELECT * FROM platform_trace_events WHERE subject_id = :s"),
                {"s": subject},
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1
    row = rows[0]
    assert str(row["id"]) == resp.json()["event_id"]
    assert row["id"].version == 7
    assert row["opportunity_id"] is None
    assert row["workflow_run_id"] is None
    assert row["subject_version"] is None
    assert (row["actor_type"], row["actor_id"]) == ("user", "u-1")
    assert row["event_type"] == "identity.user.provisioned"
    assert row["payload"] == {}
    occurred_at: datetime = row["occurred_at"]
    assert occurred_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(UTC) - occurred_at) < timedelta(minutes=1)


# --- the app role cannot tamper with the trace -------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE platform_trace_events SET actor_id = 'x'",
        "DELETE FROM platform_trace_events",
        "TRUNCATE platform_trace_events",
    ],
)
def test_app_role_cannot_update_or_delete_trace(sync_engine: Engine, statement: str) -> None:
    with sync_engine.connect() as conn:
        role: str = conn.execute(sa.text("SELECT current_user")).scalar_one()
        assert role == "psa_app", "DB-backed tests must run as psa_app (see README)"
        with pytest.raises(sa.exc.ProgrammingError) as info:
            conn.execute(sa.text(statement))
        assert isinstance(info.value.orig, psycopg.errors.InsufficientPrivilege)
        conn.rollback()


def test_app_role_can_read_and_insert_trace(sync_engine: Engine) -> None:
    with sync_engine.connect() as conn:
        privileges: dict[str, bool] = {
            p: conn.execute(
                sa.text("SELECT has_table_privilege('platform_trace_events', :p)"), {"p": p}
            ).scalar_one()
            for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        }
    assert privileges == {
        "SELECT": True,
        "INSERT": True,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
    }
