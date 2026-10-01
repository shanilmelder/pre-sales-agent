"""`append`: the only code that writes trace rows (AD-12)."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import insert

from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.trace.catalogue import CATALOGUE, TracePayload
from app.platform.trace.models import TraceEvent
from app.platform.uow import UnitOfWork


class UnknownTraceEventError(LookupError):
    """A payload whose class is not the catalogue's model for its `event_type`. This is a
    programming error, so it is deliberately not a `ProblemError` (it surfaces as a 500)."""


async def append(
    uow: UnitOfWork,
    *,
    actor: Actor,
    payload: TracePayload,
    subject_type: str,
    subject_id: UUID,
    opportunity_id: UUID | None = None,
    workflow_run_id: UUID | None = None,
    subject_version: int | None = None,
) -> UUID:
    """Insert one trace row inside the caller's transaction and return its UUIDv7 id.

    The row commits or rolls back with everything else in the Unit of Work."""
    event_type = getattr(type(payload), "event_type", None)
    if event_type is None or CATALOGUE.get(event_type) is not type(payload):
        raise UnknownTraceEventError(f"{type(payload).__name__} is not in the trace catalogue")

    event_id = new_id()
    await uow.session.execute(
        insert(TraceEvent).values(
            id=event_id,
            opportunity_id=opportunity_id,
            workflow_run_id=workflow_run_id,
            actor_type=actor.type,
            actor_id=actor.id,
            event_type=event_type,
            subject_type=subject_type,
            subject_id=subject_id,
            subject_version=subject_version,
            payload=payload.model_dump(mode="json"),
            occurred_at=datetime.now(UTC),
        )
    )
    return event_id
