"""Submission blockers (Story 8.6; AD-27, FR-14): the only code that decides whether an
Estimate Version can be submitted.

`get_submission_blockers(uow, version_id)` lists, as typed items with a link to each subject:

- `gap`: the Opportunity's open Gaps (`gaps.open_gap_summaries`; open Unknowns are open Gaps);
- `assumption`: the version's unaccepted Assumptions;
- `conflict`: the open and escalated Conflicts (`conflicts.list_open`, the conflicts
  module's own `BLOCKING` set);
- `finding`: the open critical Findings of the current Critic and Red Team Reviews
  (`assessments.get_blocking_findings`; an overridden or resolved one no longer blocks);
- `uncovered_requirement`: active Requirements (`intake.active_requirement_snapshots`) that
  no line of the version covers, read live (never the stored `uncovered_count`);
- `review_request` (`to_baseline`, Story 9.1): the version's pending, rejected and challenged
  Review Requests (`reviews.list_open_requests`), titled "{Type} review · {Reviewer} ·
  {Status}", each linking to its row on the Estimate tab (`?review={id}`);
- `no_review_request` (`to_baseline`, Story 9.7): a submitted version no Review Request was
  sent for (none that isn't cancelled), "No Review Request sent yet".

Story 9.7: once a version is past the draft, `to_baseline` also repeats the content checks
(Gaps, Assumptions, Conflicts, Findings, uncovered Requirements), which can reopen after
submit. The Baseline gate and `estimates.set_baseline` read this one list.

`submission_blocker_counts(uow, opportunity_ids)` is the same rule counted for a page of
Opportunities with one batched query per module, never one per row; it always equals
`len(to_submit)` for each Opportunity's current version.

No authorization here: callers have checked that the actor may read the Opportunity.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from app.modules.conflicts.application import public as conflicts
from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import VersionRecord
from app.modules.estimates.application.models import Blocker, SubmissionBlockers
from app.modules.estimates.domain.assumptions import AssumptionKind
from app.modules.estimates.domain.estimates import VersionStatus
from app.modules.gaps.application import public as gaps
from app.modules.intake.application import public as intake
from app.platform.uow import UnitOfWork

TITLE_MAX = 120
REVIEW_NAMES = {"red_team": "Red Team", "critic": "Critic"}


def _clip(text: str, limit: int = TITLE_MAX) -> str:
    """`text` on one line, at most `limit` code points, ending in `…` when cut."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _words(value: str) -> str:
    return value.replace("_", " ")


def href(opportunity_id: UUID, tab: str, anchor: str) -> str:
    """The web path of a subject: its workspace tab, with the row's anchor."""
    return f"/opportunities/{opportunity_id}/{tab}#{anchor}"


async def _gap_blockers(uow: UnitOfWork, opportunity_id: UUID) -> list[Blocker]:
    return [
        Blocker(
            kind="gap",
            subject_id=str(g.id),
            title=_clip(g.title),
            detail=f"{g.impact.capitalize()} impact {_words(g.category)} Gap. Answer it, "
            "convert it to an Assumption or dismiss it.",
            href=href(opportunity_id, "gaps", f"gap-{g.id}"),
        )
        for g in await gaps.open_gap_summaries(uow, opportunity_id)
    ]


async def _assumption_blockers(uow: UnitOfWork, version: VersionRecord) -> list[Blocker]:
    found: list[Blocker] = []
    for a in await repo.assumptions_of(uow, version.id, unaccepted_only=True):
        kind = AssumptionKind(a.kind)
        hours = "" if a.amount_hours is None else f", {a.amount_hours:.1f} h"
        found.append(
            Blocker(
                kind="assumption",
                subject_id=str(a.id),
                title=_clip(a.wording),
                detail=f"{kind.value.capitalize()}{hours}, not accepted. It needs a named "
                "accepting person.",
                href=href(version.opportunity_id, "estimate", f"assumption-{a.id}"),
            )
        )
    return found


