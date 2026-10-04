"""Assumptions (Story 8.4): the `estimates.propose_assumptions` job,
`estimates.accept_assumption_proposals`, and accepting Assumptions.

**Queueing.** `estimates.accept_draft` stores each new draft Estimate Version with
`proposal_status` `queued` and calls `enqueue_proposals` in its Unit of Work (background
priority, `timeout_s` 900, `max_attempts` 2).

**The handler.**

1. Short Unit of Work: skips the version unless it is still the `draft`, its proposals are
   `queued` or `running`, and it has no Assumptions yet; reads the Opportunity's open Gaps
   (`gaps.open_gap_summaries`, labelled `G<n>`, with their questions) and the version's lines
   (`L<n>`), and marks the proposals `running`. No open Gap: no model call, `succeeded`.
2. No Unit of Work open: `estimating_agent` proposes one Assumption per Gap (prompt
   `v1-assumptions`).
3. `accept_assumption_proposals`, one Unit of Work: validates every proposal (a `G<n>` that
   is still an open Gap, a kind, wording, hours for a Contingency only, a line of this
   version), keeps the first valid one per Gap, stores them **unaccepted**, marks the
   proposals `succeeded` and traces `estimates.assumption.proposed`. If an open Gap has no
   valid proposal, nothing is written and `ModelOutputInvalidError` is raised, so the job
   runs once more; on that final attempt what is valid is stored and the rest show as
   Unconverted Gaps.

A gateway error on the final attempt marks the proposals `failed`.

**Accepting** (`estimates.assumption.accept`: the owner and collaborators except sales
representatives, always as themselves): `accept_assumption` (with `If-Match`) and
`accept_all_assumptions` (every unaccepted Assumption of the current draft). Each takes the
Opportunity's draft lock and then its Assumption lock (always in that order; the proposal job
takes the Assumption lock only), records who accepted and when, and calls
`gaps.mark_converted` in the same Unit of Work: a Gap that is no longer `open` raises 409
`gap_not_open` and nothing commits. Accepting an accepted Assumption changes nothing (200).

Logs, trace and `last_error` carry ids, kinds, hours and counts only, never wording or Gap
text.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.agents.contract import AgentResult
from app.agents.estimating_agent.agent import (
    AGENT_ID,
    AssumptionsTask,
    EstimatingAgent,
    GapBlock,
    LineBlock,
)
from app.agents.estimating_agent.agent import config as agent_config
from app.agents.estimating_agent.schema import AssumptionsOutput
from app.modules.estimates.adapters import repository as repo
from app.modules.estimates.adapters.repository import AssumptionRecord, NewAssumption
from app.modules.estimates.domain.assumptions import (
    ASSUMPTION_SUBJECT_TYPE,
    ORIGIN_GAP,
    PROPOSING,
    AssumptionKind,
    ProposalCandidate,
    ProposalStatus,
    ProposalValidation,
    validate_proposals,
)
from app.modules.estimates.domain.estimates import VERSION_SUBJECT_TYPE, VersionStatus
from app.modules.gaps.application import public as gaps
from app.modules.identity.application import public as identity
from app.modules.identity.application.public import Action, Principal
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.actor import Actor
from app.platform.concurrency import parse_if_match
from app.platform.config import Settings, get_settings
from app.platform.errors import ForbiddenError, NotFoundError, RowVersionMismatchError
from app.platform.ids import new_id
from app.platform.jobs import JobContext, JobPayload, JobType, enqueue, register
from app.platform.logging import get_logger
from app.platform.model_gateway import provider
from app.platform.model_gateway.port import ModelOutputInvalidError
from app.platform.trace.catalogue import (
    EstimatesAssumptionAccepted,
    EstimatesAssumptionProposed,
)
from app.platform.uow import UnitOfWork, unit_of_work

PROPOSE_ASSUMPTIONS = "estimates.propose_assumptions"
NOT_FOUND_DETAIL = "No Assumption with this id in the current draft Estimate."
MAX_ROW_VERSION = 2**31 - 1
_PROPOSING = tuple(sorted(s.value for s in PROPOSING))
_RUNNING = (ProposalStatus.RUNNING.value,)
_log = get_logger(__name__)


class ProposeAssumptions(JobPayload):
    version_id: UUID


def proposal_settings() -> Settings:
    """Settings for the handler (the chat profile). Tests replace this."""
    return get_settings()


async def enqueue_proposals(uow: UnitOfWork, *, version_id: UUID, opportunity_id: UUID) -> None:
    """Queue the Assumption proposals of a new draft version (stored with `proposal_status`
    `queued`) in the caller's Unit of Work."""
    await enqueue(uow, ProposeAssumptions(version_id=version_id), opportunity_id=opportunity_id)
    _log.info(
        "estimates.proposals_queued",
        extra={"opportunity_id": str(opportunity_id), "version_id": str(version_id)},
    )


