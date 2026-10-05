"""The Opportunity's Decision Trace, read-only (Story 9.8, demo slice; FR-41).

Anyone who can read the Opportunity (sales representatives included) reads its trace;
anyone else gets the same 404 `not_found` as for an unknown id. There is no write path:
trace rows are appended only by `app.platform.trace.append` and the app role can't change
them. This returns only the stored payloads (ids, counts, kinds) and logs nothing new.
"""

from typing import Any
from uuid import UUID

from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Principal
from app.modules.opportunities.adapters import repository
from app.modules.opportunities.adapters.repository import TraceRecord
from app.modules.opportunities.application.models import (
    TraceActor,
    TraceEventItem,
    TraceFilterOptions,
    TracePage,
    TraceSubject,
)
from app.modules.opportunities.application.opportunities import UNKNOWN_USER, readable_resource
from app.platform.trace.catalogue import CATALOGUE
from app.platform.uow import UnitOfWork

TRACE_DEFAULT_PAGE_SIZE = 50
TRACE_MAX_PAGE_SIZE = 100
SYSTEM_NAME = "System"
AGENT_SUFFIX = "agent"


def agent_name(actor_id: str) -> tuple[str, str | None]:
    """An agent actor id (`<agent_id>@<semver>`) as its role in words and its version, e.g.
    `red_team_agent@1.0.0` -> ("Red Team Agent", "1.0.0"). An id without `@` has no
    version."""
    agent_id, _, version = actor_id.partition("@")
    words = [word for word in agent_id.split("_") if word]
    if not words or words[-1] != AGENT_SUFFIX:
        words.append(AGENT_SUFFIX)
    return " ".join(word.capitalize() for word in words), version or None


def _user_id(actor_id: str) -> UUID | None:
    try:
        return UUID(actor_id)
    except ValueError:
        return None


def _actor(record: TraceRecord, names: dict[UUID, str]) -> TraceActor:
    if record.actor_type == "agent":
        name, version = agent_name(record.actor_id)
        return TraceActor(type="agent", id=record.actor_id, name=name, version=version)
    if record.actor_type == "user":
        user_id = _user_id(record.actor_id)
        name = names.get(user_id, UNKNOWN_USER) if user_id else UNKNOWN_USER
        return TraceActor(type="user", id=record.actor_id, name=name)
    return TraceActor(type="system", id=record.actor_id, name=SYSTEM_NAME)


def ordered_payload(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """The payload's fields in catalogue order (JSONB doesn't keep key order); fields the
    model doesn't know (or an unknown event type's) follow in their stored order."""
    model = CATALOGUE.get(event_type)
    known = [] if model is None else [name for name in model.model_fields if name in payload]
    rest = [name for name in payload if name not in known]
    return {name: payload[name] for name in (*known, *rest)}


async def trace_page(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    *,
    page: int,
    page_size: int,
    subject_type: str | None = None,
    actor_type: str | None = None,
    event_type: str | None = None,
) -> TracePage:
    """One page of the Opportunity's trace, newest first, with the filter options present
    on it. Filters are exact matches; an unknown value gives an empty page."""
    await readable_resource(uow, actor, opportunity_id)
    records, total = await repository.trace_page(
        uow,
        opportunity_id,
        subject_type=subject_type,
        actor_type=actor_type,
        event_type=event_type,
        offset=(page - 1) * page_size,
        limit=page_size,
    )
    subject_types, actor_types, event_types = await repository.trace_options(uow, opportunity_id)
    user_ids = {
        user_id
        for record in records
        if record.actor_type == "user" and (user_id := _user_id(record.actor_id)) is not None
    }
    names = await identity.user_names(uow, user_ids)
    return TracePage(
        items=[
            TraceEventItem(
                id=str(record.id),
                occurred_at=record.occurred_at,
                event_type=record.event_type,
                actor=_actor(record, names),
                subject=TraceSubject(
                    type=record.subject_type,
                    id=str(record.subject_id),
                    version=record.subject_version,
                ),
                payload=ordered_payload(record.event_type, record.payload),
            )
            for record in records
        ],
        page=page,
        page_size=page_size,
        total=total,
        options=TraceFilterOptions(
            subject_types=subject_types, actor_types=actor_types, event_types=event_types
        ),
    )
