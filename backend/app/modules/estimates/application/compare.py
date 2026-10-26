"""Reading one Estimate Version for review, and comparing it with the one before (Story 9.3).

- `version_detail`: the version as the Estimate tab shows it (lines, server totals,
  Assumptions Register and Risks), whatever its status. No authorization: `reviews` reads it
  for a Review Request the caller may see.
- `compare_versions`: a minimal line diff against the version numbered just before. Lines
  are matched by section and title (trimmed, case-insensitive, as a re-draft carries edits);
  when several lines share a key they pair in position order. Story 9.9 extends it.
"""

from collections import defaultdict
from uuid import UUID

from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.application.estimates import version_view
from app.modules.estimates.application.models import (
    EstimateLine,
    EstimateVersion,
    LineDiff,
    VersionDiff,
)
from app.modules.estimates.domain.estimates import section_rank
from app.platform.uow import UnitOfWork


async def version_detail(uow: UnitOfWork, version_id: UUID) -> EstimateVersion | None:
    """`estimates.public.version_detail`: the Estimate Version, or None when unknown."""
    record = await repo.get_version(uow, version_id)
    return None if record is None else await version_view(uow, record)


def _key(line: EstimateLine) -> tuple[str, str]:
    return line.section.value, line.title.strip().casefold()


def _lines(version: EstimateVersion) -> list[EstimateLine]:
    return [line for section in version.sections for line in section.lines]


def _round(value: float) -> float:
    return round(value, 1)


def diff_lines(before: list[EstimateLine], after: list[EstimateLine]) -> list[LineDiff]:
    """The added, removed and changed lines, in template order then title. Pure."""
    older: dict[tuple[str, str], list[EstimateLine]] = defaultdict(list)
    for line in sorted(before, key=lambda line: line.position):
        older[_key(line)].append(line)
    found: list[LineDiff] = []
    for line in sorted(after, key=lambda line: line.position):
        matches = older.get(_key(line))
        if not matches:
            found.append(
                LineDiff(
                    change="added",
                    section=line.section,
                    title=line.title,
                    before_hours=None,
                    after_hours=line.total_hours,
                    delta_hours=_round(line.total_hours),
                )
            )
            continue
        old = matches.pop(0)
        if old.total_hours != line.total_hours or old.role_mix != line.role_mix:
            found.append(
                LineDiff(
                    change="changed",
                    section=line.section,
                    title=line.title,
                    before_hours=old.total_hours,
                    after_hours=line.total_hours,
                    delta_hours=_round(line.total_hours - old.total_hours),
                )
            )
    for left in older.values():
        for old in left:
            found.append(
                LineDiff(
                    change="removed",
                    section=old.section,
                    title=old.title,
                    before_hours=old.total_hours,
                    after_hours=None,
                    delta_hours=_round(-old.total_hours),
                )
            )
    return sorted(found, key=lambda d: (section_rank(d.section), d.title.casefold()))


async def compare_versions(uow: UnitOfWork, version_id: UUID) -> VersionDiff | None:
    """`estimates.public.compare_versions`: the version against the one numbered just
    before it ("First version" when there is none); None when the version is unknown."""
    record = await repo.get_version(uow, version_id)
    if record is None:
        return None
    after = await version_view(uow, record)
    previous = (
        None
        if record.version <= 1
        else await repo.version_by_number(uow, record.opportunity_id, record.version - 1)
    )
    if previous is None:
        return VersionDiff(
            version=record.version,
            previous_version=None,
            first=True,
            lines=[],
            total_before=None,
            total_after=after.totals.total_hours,
            total_delta=0.0,
        )
    before = await version_view(uow, previous)
    return VersionDiff(
        version=record.version,
        previous_version=previous.version,
        first=False,
        lines=diff_lines(_lines(before), _lines(after)),
        total_before=before.totals.total_hours,
        total_after=after.totals.total_hours,
        total_delta=_round(after.totals.total_hours - before.totals.total_hours),
    )
