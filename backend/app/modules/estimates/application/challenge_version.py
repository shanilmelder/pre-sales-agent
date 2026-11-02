"""The Estimate Version a Challenge's reassessment run creates (Story 9.6; FR-38).

The run's final node (`new_version`, in `workflows`) calls, in one Unit of Work:

- `challenge_lines`: the new version's lines. The challenged version's lines are copied
  verbatim (edits included), except those covering a Requirement whose sizing a confirmed
  agent's rerun changed (its rerun Assessment against its previous one, as `pairs`): those
  take the hours, role mix and basis `build_lines` gives over the current Assessments
  (`domain.from_assessments.rebuild_changed`).
- `create_version_from_run`: stores them through `store_version` with `source` `challenge`,
  `source_run_id` the run, the challenged version as `base` (its accepted Assumptions, Risks
  and the edits of the lines the rerun did not rebuild are carried) and the node's
  `idempotency_key`; superseding the current draft and queueing the Red Team Review on the
  new version, as every new version does. A replay finds the version already stored for the
  run (a unique index on `source_run_id` for `challenge`) and stores nothing. When a version
  newer than `latest_at_start` exists (someone created one while the run worked), or the
  challenged version was not the latest when the run was queued (a newer draft would be
  superseded), nothing is stored: `estimate_changed`.
- `challenge_delta`: the per-line hours delta between the challenged and the new version
  (`compare.diff_lines`, the 9.9 diff), with the lines' ids and positions, and the total.

No model call; the system is the actor. Logs carry ids and counts only.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.application.compare import _key, _lines, _round, diff_lines
from app.modules.estimates.application.draft import store_version
from app.modules.estimates.application.estimates import version_view
from app.modules.estimates.application.versions import _copied_lines
from app.modules.estimates.domain.estimates import VersionSource
from app.modules.estimates.domain.from_assessments import (
    ActiveRequirement,
    AgentSizing,
    ChallengeLines,
    build_lines,
    changed_requirements,
    rebuild_changed,
)
from app.modules.intake.application import public as intake
from app.platform.actor import Actor
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.uow import UnitOfWork

CREATE_VERSION_FROM_RUN = "estimates.create_version_from_run"
_SYSTEM = Actor(type="system", id=CREATE_VERSION_FROM_RUN)
_log = get_logger(__name__)


async def challenge_lines(
    uow: UnitOfWork,
    opportunity_id: UUID,
    base_version_id: UUID,
    pairs: Sequence[tuple[AgentSizing | None, AgentSizing]],
    current: Sequence[AgentSizing],
) -> ChallengeLines:
    """The new version's lines (module docstring): `pairs` holds each confirmed agent's
    previous and rerun Assessment, `current` every agent's current one."""
    snapshots = await intake.active_requirement_snapshots(uow, opportunity_id)
    rebuilt = build_lines(
        [
            ActiveRequirement(
                id=s.id,
                version=s.version,
                number=s.number,
                classification=s.classification,
                text=s.text,
            )
            for s in snapshots
        ],
        current,
    )
    base = await _copied_lines(uow, base_version_id)
    return rebuild_changed(base, rebuilt.lines, changed_requirements(pairs))


@dataclass(frozen=True, slots=True)
class ChallengeVersion:
    """What `create_version_from_run` did: the version stored for the run (`created` False on
    a replay), or none because the Estimate changed while the run worked."""

    version_id: UUID | None
    created: bool
    estimate_changed: bool = False


async def latest_version_number(uow: UnitOfWork, opportunity_id: UUID) -> int:
    """The Opportunity's highest Estimate Version number, 0 before the first."""
    return await repo.latest_version_number(uow, opportunity_id)