async def _conflict_blockers(uow: UnitOfWork, opportunity_id: UUID) -> list[Blocker]:
    return [
        Blocker(
            kind="conflict",
            subject_id=c.id,
            title=_clip(c.summary),
            detail=f"{c.severity.value.capitalize()} {_words(c.type.value)} Conflict, "
            f"{c.status.value}. It needs a decision.",
            href=href(opportunity_id, "conflicts", f"conflict-{c.id}"),
        )
        for c in await conflicts.list_open(uow, opportunity_id)
    ]


async def _finding_blockers(uow: UnitOfWork, opportunity_id: UUID) -> list[Blocker]:
    # Imported here: assessments imports estimates' public API, which imports this module.
    from app.modules.assessments.application import public as assessments

    return [
        Blocker(
            kind="finding",
            subject_id=str(f.finding_id),
            title=_clip(f.title),
            detail=f"Critical {REVIEW_NAMES.get(f.review_kind, _words(f.review_kind))} "
            f"Finding, Review v{f.review_version}. Resolve or override it.",
            href=href(opportunity_id, "assessments", f"finding-{f.finding_id}"),
        )
        for f in await assessments.get_blocking_findings(uow, opportunity_id)
    ]


async def _uncovered_blockers(uow: UnitOfWork, version: VersionRecord) -> list[Blocker]:
    covered = (await repo.covered_requirement_ids(uow, [version.id]))[version.id]
    return [
        Blocker(
            kind="uncovered_requirement",
            subject_id=str(r.id),
            title=f"R{r.number} not covered",
            detail=f"No line in Estimate v{version.version} covers it: {_clip(r.text, 100)}",
            href=href(version.opportunity_id, "requirements", f"requirement-{r.id}"),
        )
        for r in await intake.active_requirement_snapshots(uow, version.opportunity_id)
        if r.id not in covered
    ]


def _sent(when: datetime) -> str:
    """E.g. "Sent 24 Oct"."""
    return f"Sent {when.day} {when:%b}"


async def _review_blockers(uow: UnitOfWork, version: VersionRecord) -> list[Blocker]:
    # Imported here: reviews imports estimates' public API, which imports this module.
    from app.modules.reviews.application import public as reviews

    found: list[Blocker] = []
    for r in await reviews.list_open_requests(uow, version.id):
        detail = _sent(r.created_at)
        if r.message:
            detail += f" · {_clip(r.message, 100)}"
        found.append(
            Blocker(
                kind="review_request",
                subject_id=str(r.id),
                title=f"{reviews.REVIEW_TYPE_LABELS[r.review_type]} review · {r.reviewer_name} "
                f"· {reviews.STATUS_LABELS[r.status]}",
                detail=detail,
                href=f"/opportunities/{version.opportunity_id}/estimate?review={r.id}",
            )
        )
    return found


NO_REVIEW_REQUEST_TITLE = "No Review Request sent yet"


async def _no_request_blockers(uow: UnitOfWork, version: VersionRecord) -> list[Blocker]:
    """Story 9.7: `no_review_request` when no non-cancelled Review Request counts towards the
    version (a Baseline needs at least one approval)."""
    # Imported here for the reason given in `_review_blockers`.
    from app.modules.reviews.application import public as reviews

    if await reviews.version_approvals(uow, version.id):
        return []
    return [
        Blocker(
            kind="no_review_request",
            subject_id=str(version.id),
            title=NO_REVIEW_REQUEST_TITLE,
            detail=f"Send Estimate v{version.version} for review. A Baseline needs every "
            "requested review to approve it.",
            href=f"/opportunities/{version.opportunity_id}/estimate",
        )
    ]


