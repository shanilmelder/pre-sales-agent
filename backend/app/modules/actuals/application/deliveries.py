"""Close delivery (Story 10.1).

`close_delivery` (action `actuals.delivery.close`: delivery managers who can read the
Opportunity, people only) with `If-Match` the Actuals tab's `row_version`, in one Unit of Work:
authorize, the shared Opportunity lock, the `If-Match` check (412 when stale), then a Baseline
must exist (409 `actuals_no_baseline`), delivery must still be open (409 `delivery_closed`)
and every Baseline line must have a final Actual (409 `delivery_not_ready`, e.g. "4 lines have
no final Actual", with `open_line_count`). It inserts the delivery row, which makes the
Opportunity's derived status `delivered`, and traces `actuals.delivery.closed`.
"""

from uuid import UUID

from app.modules.actuals.adapters import repository as repo
from app.modules.actuals.application.models import ActualsView
from app.modules.actuals.application.record import (
    MAX_ROW_VERSION,
    STALE,
    open_baseline,
    start_write,
)
from app.modules.actuals.application.view import build_view
from app.modules.actuals.domain.actuals import (
    DELIVERY_SUBJECT_TYPE,
    ActualKind,
    open_line_count,
    open_lines_message,
)
from app.modules.identity.application.public import Action, Principal
from app.platform import trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import DeliveryNotReadyError, RowVersionMismatchError
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import ActualsDeliveryClosed
from app.platform.uow import UnitOfWork

_log = get_logger(__name__)


async def close_delivery(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, if_match: str | None
) -> ActualsView:
    """`actuals.close_delivery` (module docstring)."""
    resource, user_id = await start_write(uow, actor, opportunity_id, Action.DELIVERY_CLOSE)
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or expected != await repo.change_count(uow, opportunity_id):
        raise RowVersionMismatchError(STALE)
    baseline = await open_baseline(uow, opportunity_id)
    current = await repo.actuals_of(uow, opportunity_id, current_only=True)
    by_line = {r.estimate_line_id: r for r in current if r.estimate_line_id is not None}
    kinds = [
        None if (r := by_line.get(line.id)) is None else ActualKind(r.kind)
        for line in baseline.lines
    ]
    count = open_line_count(kinds)
    if count:
        raise DeliveryNotReadyError(open_lines_message(count), open_line_count=count)

    stored = await repo.insert_delivery(
        uow,
        delivery_id=new_id(),
        opportunity_id=opportunity_id,
        estimate_version_id=baseline.version_id,
        closed_by=user_id,
    )
    counted = [r for r in current if r.estimate_version_id == baseline.version_id]
    await trace.append(
        uow,
        actor=actor.actor,
        payload=ActualsDeliveryClosed(
            delivery_id=str(stored.id),
            estimate_version_id=str(baseline.version_id),
            estimate_version=baseline.version,
            line_count=len(baseline.lines),
            actual_count=len(counted),
        ),
        subject_type=DELIVERY_SUBJECT_TYPE,
        subject_id=stored.id,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "actuals.delivery_closed",
        extra={
            "opportunity_id": str(opportunity_id),
            "version": baseline.version,
            "actor_id": actor.actor.id,
        },
    )
    return await build_view(uow, actor, resource, opportunity_id)
