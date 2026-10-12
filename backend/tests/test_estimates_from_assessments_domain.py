"""The line rule of the Estimate built from the specialist Assessments (Story 8.3). Pure: no
database, no model."""

from decimal import Decimal
from uuid import UUID, uuid4

from hypothesis import given
from hypothesis import strategies as st

from app.modules.estimates.domain.estimates import (
    BASIS_MAX,
    ROLES,
    TITLE_MAX,
    EstimateRole,
    Section,
    valid_mix,
)
from app.modules.estimates.domain.from_assessments import (
    ActiveRequirement,
    AgentSizing,
    SizingRow,
    build_lines,
    cut,
    role_mix,
)

ENG, PM, SEC = EstimateRole.ENGINEER, EstimateRole.PROJECT_MANAGER, EstimateRole.QA


def requirement(number: int, classification: str, text: str | None = None) -> ActiveRequirement:
    return ActiveRequirement(
        id=uuid4(),
        version=2,
        number=number,
        classification=classification,
        text=text or f"Requirement {number}.",
    )


def sizing(agent: str, *rows: tuple[ActiveRequirement, float, str]) -> AgentSizing:
    return AgentSizing(
        agent=agent,
        assessment_id=uuid4(),
        assessment_version=1,
        rows=tuple(
            SizingRow(
                requirement_id=r.id,
                requirement_version=1,
                hours=Decimal(str(hours)),
                basis=basis,
            )
            for r, hours, basis in rows
        ),
    )


R1 = requirement(1, "integration", "Connect to SAP.")
R2 = requirement(2, "functional", "Peak 900 orders/hour.")
R3 = requirement(3, "non_functional", "Runs 24/7.")


def test_one_line_per_sized_requirement_in_section_then_requirement_order() -> None:
    built = build_lines(
        [R1, R2, R3],
        [
            sizing("engineering_agent", (R1, 20, "Two interfaces."), (R2, 8, "One screen.")),
            sizing("pm_agent", (R1, 10, "Vendor meetings.")),
            sizing("security_agent", (R1, 4, "Credential review.")),
        ],
    )

    assert built.uncovered == 1  # R3: nobody sized it
    functional, integration = built.lines
    assert (functional.section, functional.title, functional.effort_hours) == (
        Section.FUNCTIONAL,
        "Peak 900 orders/hour.",
        Decimal("8"),
    )
    assert functional.role_mix == {ENG: 100, PM: 0, SEC: 0}
    assert functional.covers == ((R2.id, 2),)  # the Requirement at its current version
    assert functional.basis == "Engineering: One screen."
    assert (integration.section, integration.effort_hours) == (Section.INTEGRATION, Decimal(34))
    assert integration.role_mix == {ENG: 71, PM: 29, SEC: 0}  # 24 h engineer, 10 h PM
    assert integration.covers == ((R1.id, 2),)
    assert integration.basis == (
        "Engineering: Two interfaces. · PM: Vendor meetings. · Security: Credential review."
    )


def test_bases_follow_agent_order_whatever_order_the_sizings_come_in() -> None:
    (line,) = build_lines(
        [R1],
        [
            sizing("security_agent", (R1, 2, "S.")),
            sizing("pm_agent", (R1, 2, "P.")),
            sizing("engineering_agent", (R1, 2, "E.")),
        ],
    ).lines

    assert line.basis == "Engineering: E. · PM: P. · Security: S."


def test_security_hours_count_as_engineer_hours() -> None:
    (line,) = build_lines(
        [R1], [sizing("security_agent", (R1, 6, "S.")), sizing("pm_agent", (R1, 2, "P."))]
    ).lines

    assert (line.effort_hours, line.role_mix) == (Decimal(8), {ENG: 75, PM: 25, SEC: 0})


def test_nothing_sized_means_no_lines() -> None:
    other = uuid4()
    built = build_lines(
        [R1, R2],
        [
            sizing("engineering_agent"),
            AgentSizing(
                agent="pm_agent",
                assessment_id=uuid4(),
                assessment_version=1,
                rows=(SizingRow(other, 1, Decimal(5), "Not active."),),
            ),
        ],
    )

    assert (built.lines, built.uncovered) == ((), 2)


def test_long_text_is_cut_at_a_word_with_an_ellipsis() -> None:
    long = requirement(1, "data", "word " * 60)
    basis = "because " * 100
    (line,) = build_lines(
        [long], [sizing("engineering_agent", (long, 3, basis)), sizing("pm_agent", (long, 1, "x"))]
    ).lines

    assert len(line.title) <= TITLE_MAX
    assert line.title.endswith("word…")
    assert len(line.basis) <= BASIS_MAX
    assert line.basis.startswith("Engineering: because because")
    assert line.basis.endswith("because…")


def test_cut_keeps_short_text_and_flattens_whitespace() -> None:
    assert cut("  Connect\n to   SAP. ", 160) == "Connect to SAP."
    assert cut("a" * 200, 10) == "a" * 9 + "…"  # no word boundary: cut mid-word


def test_role_mix_ties_go_to_the_earlier_role() -> None:
    assert role_mix({ENG: Decimal(1), PM: Decimal(1)}) == {ENG: 50, PM: 50, SEC: 0}
    assert role_mix({ENG: Decimal(1), PM: Decimal(2)}) == {ENG: 33, PM: 67, SEC: 0}
    assert role_mix({ENG: Decimal(0), PM: Decimal(0)}) == {ENG: 100, PM: 0, SEC: 0}


@given(
    engineer=st.decimals(min_value=0, max_value=2000, places=1),
    manager=st.decimals(min_value=0, max_value=2000, places=1),
)
def test_role_mix_is_always_a_valid_mix(engineer: Decimal, manager: Decimal) -> None:
    mix = role_mix({ENG: engineer, PM: manager})

    assert valid_mix({role.value: share for role, share in mix.items()}) is not None
    assert mix[SEC] == 0
    total = engineer + manager
    if total > 0:
        for role, hours in ((ENG, engineer), (PM, manager)):
            assert abs(Decimal(mix[role]) - hours * 100 / total) < 1


def test_every_line_passes_the_template_rules() -> None:
    requirements = [requirement(n, s.value) for n, s in enumerate(Section, start=1)]
    built = build_lines(
        requirements,
        [sizing("engineering_agent", *((r, 1.5, "B.") for r in requirements))],
    )

    assert [line.section for line in built.lines] == list(Section)
    for line in built.lines:
        assert set(line.role_mix) == set(ROLES)
        assert sum(line.role_mix.values()) == 100
        assert isinstance(line.covers[0][0], UUID)
