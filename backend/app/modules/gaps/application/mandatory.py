"""Deterministic Gaps from mandatory Checklist items (Story 4.2).

`raise_mandatory_gaps` is the first step of every `gaps.detect_gaps` run, in `_start`'s Unit
of Work (after the detection is confirmed still queued or running, before the Agent Registry
check), so its Gaps are committed even when the agent is disabled, fails, or there are no
Requirements. No model output is read:

1. The Opportunity's products and industry (`opportunities.opportunity_scope`) select the
   applicable Checklists (`knowledge.find_applicable_checklists`; Integration Types come with
   Story 4.1).
2. `rules.mandatory_gaps` plans one Gap per mandatory item that has no Gap yet in any status
   (an answered, converted or dismissed one blocks a new one and is never reopened).
3. Each Gap is inserted with `ON CONFLICT DO NOTHING` on `uq_gaps_gaps_mandatory_item`, so
   reruns and concurrent runs raise it once, with a `drafted`, `from_checklist` question.
   Trace `gaps.gap.raised` (`origin: mandatory_checklist`) and
   `gaps.clarification_question.drafted`, actor `system` / `gaps.detect_gaps`.
4. Every mandatory Gap's `checklist_applies` is set, whatever its status (a settled one may
   be reopened later): true iff its item is a mandatory item of an applicable version.
   Nothing is ever deleted.

Notifies the Opportunity's event stream when anything was raised or flipped. Trace and logs
carry ids and counts only.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.gaps.adapters import repository as repo
from app.modules.gaps.domain import gaps as rules
from app.modules.gaps.domain.gaps import GAP_SUBJECT_TYPE, QUESTION_SUBJECT_TYPE, GapOrigin
from app.modules.knowledge.application import public as knowledge
from app.modules.opportunities.application import public as opportunities
from app.platform import trace
from app.platform.actor import Actor
from app.platform.ids import new_id
from app.platform.logging import get_logger
from app.platform.trace.catalogue import GapsClarificationQuestionDrafted, GapsGapRaised
from app.platform.uow import UnitOfWork

MANDATORY_ACTOR = Actor(type="system", id="gaps.detect_gaps")
_log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MandatoryOutcome:
    raised: int
    """Mandatory Gaps inserted by this run."""
    flipped: int
    """Mandatory Gaps whose `checklist_applies` changed."""


def _inputs(applicable: list[knowledge.ApplicableChecklist]) -> list[rules.ChecklistInput]:
    return [
        rules.ChecklistInput(
            checklist_id=UUID(c.checklist_id),
            version=c.version,
            name=c.name,
            domain=c.domain.value,
            items=tuple(
                rules.ChecklistItemInput(
                    item_id=UUID(i.item_id),
                    text=i.text,
                    why_it_matters=i.why_it_matters,
                    affected_entry_id=None
                    if i.affected_entry_id is None
                    else UUID(i.affected_entry_id),
                    impact=rules.Impact(i.impact.value),
                    mandatory=i.mandatory,
                )
                for i in c.items
            ),
        )
        for c in applicable
    ]


async def raise_mandatory_gaps(
    uow: UnitOfWork, opportunity_id: UUID, detection_id: UUID
) -> MandatoryOutcome:
    """Raise the Opportunity's missing mandatory Gaps and refresh `checklist_applies`, in the
    caller's Unit of Work (which holds the Opportunity's detection lock)."""
    scope = await opportunities.opportunity_scope(uow, opportunity_id)
    applicable = (
        []
        if scope is None
        else await knowledge.find_applicable_checklists(
            uow, products=scope.products, industry=scope.industry, integration_type_ids=[]
        )
    )
    plan = rules.mandatory_gaps(_inputs(applicable), await repo.mandatory_keys(uow, opportunity_id))
    raised = 0
    for gap in plan.new:
        gap_id = new_id()
        question_id = new_id()
        inserted = await repo.insert_mandatory_gap(
            uow,
            gap_id=gap_id,
            opportunity_id=opportunity_id,
            title=gap.title,
            category=gap.category.value,
            trigger=dict(gap.trigger),
            why_it_matters=gap.why_it_matters,
            why_entry_id=gap.why_entry_id,
            impact=gap.impact.value,
            impact_basis=gap.impact_basis,
            detection_id=detection_id,
            question_id=question_id,
            question_text=gap.question_text,
            question_topic=gap.question_topic,
        )
        if not inserted:  # a concurrent run raised it first
            continue
        raised += 1
        await trace.append(
            uow,
            actor=MANDATORY_ACTOR,
            payload=GapsGapRaised(
                detection_id=str(detection_id),
                category=gap.category.value,
                impact=gap.impact.value,
                requirement_ids=[],
                origin=GapOrigin.MANDATORY_CHECKLIST.value,
            ),
            subject_type=GAP_SUBJECT_TYPE,
            subject_id=gap_id,
            opportunity_id=opportunity_id,
        )
        await trace.append(
            uow,
            actor=MANDATORY_ACTOR,
            payload=GapsClarificationQuestionDrafted(gap_id=str(gap_id)),
            subject_type=QUESTION_SUBJECT_TYPE,
            subject_id=question_id,
            opportunity_id=opportunity_id,
        )
    flipped = await repo.set_checklist_applies(uow, opportunity_id, plan.applies)
    if raised or flipped:
        await repo.notify_gaps_changed(uow, opportunity_id)
    _log.info(
        "gaps.mandatory_gaps",
        extra={
            "opportunity_id": str(opportunity_id),
            "detection_id": str(detection_id),
            "checklist_count": len(applicable),
            "raised_count": raised,
            "flipped_count": flipped,
        },
    )
    return MandatoryOutcome(raised=raised, flipped=flipped)
