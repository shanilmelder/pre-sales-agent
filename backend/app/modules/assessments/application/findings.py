"""Blocking Findings and overrides (Story 6.6; FR-29).

**At acceptance** (`stamp`, called by `accept_red_team_review` and `accept_critic_review` in
their Unit of Work, under the Opportunity's Findings lock): each new Finding gets, by code
only, its fingerprint (`domain/findings.py`), whether it is security discipline (it cites a
Security Agent Finding), its `policy_ref` (one of its Requirements is linked to a mandatory
Gap whose `checklist_item` trigger is a mandatory item of a `security` Checklist:
`gaps.security_policies`) and `previous_override_id` (the newest override of a Finding with
the same fingerprint in an earlier Review of the same kind: shown, never applied).

**Commands** (one Unit of Work each; the Opportunity's 404 for those who can't read it, 404
for a Finding not in it; `If-Match` the Finding's `row_version`: 428 without, 412 "Changed by
{name} since you opened it." when stale; 409 `finding_not_open` unless it is `open` and in a
current Review; a reason of 1-1,000 characters, else 422; traced in the same transaction):

- `supply_evidence` (`assessments.finding.resolve`, the `conflicts.conflict.resolve` rules:
  the owner and collaborators except sales representatives): references checked through
  `platform/evidence.resolve_all` and as the Opportunity's own (422 `evidence_unresolvable`),
  stored in `assessments_finding_evidence`; the Finding becomes `resolved` /
  `evidence_supplied`. Trace `assessments.finding.resolved`.
- `mark_resolved` (same rule): `resolved` / `addressed`. Trace `assessments.finding.resolved`.
- `override_finding` (R1, `identity.finding_override_basis`): first 422
  `finding_not_overridable` for a Finding with a `policy_ref`, whoever asks (platform
  administrators included); then 403 unless the caller is the Opportunity's owner, a Head of
  Delivery, or a security reviewer on a security-discipline Finding. Inserts
  `assessments_finding_overrides` and the Finding becomes `overridden`. Trace
  `assessments.finding.overridden` with the person and the reason. Re-applying an earlier
  override is this command on the newer Finding.

`get_blocking_findings`: the `open`, `critical` Findings of the current Critic and Red Team
Reviews (Epic 8's `estimates.get_submission_blockers` reads it).

Logs carry ids, kinds and counts only, never a reason or Finding text.
"""

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.assessments.adapters import repository as repo
from app.modules.assessments.adapters.repository import (
    EvidenceRecord,
    FindingRecord,
    OverrideRecord,
    ReviewRecord,
)
from app.modules.assessments.application.models import (
    BlockingFinding,
    FindingEvidence,
    FindingEvidenceSubmission,
    FindingOverride,
    FindingPerson,
    FindingReason,
    FindingResolution,
    FindingState,
    PolicyRef,
)
from app.modules.assessments.domain.findings import (
    FINDING_SUBJECT_TYPE,
    POLICY_KIND,
    REASON_RULE,
    FindingStatus,
    ResolutionKind,
    finding_reason,
    fingerprint,
    is_blocking,
)
from app.modules.assessments.domain.reviews import ReviewKind, ReviewStatus
from app.modules.gaps.application import public as gaps
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, OverrideBasis, Principal, Resource
from app.modules.intake.application import public as intake
from app.modules.opportunities.application import public as opportunities
from app.platform import evidence, trace
from app.platform.concurrency import parse_if_match
from app.platform.errors import (
    EvidenceUnresolvableError,
    FindingNotOpenError,
    FindingNotOverridableError,
    ForbiddenError,
    NotFoundError,
    RowVersionMismatchError,
    UnprocessableError,
)
from app.platform.ids import new_id
from app.platform.locks import opportunity_lock
from app.platform.logging import get_logger
from app.platform.trace.catalogue import (
    AssessmentsFindingOverridden,
    AssessmentsFindingResolved,
    FindingEvidenceSummary,
)
from app.platform.uow import UnitOfWork