# --- accepting the proposals ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposalGap:
    """An open Gap the proposals read, with its prompt label `G<n>`."""

    label: str
    gap_id: UUID
    category: str
    impact: str
    title: str = field(repr=False)
    why_it_matters: str = field(repr=False)
    question: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ProposalLine:
    """A line of the version, with its prompt label `L<n>`."""

    label: str
    line_id: UUID
    section: str
    effort_hours: str
    title: str = field(repr=False)


def proposal(result: AgentResult) -> AssumptionsOutput:
    """The agent's proposals, re-validated (AD-4). Raises `ModelOutputInvalidError` when the
    extension is missing or malformed."""
    raw = result.extensions.get(AGENT_ID)
    try:
        return AssumptionsOutput.model_validate(raw)
    except ValueError:
        raise ModelOutputInvalidError("The estimating_agent extension is not valid.") from None


def candidates(output: AssumptionsOutput) -> list[ProposalCandidate]:
    return [
        ProposalCandidate(gap=a.gap, kind=a.kind, wording=a.wording, hours=a.hours, line=a.line)
        for a in output.assumptions
    ]


async def accept_assumption_proposals(
    uow: UnitOfWork,
    *,
    version_id: UUID,
    result: AgentResult,
    gaps_read: Sequence[ProposalGap],
    lines_read: Sequence[ProposalLine],
    actor: Actor,
    final: bool,
) -> ProposalValidation[UUID, UUID] | None:
    """`estimates.accept_assumption_proposals`: validate the agent's proposals and store them
    as unaccepted Assumptions of the version; mark its proposals `succeeded` and trace them.
    Returns None (and writes nothing) unless the version is still the `draft`, its proposals
    `running`, and it has no Assumptions yet.

    Unless `final`, an open Gap left without a valid proposal writes nothing and raises
    `ModelOutputInvalidError`, so the job runs again; when `final`, what is valid is stored."""
    version = await repo.get_version(uow, version_id)
    if version is None:
        return None
    await repo.lock_assumptions(uow, version.opportunity_id)
    version = await repo.get_version(uow, version_id, for_update=True)
    if (
        version is None
        or version.status != VersionStatus.DRAFT
        or version.proposal_status != ProposalStatus.RUNNING
        or await repo.has_assumptions(uow, version_id)
    ):
        return None
    ids = {"version_id": str(version_id), "opportunity_id": str(version.opportunity_id)}
    proposed = candidates(proposal(result))
    still_open = {g.id: g for g in await gaps.open_gap_summaries(uow, version.opportunity_id)}
    gap_labels = {g.label: g.gap_id for g in gaps_read if g.gap_id in still_open}
    line_labels = {line.label: line.line_id for line in lines_read}
    validation = validate_proposals(proposed, gap_labels, line_labels)
    if validation.missing and not final:
        _log.info(
            "estimates.proposals_incomplete",
            extra={
                **ids,
                "dropped_count": validation.dropped,
                "duplicate_count": validation.duplicates,
                "missing_count": len(validation.missing),
            },
        )
        raise ModelOutputInvalidError("An open Gap has no valid Assumption proposal.")

    await repo.insert_assumptions(
        uow,
        version_id,
        [
            NewAssumption(
                assumption_id=new_id(),
                position=position,
                kind=p.kind.value,
                wording=p.wording,
                amount_hours=p.hours,
                line_id=p.line,
                origin_ref={
                    "kind": ORIGIN_GAP,
                    "id": str(p.gap),
                    "row_version": still_open[p.gap].row_version,
                },
            )
            for position, p in enumerate(validation.proposals, start=1)
        ],
    )
    await repo.set_proposal_status(
        uow, version_id, from_statuses=_RUNNING, status=ProposalStatus.SUCCEEDED.value
    )
    kinds = [p.kind for p in validation.proposals]
    proposed_event = EstimatesAssumptionProposed(
        count=len(kinds),
        condition_count=kinds.count(AssumptionKind.CONDITION),
        contingency_count=kinds.count(AssumptionKind.CONTINGENCY),
        dropped_count=validation.dropped,
        duplicate_count=validation.duplicates,
        unconverted_count=len(validation.missing),
    )
    await trace.append(
        uow,
        actor=actor,
        payload=proposed_event,
        subject_type=VERSION_SUBJECT_TYPE,
        subject_id=version_id,
        opportunity_id=version.opportunity_id,
    )
    _log.info("estimates.proposals_accepted", extra={**ids, **proposed_event.model_dump()})
    return validation