async def create_version_from_run(
    uow: UnitOfWork,
    run_id: UUID,
    base_version_id: UUID,
    lines: ChallengeLines,
    reason: str | None,
    idempotency_key: str,
    *,
    latest_at_start: int | None = None,
    created_by: UUID | None = None,
) -> ChallengeVersion:
    """Store the Challenge run's new draft version (module docstring). The caller has
    checked the run and the base."""
    base = await repo.get_version(uow, base_version_id)
    if base is None:  # pragma: no cover - the Challenge's version in context
        raise LookupError(f"No Estimate Version {base_version_id}")
    ids = {"opportunity_id": str(base.opportunity_id), "run_id": str(run_id)}
    await opportunity_lock(uow, base.opportunity_id)
    existing = await repo.challenge_version_of(uow, run_id)
    if existing is not None:
        _log.info(
            "estimates.challenge_version_replayed", extra={**ids, "version_id": str(existing.id)}
        )
        return ChallengeVersion(version_id=existing.id, created=False)
    latest = await repo.latest_version_number(uow, base.opportunity_id)
    # A newer version than the challenged one, whether made while the run worked or already
    # there when it was queued (a draft `store_version` would supersede), is not overwritten.
    if latest_at_start is not None and (latest > latest_at_start or base.version != latest):
        _log.info(
            "estimates.challenge_version_estimate_changed",
            extra={**ids, "latest": latest, "latest_at_start": latest_at_start},
        )
        return ChallengeVersion(version_id=None, created=False, estimate_changed=True)
    snapshots = await intake.active_requirement_snapshots(uow, base.opportunity_id)
    stored = await store_version(
        uow,
        base.opportunity_id,
        lines.lines,
        active=[(s.id, s.version) for s in snapshots],
        dropped=0,
        requirement_count=len(snapshots),
        actor=_SYSTEM,
        source=VersionSource.CHALLENGE,
        source_run_id=run_id,
        created_by=created_by,
        base=base,
        reason=reason,
        idempotency_key=idempotency_key,
        skip_edits=lines.rebuilt,
    )
    _log.info(
        "estimates.challenge_version_created",
        extra={
            **ids,
            "version_id": str(stored.version_id),
            "base_version_id": str(base.id),
            "rebuilt_count": len(lines.rebuilt),
            "line_count": len(lines.lines),
        },
    )
    return ChallengeVersion(version_id=stored.version_id, created=True)


@dataclass(frozen=True, slots=True)
class LineDelta:
    """One line the reassessment changed: its id (the new version's line; the challenged
    one's when removed), position, title and hours."""

    line_id: UUID
    position: int
    title: str = field(repr=False)
    before_h: float | None
    after_h: float | None
    delta_h: float


@dataclass(frozen=True, slots=True)
class ChallengeDelta:
    previous_version_id: UUID
    previous_version: int
    new_version_id: UUID
    new_version: int
    lines: tuple[LineDelta, ...]
    total_delta_h: float


async def challenge_delta(
    uow: UnitOfWork, previous_version_id: UUID, new_version_id: UUID
) -> ChallengeDelta:
    """The changed lines between the challenged and the new version (9.9's `diff_lines`)."""
    previous = await repo.get_version(uow, previous_version_id)
    new = await repo.get_version(uow, new_version_id)
    if previous is None or new is None:  # pragma: no cover - both just read or stored
        raise LookupError("No such Estimate Version")
    before = await version_view(uow, previous)
    after = await version_view(uow, new)
    old_lines, new_lines = _lines(before), _lines(after)
    by_key_new: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for line in sorted(new_lines, key=lambda line: line.position):
        by_key_new.setdefault(_key(line), []).append((line.id, line.position))
    by_key_old: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for line in sorted(old_lines, key=lambda line: line.position):
        by_key_old.setdefault(_key(line), []).append((line.id, line.position))
    deltas: list[LineDelta] = []
    for diff in diff_lines(old_lines, new_lines):
        key = (diff.section.value, diff.title.strip().casefold())
        pool = by_key_old if diff.change == "removed" else by_key_new
        found = pool.get(key) or []
        line_id, position = found.pop(0) if found else ("", 0)
        if not line_id:  # pragma: no cover - every diff comes from one of the two
            continue
        deltas.append(
            LineDelta(
                line_id=UUID(line_id),
                position=position,
                title=diff.title,
                before_h=diff.before_hours,
                after_h=diff.after_hours,
                delta_h=diff.delta_hours,
            )
        )
    deltas.sort(key=lambda d: d.position)
    return ChallengeDelta(
        previous_version_id=previous.id,
        previous_version=previous.version,
        new_version_id=new.id,
        new_version=new.version,
        lines=tuple(deltas),
        total_delta_h=_round(after.totals.total_hours - before.totals.total_hours),
    )