NOT_FOUND_DETAIL = "No Finding with this id."
NOT_OPEN_DETAIL = "This Finding is already resolved or overridden."
SUPERSEDED_DETAIL = "This Finding belongs to an earlier Review."
NOT_OVERRIDABLE_DETAIL = (
    "This Finding is tied to a mandatory security Checklist item and can't be overridden. "
    "Supply Evidence or mark it resolved instead."
)
SOMEONE_ELSE = "someone else"
MAX_ROW_VERSION = 2**31 - 1
_log = get_logger(__name__)


# --- at acceptance --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class Draft:
    """A Finding about to be stored, with the keys its fingerprint adds to its Requirements
    (Red Team: the cited lines' keys; Critic: the cited specialist Finding ids) and whether
    it cites a Security Agent Finding."""

    finding: repo.NewFinding
    keys: tuple[str, ...] = ()
    security: bool = False


async def stamp(
    uow: UnitOfWork,
    *,
    opportunity_id: UUID,
    kind: ReviewKind,
    version: int,
    drafts: Sequence[Draft],
) -> list[repo.NewFinding]:
    """The Findings with their fingerprint, discipline, `policy_ref` and previous override
    set (module docstring). Takes the Opportunity's Findings lock until commit."""
    await opportunity_lock(uow, opportunity_id)
    prints = [
        fingerprint(kind.value, d.finding.category, (r for r, _ in d.finding.requirements), d.keys)
        for d in drafts
    ]
    policies = await gaps.security_policies(
        uow, opportunity_id, {r for d in drafts for r, _ in d.finding.requirements}
    )
    previous = await repo.latest_overrides(
        uow, opportunity_id, kind.value, version, sorted(set(prints))
    )
    stamped: list[repo.NewFinding] = []
    for draft, fp in zip(drafts, prints, strict=True):
        policy = next((policies[r] for r, _ in draft.finding.requirements if r in policies), None)
        stamped.append(
            dataclasses.replace(
                draft.finding,
                fingerprint=fp,
                security_discipline=draft.security,
                policy_ref=None
                if policy is None
                else {
                    "kind": POLICY_KIND,
                    "checklist_id": str(policy.checklist_id),
                    "version": policy.version,
                    "item_id": str(policy.item_id),
                },
                previous_override_id=previous.get(fp),
            )
        )
    return stamped


# --- queries --------------------------------------------------------------------------------


async def get_blocking_findings(uow: UnitOfWork, opportunity_id: UUID) -> list[BlockingFinding]:
    """`assessments.get_blocking_findings`: every `open`, `critical` Finding of the
    Opportunity's current Critic and Red Team Reviews, with its Review kind and version. No
    authorization (Epic 8's `estimates.get_submission_blockers` has checked the caller)."""
    return [
        BlockingFinding(
            finding_id=b.finding_id,
            review_kind=b.review_kind,
            review_version=b.review_version,
            title=b.title,
        )
        for b in await repo.blocking_findings(uow, opportunity_id)
    ]


async def blocking_finding_counts(
    uow: UnitOfWork, opportunity_ids: Sequence[UUID]
) -> dict[UUID, int]:
    """How many Findings `get_blocking_findings` returns for each of these Opportunities, in
    one query (Story 8.6: the Opportunity list's blocker count); one with none counts 0."""
    ids = list(opportunity_ids)
    found = await repo.blocking_counts(uow, ids)
    return {opportunity_id: found.get(opportunity_id, 0) for opportunity_id in ids}


def blocking_count(findings: Sequence[FindingRecord]) -> int:
    """How many of a current Review's Findings block submission."""
    return sum(1 for f in findings if is_blocking(f.status, f.severity))


def _person(user_id: UUID, names: dict[UUID, str]) -> FindingPerson:
    return FindingPerson(id=str(user_id), name=names.get(user_id, SOMEONE_ELSE))


def _override_view(record: OverrideRecord, names: dict[UUID, str]) -> FindingOverride:
    return FindingOverride(
        id=str(record.id),
        reason=record.reason,
        by=_person(record.overridden_by, names),
        at=record.created_at,
        review_version=record.review_version,
        policy_basis=OverrideBasis(record.policy_basis).value,
    )