# --- the handler ----------------------------------------------------------------------------


async def _mark_failed(ctx: JobContext, version_id: UUID) -> bool:
    async with unit_of_work(ctx.engine) as uow:
        return await repo.set_proposal_status(
            uow, version_id, from_statuses=_PROPOSING, status=ProposalStatus.FAILED.value
        )


async def _mark_failed_shielded(ctx: JobContext, version_id: UUID, ids: dict[str, str]) -> None:
    write = asyncio.ensure_future(_mark_failed(ctx, version_id))
    try:
        recorded = await asyncio.shield(write)
    except asyncio.CancelledError:  # cancelled again: still let the write land
        await asyncio.wait({write})
        recorded = not write.cancelled() and write.exception() is None and write.result()
    except Exception as exc:
        _log.warning(
            "estimates.proposals_fail_unrecorded", extra={**ids, "exc_type": type(exc).__name__}
        )
        return
    _log.info("estimates.proposals_failed", extra={**ids, "recorded": recorded})


async def propose_assumptions(ctx: JobContext, payload: ProposeAssumptions) -> None:
    """The handler. On the job's final attempt any error first marks the proposals `failed`
    (best effort), so none is left `running` once its job is dead; then it re-raises."""
    ids = {"version_id": str(payload.version_id), "job_id": str(ctx.job_id)}
    try:
        await _propose(ctx, payload)
    except asyncio.CancelledError:
        if ctx.attempt >= ctx.max_attempts:
            await _mark_failed_shielded(ctx, payload.version_id, ids)
        raise
    except Exception as exc:
        if ctx.attempt >= ctx.max_attempts:
            try:
                recorded = await _mark_failed(ctx, payload.version_id)
            except Exception as mark_exc:  # e.g. the database is down: the job still dies
                _log.warning(
                    "estimates.proposals_fail_unrecorded",
                    extra={**ids, "exc_type": type(mark_exc).__name__},
                )
            else:
                _log.info(
                    "estimates.proposals_failed",
                    extra={**ids, "exc_type": type(exc).__name__, "recorded": recorded},
                )
        else:
            _log.warning(
                "estimates.proposals_retrying", extra={**ids, "exc_type": type(exc).__name__}
            )
        raise


@dataclass(frozen=True, slots=True)
class _Started:
    opportunity_id: UUID
    gaps: list[ProposalGap] = field(repr=False)
    lines: list[ProposalLine] = field(repr=False)


