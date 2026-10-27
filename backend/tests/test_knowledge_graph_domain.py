"""Knowledge Graph rules (Story 3.6), pure: Source node status, the pair and node scores,
status aggregation and days until stale, with their boundaries."""

from datetime import date, timedelta

import pytest

from app.modules.knowledge.domain.coverage import CoverageStatus
from app.modules.knowledge.domain.embedding import EmbedStatus
from app.modules.knowledge.domain.graph import (
    NodeStatus,
    aggregate_status,
    node_score,
    pair_score,
    source_node_status,
    source_score,
    stale_in_days,
)
from app.modules.knowledge.domain.sources import is_stale
from app.platform.parsing.rules import ParseStatus

P = ParseStatus
E = EmbedStatus
R = CoverageStatus

# --- source_node_status ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("parse", "embed", "stale", "expected"),
    [
        (P.QUEUED, None, False, NodeStatus.EMBEDDING),
        (P.PARSING, None, False, NodeStatus.EMBEDDING),
        (P.PARSED, None, False, NodeStatus.EMBEDDING),
        (P.PARSED, E.QUEUED, False, NodeStatus.EMBEDDING),
        (P.PARSED, E.EMBEDDING, True, NodeStatus.EMBEDDING),
        (P.FAILED, None, False, NodeStatus.EMBEDDING_FAILED),
        (P.PARSED, E.FAILED, False, NodeStatus.EMBEDDING_FAILED),
        (P.FAILED, None, True, NodeStatus.EMBEDDING_FAILED),
        (P.PARSED, E.READY, False, NodeStatus.READY),
        (P.PARSED, E.READY, True, NodeStatus.STALE),
    ],
)
def test_source_node_status(
    parse: ParseStatus, embed: EmbedStatus | None, stale: bool, expected: NodeStatus
) -> None:
    assert source_node_status(parse, embed, stale=stale) == expected


# --- pair_score -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sources", "stale", "checklists", "expected"),
    [
        (0, 0, 0, 0),
        (0, 0, 1, 50),
        (0, 0, 3, 50),
        (1, 0, 0, 50),
        (1, 1, 0, 25),
        (2, 2, 0, 25),
        (2, 1, 0, 50),  # one fresh Source is enough
        (1, 0, 1, 100),
        (1, 1, 1, 75),
        (5, 4, 2, 100),
    ],
)
def test_pair_score(sources: int, stale: int, checklists: int, expected: int) -> None:
    assert pair_score(sources, stale, checklists) == expected


@pytest.mark.parametrize(("sources", "stale", "checklists"), [(-1, 0, 0), (0, -1, 0), (1, 2, 0)])
def test_pair_score_rejects_impossible_counts(sources: int, stale: int, checklists: int) -> None:
    with pytest.raises(ValueError):
        pair_score(sources, stale, checklists)


# --- node_score and source_score -----------------------------------------------------------


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ([], 0),
        ([0], 0),
        ([100], 100),
        ([100, 50], 75),
        ([100, 25], 63),  # 62.5 rounds half up
        ([25, 50], 38),  # 37.5 rounds half up
        ([50, 50, 25], 42),  # 41.67
        ([100, 100, 0], 67),  # 66.67
        ([75, 0, 0, 0], 19),  # 18.75
    ],
)
def test_node_score_is_the_rounded_mean(scores: list[int], expected: int) -> None:
    assert node_score(scores) == expected


@pytest.mark.parametrize("bad", [-1, 101])
def test_node_score_rejects_a_score_out_of_range(bad: int) -> None:
    with pytest.raises(ValueError):
        node_score([50, bad])


def test_source_score_by_status() -> None:
    assert source_score(NodeStatus.EMBEDDING_FAILED, [100]) == 15
    assert source_score(NodeStatus.EMBEDDING, [100]) == 70
    assert source_score(NodeStatus.READY, [100, 50]) == 75
    assert source_score(NodeStatus.STALE, [75]) == 75
    assert source_score(NodeStatus.READY, []) == 0


# --- aggregate_status ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], NodeStatus.MISSING),
        ([R.MISSING], NodeStatus.MISSING),
        ([R.MISSING, R.MISSING], NodeStatus.MISSING),
        ([R.READY], NodeStatus.READY),
        ([R.READY, R.READY], NodeStatus.READY),
        ([R.READY, R.PARTIAL], NodeStatus.PARTIAL),
        ([R.READY, R.MISSING], NodeStatus.PARTIAL),
        ([R.PARTIAL], NodeStatus.PARTIAL),
        ([R.PARTIAL, R.MISSING], NodeStatus.PARTIAL),
    ],
)
def test_aggregate_status(statuses: list[CoverageStatus], expected: NodeStatus) -> None:
    assert aggregate_status(statuses) == expected
    assert aggregate_status(iter(statuses)) == expected  # any iterable


# --- stale_in_days ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("reviewed", "today", "months", "expected"),
    [
        (date(2026, 1, 15), date(2026, 1, 15), 12, 366),  # stale on 16 Jan 2027
        (date(2025, 1, 15), date(2026, 1, 15), 12, 1),  # the last fresh day
        (date(2025, 1, 15), date(2026, 1, 16), 12, 0),  # stale
        (date(2024, 1, 1), date(2026, 1, 1), 12, 0),
        (date(2026, 8, 31), date(2026, 9, 1), 1, 30),  # month-end clamping
        (date(2024, 2, 29), date(2024, 3, 1), 12, 365),
    ],
)
def test_stale_in_days(reviewed: date, today: date, months: int, expected: int) -> None:
    days = stale_in_days(reviewed, today, months)
    assert days == expected


@pytest.mark.parametrize(
    ("reviewed", "today", "months"),
    [
        (date(2026, 1, 31), date(2026, 2, 1), 1),
        (date(2025, 12, 31), date(2026, 1, 10), 2),
        (date(2025, 5, 31), date(2025, 6, 1), 12),
        (date(2026, 3, 1), date(2026, 3, 1), 6),
    ],
)
def test_stale_in_days_lands_on_the_first_stale_day(
    reviewed: date, today: date, months: int
) -> None:
    days = stale_in_days(reviewed, today, months)
    assert days > 0
    assert is_stale(reviewed, today + timedelta(days=days), months)
    assert not is_stale(reviewed, today + timedelta(days=days - 1), months)