def _resolver(resolution: dict[str, Any] | None) -> UUID | None:
    if not resolution:
        return None
    try:
        return UUID(str(resolution.get("by")))
    except ValueError:
        return None


def _may_override(actor: Principal, resource: Resource, finding: FindingRecord) -> bool:
    return (
        finding.policy_ref is None
        and identity.finding_override_basis(
            actor, resource, security_discipline=finding.security_discipline
        )
        is not None
    )


@dataclasses.dataclass(frozen=True, slots=True)
class FindingDecisions:
    """A Finding's resolution (when resolved), its override and the earlier override with
    the same fingerprint, as read models; no caller-specific flags."""

    resolution: FindingResolution | None
    override: FindingOverride | None
    previous_override: FindingOverride | None


async def finding_decisions(
    uow: UnitOfWork, opportunity_id: UUID, findings: Sequence[FindingRecord]
) -> dict[UUID, FindingDecisions]:
    """Each Finding's resolution and overrides (who, when, why, and the Evidence supplied).
    No authorization: the caller has checked that the actor may read the Opportunity."""
    ids = [f.id for f in findings]
    overrides = await repo.overrides_for(uow, ids)
    previous = await repo.overrides_by_id(
        uow, [f.previous_override_id for f in findings if f.previous_override_id is not None]
    )
    supplied = await repo.evidence_for(uow, ids)
    labels = await intake.evidence_labels(
        uow, opportunity_id, [(e.kind, e.ref_id, e.ref_version) for e in supplied]
    )
    by_finding: dict[UUID, list[EvidenceRecord]] = {}
    for e in supplied:
        by_finding.setdefault(e.finding_id, []).append(e)
    people = {o.overridden_by for o in (*overrides.values(), *previous.values())}
    people |= {p for f in findings if (p := _resolver(f.resolution)) is not None}
    names = await identity.user_names(uow, people)
    found: dict[UUID, FindingDecisions] = {}
    for f in findings:
        resolution = None
        resolver = _resolver(f.resolution)
        if f.resolution and resolver is not None:
            resolution = FindingResolution(
                kind=ResolutionKind(f.resolution["kind"]),
                reason=str(f.resolution["reason"]),
                by=_person(resolver, names),
                at=datetime.fromisoformat(str(f.resolution["at"])),
                evidence=[
                    FindingEvidence(
                        kind=e.kind,
                        id=str(e.ref_id),
                        version=e.ref_version,
                        label=labels.get((e.kind, e.ref_id, e.ref_version), e.kind),
                    )
                    for e in by_finding.get(f.id, [])
                ],
            )
        override = overrides.get(f.id)
        earlier = None if f.previous_override_id is None else previous.get(f.previous_override_id)
        found[f.id] = FindingDecisions(
            resolution=resolution,
            override=None if override is None else _override_view(override, names),
            previous_override=None if earlier is None else _override_view(earlier, names),
        )
    return found


async def finding_states(
    uow: UnitOfWork,
    actor: Principal,
    resource: Resource,
    opportunity_id: UUID,
    review: ReviewRecord,
    findings: Sequence[FindingRecord],
) -> dict[UUID, FindingState]:
    """Each Finding's status, resolution, overrides and what the caller may do with it."""
    decisions = await finding_decisions(uow, opportunity_id, findings)
    current = review.status == ReviewStatus.CURRENT
    may_resolve = current and identity.can(actor, Action.FINDING_RESOLVE, resource)
    states: dict[UUID, FindingState] = {}
    for f in findings:
        is_open = f.status == FindingStatus.OPEN
        decided = decisions[f.id]
        states[f.id] = FindingState(
            id=str(f.id),
            status=FindingStatus(f.status),
            resolution=decided.resolution,
            override=decided.override,
            previous_override=decided.previous_override,
            policy_ref=None if f.policy_ref is None else PolicyRef.model_validate(f.policy_ref),
            overridable=f.policy_ref is None,
            can_resolve=is_open and may_resolve,
            can_override=is_open and current and _may_override(actor, resource, f),
            row_version=f.row_version,
        )
    return states