async def _start(ctx: JobContext, version_id: UUID) -> _Started | None:
    """Read the open Gaps and the version's lines and mark the proposals `running`; None if
    there is nothing to propose for (a superseded version, proposals already stored or
    finished, a duplicate or late run)."""
    async with unit_of_work(ctx.engine) as uow:
        version = await repo.get_version(uow, version_id)
        if version is None:
            return None
        await repo.lock_assumptions(uow, version.opportunity_id)
        version = await repo.get_version(uow, version_id, for_update=True)
        if (
            version is None
            or version.status != VersionStatus.DRAFT
            or version.proposal_status not in _PROPOSING
        ):
            return None
        if await repo.has_assumptions(uow, version_id):
            await repo.set_proposal_status(
                uow, version_id, from_statuses=_PROPOSING, status=ProposalStatus.SUCCEEDED.value
            )
            return None
        open_gaps = await gaps.open_gap_summaries(uow, version.opportunity_id)
        lines = await repo.lines_of(uow, version_id)
        await repo.set_proposal_status(
            uow, version_id, from_statuses=_PROPOSING, status=ProposalStatus.RUNNING.value
        )
        return _Started(
            opportunity_id=version.opportunity_id,
            gaps=[
                ProposalGap(
                    label=f"G{n}",
                    gap_id=g.id,
                    category=g.category,
                    impact=g.impact,
                    title=g.title,
                    why_it_matters=g.why_it_matters,
                    question=g.question,
                )
                for n, g in enumerate(open_gaps, start=1)
            ],
            lines=[
                ProposalLine(
                    label=f"L{n}",
                    line_id=line.id,
                    section=line.section,
                    effort_hours=f"{line.effort_hours:.1f}",
                    title=line.title,
                )
                for n, line in enumerate(lines, start=1)
            ],
        )


async def _propose(ctx: JobContext, payload: ProposeAssumptions) -> None:
    settings = proposal_settings()
    version_id = payload.version_id
    ids: dict[str, object] = {"version_id": str(version_id)}
    started = await _start(ctx, version_id)
    if started is None:
        _log.info("estimates.proposals_skipped", extra=ids)
        return
    ids["opportunity_id"] = str(started.opportunity_id)

    if not started.gaps:  # nothing to convert: no model call, no Assumptions
        async with unit_of_work(ctx.engine) as uow:
            await repo.set_proposal_status(
                uow, version_id, from_statuses=_RUNNING, status=ProposalStatus.SUCCEEDED.value
            )
        _log.info("estimates.proposals_empty", extra=ids)
        return

    agent = EstimatingAgent(provider.current(), profile=settings.model_profile_chat)
    result = await agent.propose_assumptions(
        AssumptionsTask(
            opportunity_id=started.opportunity_id,
            run_id=version_id,
            gaps=[
                GapBlock(
                    label=g.label,
                    category=g.category,
                    impact=g.impact,
                    title=g.title,
                    why_it_matters=g.why_it_matters,
                    question=g.question,
                )
                for g in started.gaps
            ],
            lines=[
                LineBlock(
                    label=line.label,
                    section=line.section,
                    effort_hours=line.effort_hours,
                    title=line.title,
                )
                for line in started.lines
            ],
        )
    )
    actor = Actor(type="agent", id=agent_config(settings.model_profile_chat).actor_id)
    async with unit_of_work(ctx.engine) as uow:
        accepted = await accept_assumption_proposals(
            uow,
            version_id=version_id,
            result=result,
            gaps_read=started.gaps,
            lines_read=started.lines,
            actor=actor,
            final=ctx.attempt >= ctx.max_attempts,
        )
    if accepted is None:
        _log.info("estimates.proposals_skipped", extra=ids)


PROPOSE_ASSUMPTIONS_JOB = register(
    JobType(
        name=PROPOSE_ASSUMPTIONS,
        payload=ProposeAssumptions,
        handler=propose_assumptions,
        priority="background",
        timeout_s=900.0,
        max_attempts=2,
        backoff_base_s=15.0,
        backoff_cap_s=120.0,
    )
)


# --- accepting Assumptions ------------------------------------------------------------------


def _stale() -> RowVersionMismatchError:
    return RowVersionMismatchError(
        "The Assumption was changed by someone else since you opened it. Reload and try again."
    )