async def _content_blockers(
    uow: UnitOfWork, opportunity_id: UUID, version: VersionRecord | None
) -> list[Blocker]:
    """The checks submit runs: Gaps, unaccepted Assumptions, Conflicts, Findings and
    uncovered Requirements, in that order."""
    found = await _gap_blockers(uow, opportunity_id)
    if version is not None:
        found += await _assumption_blockers(uow, version)
    found += await _conflict_blockers(uow, opportunity_id)
    found += await _finding_blockers(uow, opportunity_id)
    if version is not None:
        found += await _uncovered_blockers(uow, version)
    return found


async def blockers_for(
    uow: UnitOfWork, opportunity_id: UUID, version: VersionRecord | None
) -> SubmissionBlockers:
    """The blockers of `version` (an Estimate Version of the Opportunity). Before the first
    version only the Opportunity's own (Gaps, Conflicts, Findings) are listed. A version that
    is no longer a draft has passed the submit gate, so it has none to submit; Story 9.7: its
    `to_baseline` lists its open Review Requests, `no_review_request` when none was sent, and
    the content checks submit runs (they can reopen after submit). The Baseline gate and
    `set_baseline` both read this one list."""
    if version is not None and version.status != VersionStatus.DRAFT:
        to_baseline = await _review_blockers(uow, version)
        to_baseline += await _no_request_blockers(uow, version)
        to_baseline += await _content_blockers(uow, opportunity_id, version)
        return SubmissionBlockers(to_submit=[], to_baseline=to_baseline)
    to_submit = await _content_blockers(uow, opportunity_id, version)
    to_baseline = [] if version is None else await _review_blockers(uow, version)
    return SubmissionBlockers(to_submit=to_submit, to_baseline=to_baseline)


async def get_submission_blockers(uow: UnitOfWork, version_id: UUID) -> SubmissionBlockers:
    """`estimates.get_submission_blockers`: the version's submission blockers, read now."""
    version = await repo.get_version(uow, version_id)
    if version is None:
        raise LookupError(f"No Estimate Version {version_id}")
    return await blockers_for(uow, version.opportunity_id, version)


async def current_blockers(
    uow: UnitOfWork, opportunity_id: UUID
) -> tuple[VersionRecord | None, SubmissionBlockers]:
    """The Opportunity's current Estimate Version (its draft, else its latest submitted or
    in-review one) and that version's submission blockers."""
    version = await repo.current_version(uow, opportunity_id)
    return version, await blockers_for(uow, opportunity_id, version)


async def submission_blocker_counts(
    uow: UnitOfWork, opportunity_ids: Sequence[UUID]
) -> dict[UUID, int]:
    """`len(to_submit)` of each of these Opportunities' current version (as
    `current_blockers`), with one batched query per module whatever the count."""
    # Imported here for the reason given in `_finding_blockers`.
    from app.modules.assessments.application import public as assessments

    ids = list(dict.fromkeys(opportunity_ids))
    if not ids:
        return {}
    open_gaps = await gaps.open_gap_counts(uow, ids)
    open_conflicts = await conflicts.open_conflict_counts(uow, ids)
    findings = await assessments.blocking_finding_counts(uow, ids)
    versions = await repo.current_versions(uow, ids)
    version_ids = [v.id for v in versions.values()]
    unaccepted = await repo.unaccepted_counts(uow, version_ids)
    covered = await repo.covered_requirement_ids(uow, version_ids)
    active = await intake.active_requirement_ids(uow, [o for o in ids if o in versions])
    counts: dict[UUID, int] = {}
    for opportunity_id in ids:
        version = versions.get(opportunity_id)
        if version is not None and version.status != VersionStatus.DRAFT:
            counts[opportunity_id] = 0  # submitted or in review: past the gate (`blockers_for`)
            continue
        count = (
            open_gaps.get(opportunity_id, 0)
            + open_conflicts.get(opportunity_id, 0)
            + findings.get(opportunity_id, 0)
        )
        if version is not None:
            count += unaccepted.get(version.id, 0)
            count += len(active.get(opportunity_id, set()) - covered.get(version.id, set()))
        counts[opportunity_id] = count
    return counts
