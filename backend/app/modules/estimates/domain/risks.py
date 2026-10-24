"""Risk rules (Story 8.5): levels, their order, and the description rule. Pure.

A Risk is made from one open Gap by a person ("Convert to Risk"): a description, a
likelihood and an impact. It is never accepted and never a submission blocker.
"""

from enum import StrEnum

RISK_SUBJECT_TYPE = "estimates.risk"
"""The trace subject of a Risk."""

DESCRIPTION_MAX = 500
"""In Unicode code points, on the trimmed text."""
DESCRIPTION_RULE = f"The description must be 1 to {DESCRIPTION_MAX} characters."
NOTHING_RULE = "Change the description, the likelihood or the impact."


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


_RANK = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}


def risk_description(raw: str) -> str | None:
    """The description trimmed, if it is 1-500 characters; None otherwise."""
    trimmed = raw.strip()
    return trimmed if 0 < len(trimmed) <= DESCRIPTION_MAX else None


def risk_order(impact: str, likelihood: str, position: int) -> tuple[int, int, int]:
    """The Risks card's order: impact high first, then likelihood high first, then the order
    they were made in."""
    return _RANK[RiskLevel(impact)], _RANK[RiskLevel(likelihood)], position