# --- commands -------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _Loaded:
    resource: Resource
    finding: FindingRecord
    review: ReviewRecord


async def _load(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, finding_id: UUID
) -> _Loaded:
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    await opportunity_lock(uow, opportunity_id)
    found = await repo.get_finding(uow, finding_id)
    if found is None or found[1].opportunity_id != opportunity_id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    finding, review = found
    return _Loaded(resource=resource, finding=finding, review=review)


async def _stale(uow: UnitOfWork, finding: FindingRecord) -> RowVersionMismatchError:
    name = SOMEONE_ELSE
    changer = _resolver(finding.resolution)
    if changer is None:
        override = (await repo.overrides_for(uow, [finding.id])).get(finding.id)
        changer = None if override is None else override.overridden_by
    if changer is not None:
        name = (await identity.user_names(uow, {changer})).get(changer, name)
    return RowVersionMismatchError(f"Changed by {name} since you opened it.")


async def _checked_version(uow: UnitOfWork, loaded: _Loaded, if_match: str | None) -> int:
    expected = parse_if_match(if_match)
    if expected >= MAX_ROW_VERSION or loaded.finding.row_version != expected:
        raise await _stale(uow, loaded.finding)
    if loaded.review.status != ReviewStatus.CURRENT:
        raise FindingNotOpenError(SUPERSEDED_DETAIL)
    if loaded.finding.status != FindingStatus.OPEN:
        raise FindingNotOpenError(NOT_OPEN_DETAIL)
    return expected


def _reason(raw: str) -> str:
    reason = finding_reason(raw)
    if reason is None:
        raise UnprocessableError(REASON_RULE)
    return reason


def _user(actor: Principal) -> UUID:
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants these actions to users only
        raise ForbiddenError("Only people can resolve or override Findings.")
    return user_id


async def _state(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID, loaded: _Loaded
) -> FindingState:
    found = await repo.get_finding(uow, loaded.finding.id)
    assert found is not None
    states = await finding_states(uow, actor, loaded.resource, opportunity_id, found[1], [found[0]])
    return states[loaded.finding.id]


def _ids(opportunity_id: UUID, loaded: _Loaded, user_id: UUID) -> dict[str, object]:
    return {
        "opportunity_id": str(opportunity_id),
        "finding_id": str(loaded.finding.id),
        "review_kind": loaded.review.kind,
        "review_version": loaded.review.version,
        "actor_id": str(user_id),
    }


async def _resolve(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    loaded: _Loaded,
    *,
    expected: int,
    kind: ResolutionKind,
    reason: str,
    refs: list[tuple[str, UUID, int]],
) -> FindingState:
    user_id = _user(actor)
    resolution = {
        "kind": kind.value,
        "reason": reason,
        "by": str(user_id),
        "at": datetime.now(UTC).isoformat(),
    }
    new_version = await repo.set_status(
        uow,
        loaded.finding.id,
        expected_row_version=expected,
        status=FindingStatus.RESOLVED.value,
        resolution=resolution,
    )
    if new_version is None:  # pragma: no cover - the Findings lock serialises commands
        raise await _stale(uow, loaded.finding)
    await repo.insert_evidence(uow, loaded.finding.id, refs)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=AssessmentsFindingResolved(
            review_kind=ReviewKind(loaded.review.kind).value,
            review_version=loaded.review.version,
            severity=loaded.finding.severity,
            kind=kind.value,
            reason=reason,
            evidence=[FindingEvidenceSummary(kind=k, id=str(i), version=v) for k, i, v in refs],
        ),
        subject_type=FINDING_SUBJECT_TYPE,
        subject_id=loaded.finding.id,
        subject_version=new_version,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "assessments.finding_resolved",
        extra={
            **_ids(opportunity_id, loaded, user_id),
            "kind": kind.value,
            "evidence_count": len(refs),
            "row_version": new_version,
        },
    )
    return await _state(uow, actor, opportunity_id, loaded)


