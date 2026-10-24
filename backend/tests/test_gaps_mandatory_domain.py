"""Mandatory Gap rules (Story 4.2), without a database: the planner over the spec's I/O
matrix, the category map, cutting, and the dismissal rule."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.modules.gaps.domain import gaps as rules
from app.modules.gaps.domain.gaps import (
    IMPACT_BASIS_MAX,
    QUESTION_MAX,
    TITLE_MAX,
    TOPIC_MAX,
    WHY_MAX,
    ChecklistInput,
    ChecklistItemInput,
    DismissReasonKind,
    GapCategory,
    GapMandatoryError,
    GapNotOpenTransitionError,
    GapState,
    GapStatus,
    Impact,
    mandatory_gaps,
)


def item(
    *,
    mandatory: bool = True,
    text: str = "Is SSO required?",
    item_id: UUID | None = None,
    impact: Impact = Impact.HIGH,
    affected: UUID | None = None,
    why: str = "SSO changes the identity design.",
) -> ChecklistItemInput:
    return ChecklistItemInput(
        item_id=item_id or uuid4(),
        text=text,
        why_it_matters=why,
        affected_entry_id=affected,
        impact=impact,
        mandatory=mandatory,
    )


def checklist(
    *items: ChecklistItemInput,
    version: int = 1,
    name: str = "Security baseline",
    domain: str = "security",
    checklist_id: UUID | None = None,
) -> ChecklistInput:
    return ChecklistInput(
        checklist_id=checklist_id or uuid4(),
        version=version,
        name=name,
        domain=domain,
        items=tuple(items),
    )


def test_first_run_raises_one_gap_per_mandatory_item() -> None:
    a = checklist(item(), item(mandatory=False), item(text="Pen test?"))
    b = checklist(item(text="Data residency?"), item(mandatory=False), domain="commercial")

    plan = mandatory_gaps([a, b], [])

    assert [g.title for g in plan.new] == ["Is SSO required?", "Pen test?", "Data residency?"]
    assert len(plan.applies) == 3
    assert {g.key for g in plan.new} == plan.applies


def test_the_new_gap_carries_the_item_and_checklist() -> None:
    entry = uuid4()
    one = item(impact=Impact.MEDIUM, affected=entry)
    source = checklist(one, version=3, name="Security baseline")

    (gap,) = mandatory_gaps([source], []).new

    assert gap.key == (source.checklist_id, one.item_id)
    assert gap.title == "Is SSO required?"
    assert gap.why_it_matters == "SSO changes the identity design."
    assert gap.why_entry_id == entry
    assert gap.impact == Impact.MEDIUM
    assert gap.category == GapCategory.SECURITY_AND_COMPLIANCE
    assert (
        gap.impact_basis == 'Default impact of mandatory item in Checklist "Security baseline" v3.'
    )
    assert gap.trigger == {
        "kind": "checklist_item",
        "checklist_id": str(source.checklist_id),
        "version": 3,
        "item_id": str(one.item_id),
        "checklist_name": "Security baseline",
    }
    assert (gap.question_text, gap.question_topic) == ("Is SSO required?", "Security baseline")


def test_rerun_raises_nothing_new() -> None:
    source = checklist(item(), item())
    first = mandatory_gaps([source], [])

    again = mandatory_gaps([source], {g.key for g in first.new})

    assert again.new == ()
    assert again.applies == first.applies


def test_a_settled_gap_blocks_a_new_one() -> None:
    """Existing keys come from mandatory Gaps in any status (answered, converted,
    dismissed): none is raised again."""
    one = item()
    source = checklist(one)

    plan = mandatory_gaps([source], [(source.checklist_id, one.item_id)])

    assert plan.new == ()
    assert plan.applies == {(source.checklist_id, one.item_id)}


def test_a_new_version_raises_only_the_added_mandatory_item() -> None:
    kept = item()
    v1 = checklist(kept)
    existing = {g.key for g in mandatory_gaps([v1], []).new}
    added = item(text="Backups?")
    v2 = checklist(kept, added, version=2, checklist_id=v1.checklist_id)

    plan = mandatory_gaps([v2], existing)

    assert [g.title for g in plan.new] == ["Backups?"]
    assert plan.new[0].trigger["version"] == 2
    assert plan.applies == {(v1.checklist_id, kept.item_id), (v1.checklist_id, added.item_id)}


def test_an_item_removed_or_made_optional_no_longer_applies() -> None:
    removed = item()
    optional = item()
    v1 = checklist(removed, optional)
    existing = {g.key for g in mandatory_gaps([v1], []).new}
    v2 = checklist(
        item(mandatory=False, item_id=optional.item_id), version=2, checklist_id=v1.checklist_id
    )

    plan = mandatory_gaps([v2], existing)

    assert plan.new == ()
    assert plan.applies == frozenset()


def test_no_applicable_checklist_applies_nothing() -> None:
    plan = mandatory_gaps([], [(uuid4(), uuid4())])
    assert (plan.new, plan.applies) == ((), frozenset())


@pytest.mark.parametrize(
    ("domain", "category"),
    [
        ("security", GapCategory.SECURITY_AND_COMPLIANCE),
        ("commercial", GapCategory.COMMERCIAL),
        ("delivery", GapCategory.SCOPE_AND_OWNERSHIP),
        ("engineering", GapCategory.INTEGRATION_DETAILS),
        ("general", GapCategory.OTHER),
        ("unheard_of", GapCategory.OTHER),
    ],
)
def test_category_by_checklist_domain(domain: str, category: GapCategory) -> None:
    (gap,) = mandatory_gaps([checklist(item(), domain=domain)], []).new
    assert gap.category == category


def test_long_texts_are_cut_with_an_ellipsis() -> None:
    long_text = "word " * 400
    source = checklist(item(text=long_text, why="why " * 400), name="N" * 300)

    (gap,) = mandatory_gaps([source], []).new

    assert len(gap.title) == TITLE_MAX and gap.title.endswith("…")
    assert len(gap.why_it_matters) <= WHY_MAX and gap.why_it_matters.endswith("…")
    assert len(gap.question_text) <= QUESTION_MAX and gap.question_text.endswith("…")
    assert len(gap.question_topic) == TOPIC_MAX and gap.question_topic.endswith("…")
    assert len(gap.impact_basis) <= IMPACT_BASIS_MAX
    assert rules.cut("  short  ", 10) == "short"


def _open() -> GapState:
    return GapState(status=GapStatus.OPEN, impact=Impact.HIGH)


def _dismiss(state: GapState, *, mandatory_applies: bool) -> GapState:
    return rules.dismiss_gap(
        state,
        kind=DismissReasonKind.NOT_RELEVANT,
        note=None,
        user_id=uuid4(),
        at=datetime.now(UTC),
        mandatory_applies=mandatory_applies,
    )


def test_a_mandatory_gap_that_applies_cannot_be_dismissed() -> None:
    with pytest.raises(GapMandatoryError):
        _dismiss(_open(), mandatory_applies=True)


def test_a_mandatory_gap_that_no_longer_applies_can_be_dismissed() -> None:
    assert _dismiss(_open(), mandatory_applies=False).status == GapStatus.DISMISSED


def test_a_closed_gap_reports_not_open_first() -> None:
    answered = GapState(status=GapStatus.CONVERTED, impact=Impact.HIGH)
    with pytest.raises(GapNotOpenTransitionError):
        _dismiss(answered, mandatory_applies=True)
