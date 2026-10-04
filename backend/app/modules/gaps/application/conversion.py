"""Converting a Gap into an Assumption (Story 8.4): `mark_converted`.

Called by `estimates` (through `gaps.application.public`) in the Unit of Work that accepts the
Assumption, so the Assumption's acceptance and the Gap's conversion commit together or not at
all. Only an `open` Gap converts; anything else raises `GapNotOpenError` (409
`gap_not_open`), which rolls the whole Unit of Work back. No authorization here: the caller
has authorized accepting the Assumption.

A converted Gap leaves the open-Gaps list, so a later detection (which supersedes only `open`
Gaps) never touches it. Trace and logs carry ids and the Assumption's kind only.
"""

from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.domain.gaps import GAP_SUBJECT_TYPE, ConvertedTo
from app.platform import trace
from app.platform.actor import Actor
from app.platform.errors import GapNotOpenError
from app.platform.logging import get_logger
from app.platform.trace.catalogue import GapsGapConverted
from app.platform.uow import UnitOfWork

NOT_OPEN_DETAIL = (
    "The Gap behind this Assumption is no longer open: it was converted or replaced by a "
    "newer Gap detection."
)
_log = get_logger(__name__)


async def mark_converted(
    uow: UnitOfWork, gap_id: UUID, *, actor: Actor, assumption_kind: str
) -> None:
    """Mark the `open` Gap `converted` to `assumption_kind` (`condition` or `contingency`) and
    trace `gaps.gap.converted`. Raises `GapNotOpenError` unless the Gap is `open`."""
    kind = ConvertedTo(assumption_kind)
    converted = await repo.convert_gap(uow, gap_id, converted_to=kind.value)
    if converted is None:
        raise GapNotOpenError(NOT_OPEN_DETAIL)
    await trace.append(
        uow,
        actor=actor,
        payload=GapsGapConverted(assumption_kind=kind.value, row_version=converted.row_version),
        subject_type=GAP_SUBJECT_TYPE,
        subject_id=gap_id,
        opportunity_id=converted.opportunity_id,
    )
    _log.info(
        "gaps.gap_converted",
        extra={
            "opportunity_id": str(converted.opportunity_id),
            "gap_id": str(gap_id),
            "assumption_kind": kind.value,
        },
    )