async def supply_evidence(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    finding_id: UUID,
    submission: FindingEvidenceSubmission,
    if_match: str | None,
) -> FindingState:
    """Resolve the open Finding with Evidence and a note (module docstring)."""
    loaded = await _load(uow, actor, opportunity_id, finding_id)
    identity.authorize(actor, Action.FINDING_RESOLVE, loaded.resource)
    _user(actor)
    expected = await _checked_version(uow, loaded, if_match)
    note = _reason(submission.note)
    await evidence.resolve_all(uow, submission.refs)
    foreign = await intake.foreign_evidence(uow, opportunity_id, submission.refs)
    if foreign is not None:
        raise EvidenceUnresolvableError(
            f"Evidence {evidence.describe(foreign)} does not resolve: "
            "it belongs to another Opportunity."
        )
    refs = [(r.kind, r.id, r.version) for r in submission.refs]
    return await _resolve(
        uow,
        actor,
        opportunity_id,
        loaded,
        expected=expected,
        kind=ResolutionKind.EVIDENCE_SUPPLIED,
        reason=note,
        refs=list(dict.fromkeys(refs)),
    )


async def mark_resolved(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    finding_id: UUID,
    body: FindingReason,
    if_match: str | None,
) -> FindingState:
    """Mark the open Finding resolved (addressed) with a reason (module docstring)."""
    loaded = await _load(uow, actor, opportunity_id, finding_id)
    identity.authorize(actor, Action.FINDING_RESOLVE, loaded.resource)
    _user(actor)
    expected = await _checked_version(uow, loaded, if_match)
    reason = _reason(body.reason)
    return await _resolve(
        uow,
        actor,
        opportunity_id,
        loaded,
        expected=expected,
        kind=ResolutionKind.ADDRESSED,
        reason=reason,
        refs=[],
    )


async def override_finding(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    finding_id: UUID,
    body: FindingReason,
    if_match: str | None,
) -> FindingState:
    """Override the open Finding with a reason, under the Opportunity's Findings lock
    (module docstring)."""
    loaded = await _load(uow, actor, opportunity_id, finding_id)
    if loaded.finding.policy_ref is not None:  # before the role check: for everyone
        raise FindingNotOverridableError(NOT_OVERRIDABLE_DETAIL)
    basis = identity.finding_override_basis(
        actor, loaded.resource, security_discipline=loaded.finding.security_discipline
    )
    if basis is None:
        raise ForbiddenError("You are not allowed to perform this action.")
    user_id = _user(actor)
    expected = await _checked_version(uow, loaded, if_match)
    reason = _reason(body.reason)

    override_id = new_id()
    await repo.insert_override(
        uow,
        override_id=override_id,
        finding_id=loaded.finding.id,
        review_kind=loaded.review.kind,
        review_version=loaded.review.version,
        overridden_by=user_id,
        reason=reason,
        policy_basis=basis.value,
    )
    new_version = await repo.set_status(
        uow,
        loaded.finding.id,
        expected_row_version=expected,
        status=FindingStatus.OVERRIDDEN.value,
        resolution=None,
    )
    if new_version is None:  # pragma: no cover - the Findings lock serialises commands
        raise await _stale(uow, loaded.finding)
    previous = loaded.finding.previous_override_id
    await trace.append(
        uow,
        actor=actor.actor,
        payload=AssessmentsFindingOverridden(
            review_kind=ReviewKind(loaded.review.kind).value,
            review_version=loaded.review.version,
            severity=loaded.finding.severity,
            override_id=str(override_id),
            person_id=str(user_id),
            reason=reason,
            policy_basis=basis.value,
            previous_override_id=None if previous is None else str(previous),
        ),
        subject_type=FINDING_SUBJECT_TYPE,
        subject_id=loaded.finding.id,
        subject_version=new_version,
        opportunity_id=opportunity_id,
    )
    _log.info(
        "assessments.finding_overridden",
        extra={
            **_ids(opportunity_id, loaded, user_id),
            "override_id": str(override_id),
            "policy_basis": basis.value,
            "reapplied": previous is not None,
            "row_version": new_version,
        },
    )
    return await _state(uow, actor, opportunity_id, loaded)