async def _authorized(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> UUID:
    """Authorize `estimates.assumption.accept` on the Opportunity; the acting user's id."""
    resource = await opportunities.readable_resource(uow, actor, opportunity_id)
    identity.authorize(actor, Action.ASSUMPTION_ACCEPT, resource)
    user_id = actor.user_id
    if user_id is None:  # pragma: no cover - the policy grants this action to users only
        raise ForbiddenError("Only people can accept Assumptions.")
    return user_id


async def _accepted(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    record: AssumptionRecord,
    user_id: UUID,
) -> None:
    """Convert the accepted Assumption's Gap (409 `gap_not_open` unless it is open) and trace
    the acceptance."""
    gap_id = UUID(str(record.origin_ref["id"]))
    await gaps.mark_converted(uow, gap_id, actor=actor.actor, assumption_kind=record.kind)
    await trace.append(
        uow,
        actor=actor.actor,
        payload=EstimatesAssumptionAccepted(
            version_id=str(record.version_id),
            kind=AssumptionKind(record.kind).value,
            amount_hours=None if record.amount_hours is None else float(record.amount_hours),
            line_id=None if record.line_id is None else str(record.line_id),
            gap_id=str(gap_id),
            accepted_by=str(user_id),
        ),
        subject_type=ASSUMPTION_SUBJECT_TYPE,
        subject_id=record.id,
        opportunity_id=opportunity_id,
        subject_version=record.row_version,
    )


async def accept_assumption(
    uow: UnitOfWork,
    actor: Principal,
    opportunity_id: UUID,
    assumption_id: UUID,
    if_match: str | None,
) -> AssumptionRecord:
    """Accept one Assumption of the current draft as the caller. `if_match` is the raw
    `If-Match` header (428/412). Returns the Assumption as stored."""
    user_id = await _authorized(uow, actor, opportunity_id)
    # The draft lock first (as `accept_draft` takes it), so no draft can supersede the
    # version while its Assumptions are accepted; then the Assumption lock.
    await repo.lock_opportunity(uow, opportunity_id)
    await repo.lock_assumptions(uow, opportunity_id)
    version = await repo.current_version(uow, opportunity_id)
    record = await repo.get_assumption(uow, assumption_id)
    if version is None or record is None or record.version_id != version.id:
        raise NotFoundError(NOT_FOUND_DETAIL)
    expected = parse_if_match(if_match)
    if record.accepted_at is not None:
        return record  # idempotent: already accepted, nothing changes
    if expected >= MAX_ROW_VERSION or record.row_version != expected:
        raise _stale()
    accepted = await repo.accept_assumption(
        uow, assumption_id, expected_row_version=expected, user_id=user_id
    )
    if accepted is None:  # pragma: no cover - the lock serialises accepts
        raise _stale()
    await _accepted(uow, actor, opportunity_id, accepted, user_id)
    _log.info(
        "estimates.assumption_accepted",
        extra={
            "opportunity_id": str(opportunity_id),
            "assumption_id": str(assumption_id),
            "actor_id": str(user_id),
            "kind": accepted.kind,
        },
    )
    return accepted


async def accept_all_assumptions(uow: UnitOfWork, actor: Principal, opportunity_id: UUID) -> int:
    """Accept every unaccepted Assumption of the current draft as the caller; how many.
    All or nothing: one whose Gap is no longer open fails the whole call (409)."""
    user_id = await _authorized(uow, actor, opportunity_id)
    # The draft lock first (as `accept_draft` takes it), so no draft can supersede the
    # version while its Assumptions are accepted; then the Assumption lock.
    await repo.lock_opportunity(uow, opportunity_id)
    await repo.lock_assumptions(uow, opportunity_id)
    version = await repo.current_version(uow, opportunity_id)
    if version is None:
        return 0
    count = 0
    for record in await repo.assumptions_of(uow, version.id, unaccepted_only=True):
        accepted = await repo.accept_assumption(
            uow, record.id, expected_row_version=record.row_version, user_id=user_id
        )
        if accepted is None:  # pragma: no cover - the lock serialises accepts
            continue
        await _accepted(uow, actor, opportunity_id, accepted, user_id)
        count += 1
    _log.info(
        "estimates.assumptions_accepted",
        extra={
            "opportunity_id": str(opportunity_id),
            "version_id": str(version.id),
            "actor_id": str(user_id),
            "count": count,
        },
    )
    return count
