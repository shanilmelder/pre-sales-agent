"""Knowledge Graph rules (Story 3.6): node status and the Coverage score. Pure, no I/O.

The PRD leaves the exact score formula open, so it lives here, in one place:

- A product and Integration Type **pair** scores 50 when at least one Ready Source that isn't
  stale covers it, or 25 when its Ready Sources are all stale; and another 50 when at least
  one published Checklist covers it.
- A **Product**, **Integration Type** or **Checklist** scores the mean of its pairs, rounded
  half up, or 0 with no pairs.
- A **Knowledge Source** scores 15 when its pipeline failed and 70 while it is still being
  parsed or embedded; otherwise the mean of its product's pairs with its Integration Types.

A Source's status comes from its pipeline and the stale flag (`source_node_status`). A
Product's, Integration Type's or Checklist's comes from its pairs' coverage statuses
(`aggregate_status`): Ready when every pair is Ready, Missing with no covered pair, else
Partial.
"""

from collections.abc import Iterable, Sequence
from datetime import date, timedelta
from enum import StrEnum

from app.modules.knowledge.domain.coverage import CoverageStatus
from app.modules.knowledge.domain.embedding import EmbedStatus
from app.modules.knowledge.domain.sources import is_stale
from app.platform.parsing.rules import ParseStatus

SOURCES_POINTS = 50
STALE_SOURCES_POINTS = 25
CHECKLISTS_POINTS = 50
FAILED_SCORE = 15
EMBEDDING_SCORE = 70
SCORE_MAX = 100


class NodeStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    MISSING = "missing"
    STALE = "stale"
    EMBEDDING = "embedding"
    EMBEDDING_FAILED = "embedding_failed"


def source_node_status(parse: ParseStatus, embed: EmbedStatus | None, *, stale: bool) -> NodeStatus:
    """A Source's status: **Embedding failed** when its latest version's parse or embedding
    failed; **Embedding** while the parse or the embedding is queued or running (or the
    version, parsed before embedding existed, has no embedding yet); otherwise (embedded,
    Ready) **Stale** past the stale threshold, else **Ready**."""
    if parse == ParseStatus.FAILED or embed == EmbedStatus.FAILED:
        return NodeStatus.EMBEDDING_FAILED
    if parse != ParseStatus.PARSED or embed != EmbedStatus.READY:
        return NodeStatus.EMBEDDING
    return NodeStatus.STALE if stale else NodeStatus.READY


def pair_score(sources: int, stale: int, checklists: int) -> int:
    """The score of a pair with `sources` Ready Sources (`stale` of them stale) and
    `checklists` published Checklists. Raises `ValueError` for counts `coverage_status`
    rejects."""
    if sources < 0 or stale < 0 or checklists < 0:
        raise ValueError("Coverage counts can't be negative.")
    if stale > sources:
        raise ValueError("There can't be more stale Sources than Sources.")
    score = 0
    if sources - stale >= 1:
        score += SOURCES_POINTS
    elif sources >= 1:
        score += STALE_SOURCES_POINTS
    if checklists >= 1:
        score += CHECKLISTS_POINTS
    return score


def node_score(pair_scores: Sequence[int]) -> int:
    """The mean of the pair scores, rounded half up; 0 with none. Raises `ValueError` for a
    score outside 0 to 100."""
    if any(s < 0 or s > SCORE_MAX for s in pair_scores):
        raise ValueError("A pair score is between 0 and 100.")
    if not pair_scores:
        return 0
    total, count = sum(pair_scores), len(pair_scores)
    return (2 * total + count) // (2 * count)


def source_score(status: NodeStatus, pair_scores: Sequence[int]) -> int:
    """A Source's score: 15 when its pipeline failed, 70 while it is embedding, else the
    mean of its pairs (`node_score`)."""
    if status == NodeStatus.EMBEDDING_FAILED:
        return FAILED_SCORE
    if status == NodeStatus.EMBEDDING:
        return EMBEDDING_SCORE
    return node_score(pair_scores)


def aggregate_status(pair_statuses: Iterable[CoverageStatus]) -> NodeStatus:
    """**Ready** when every pair is Ready, **Missing** when no pair is covered (or there are
    none), else **Partial**."""
    statuses = list(pair_statuses)
    if all(s == CoverageStatus.MISSING for s in statuses):
        return NodeStatus.MISSING
    if all(s == CoverageStatus.READY for s in statuses):
        return NodeStatus.READY
    return NodeStatus.PARTIAL


def stale_in_days(last_reviewed_on: date, today: date, months: int) -> int:
    """Days until a Source last reviewed on `last_reviewed_on` turns stale (`is_stale`); 0
    when it already is."""
    if is_stale(last_reviewed_on, today, months):
        return 0
    # The first day it is stale is near `last_reviewed_on` plus `months` months; month-end
    # clamping can move it by a few days, so step to the exact day.
    index = last_reviewed_on.year * 12 + (last_reviewed_on.month - 1) + months
    year, month = divmod(index, 12)
    guess = date(year, month + 1, 1) + timedelta(days=min(last_reviewed_on.day, 28) - 1)
    guess = max(guess, today + timedelta(days=1))
    while is_stale(last_reviewed_on, guess - timedelta(days=1), months) and guess > today:
        guess -= timedelta(days=1)
    while not is_stale(last_reviewed_on, guess, months):
        guess += timedelta(days=1)
    return (guess - today).days
