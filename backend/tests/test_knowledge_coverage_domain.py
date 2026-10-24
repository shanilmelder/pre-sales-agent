"""Story 3.5: the coverage status rule, at every boundary. Pure, no database."""

import pytest

from app.modules.knowledge.domain.coverage import CoverageStatus, coverage_status


@pytest.mark.parametrize(
    ("sources", "stale", "checklists", "expected"),
    [
        # Neither kind.
        (0, 0, 0, CoverageStatus.MISSING),
        # Exactly one kind.
        (1, 0, 0, CoverageStatus.PARTIAL),
        (3, 0, 0, CoverageStatus.PARTIAL),
        (1, 1, 0, CoverageStatus.PARTIAL),
        (0, 0, 1, CoverageStatus.PARTIAL),
        (0, 0, 4, CoverageStatus.PARTIAL),
        # Both kinds, at least one fresh Source.
        (1, 0, 1, CoverageStatus.READY),
        (2, 1, 1, CoverageStatus.READY),
        (5, 4, 3, CoverageStatus.READY),
        # Both kinds, but every Source is stale.
        (1, 1, 1, CoverageStatus.PARTIAL),
        (2, 2, 1, CoverageStatus.PARTIAL),
        (2, 2, 5, CoverageStatus.PARTIAL),
    ],
)
def test_status(sources: int, stale: int, checklists: int, expected: CoverageStatus) -> None:
    assert coverage_status(sources, stale, checklists) is expected


@pytest.mark.parametrize(
    ("sources", "stale", "checklists"),
    [(-1, 0, 0), (0, -1, 0), (0, 0, -1), (1, 2, 0), (0, 1, 1)],
)
def test_impossible_counts_are_rejected(sources: int, stale: int, checklists: int) -> None:
    with pytest.raises(ValueError):
        coverage_status(sources, stale, checklists)


def test_values_are_the_api_words() -> None:
    assert [s.value for s in CoverageStatus] == ["ready", "partial", "missing"]
