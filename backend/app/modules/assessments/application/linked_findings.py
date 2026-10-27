"""Critic and Red Team Findings behind an Estimate line (Story 9.9, for `estimates`' lineage).

`linked_review_findings`: the Critic Reviews of an assessment run and the Red Team Reviews of
an Estimate Version (current or superseded), keeping the Findings that cite one of the given
Requirements or lines, each with its Review, status and resolution or override. No actor and
no authorization: the caller has checked that the actor may read the Opportunity, and nothing
here depends on who asks.
"""

from collections.abc import Collection
from uuid import UUID

from app.modules.assessments.adapters import repository as repo
from app.modules.assessments.application.findings import finding_decisions
from app.modules.assessments.application.models import LinkedReviewFinding
from app.modules.assessments.application.reviews import requirement_chips
from app.modules.assessments.domain.findings import FindingStatus
from app.modules.assessments.domain.reviews import ReviewStatus, Severity, severity_rank
from app.platform.uow import UnitOfWork


async def linked_review_findings(
    uow: UnitOfWork,
    opportunity_id: UUID,
    *,
    requirement_ids: Collection[UUID],
    line_ids: Collection[UUID] = (),
    run_id: UUID | None = None,
    estimate_version_id: UUID | None = None,
) -> list[LinkedReviewFinding]:
    """The Findings of the run's Critic Reviews and the version's Red Team Reviews that cite
    one of `requirement_ids` or `line_ids`, oldest Review first, then critical to low."""
    reviews = await repo.reviews_for(
        uow, opportunity_id, run_id=run_id, estimate_version_id=estimate_version_id
    )
    if not reviews:
        return []
    by_id = {r.id: r for r in reviews}
    findings = await repo.findings_of_reviews(uow, list(by_id))
    ids = [f.id for f in findings]
    wanted_requirements = {str(r) for r in requirement_ids}
    wanted_lines = set(line_ids)
    chips = await requirement_chips(uow, opportunity_id, findings)
    lines: dict[UUID, list[UUID]] = {}
    for link in await repo.line_links_for(uow, ids):
        lines.setdefault(link.finding_id, []).append(link.line_id)
    kept = [
        f
        for f in findings
        if any(chip.id in wanted_requirements for chip in chips.get(f.id, []))
        or wanted_lines.intersection(lines.get(f.id, []))
    ]
    if not kept:
        return []
    decisions = await finding_decisions(uow, opportunity_id, kept)
    order = {r.id: n for n, r in enumerate(reviews)}
    ranked = sorted(
        kept,
        key=lambda f: (
            order[f.review_id] if f.review_id is not None else len(order),
            severity_rank(f.severity),
            f.position,
        ),
    )
    found: list[LinkedReviewFinding] = []
    for f in ranked:
        review = by_id[f.review_id] if f.review_id is not None else None
        if review is None:  # pragma: no cover - every Finding belongs to a Review
            continue
        decided = decisions[f.id]
        found.append(
            LinkedReviewFinding(
                id=str(f.id),
                review_kind="critic" if review.kind == "critic" else "red_team",
                review_id=str(review.id),
                review_version=review.version,
                review_superseded=review.status != ReviewStatus.CURRENT,
                review_created_at=review.created_at,
                severity=Severity(f.severity),
                title=f.title,
                status=FindingStatus(f.status),
                requirements=chips.get(f.id, []),
                line_ids=[str(line_id) for line_id in lines.get(f.id, [])],
                resolution=decided.resolution,
                override=decided.override,
            )
        )
    return found
