"""Conflict vocabulary (Story 6.1): types, severities, statuses, who detected it, where a
position comes from, the agents' role names, and display helpers. Pure."""

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

CONFLICT_SUBJECT_TYPE = "conflicts.conflict"
"""The trace subject of a Conflict."""


class ConflictType(StrEnum):
    TIMELINE = "timeline"
    EFFORT = "effort"
    RESOURCE = "resource"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    SCOPE = "scope"
    ASSUMPTION = "assumption"
    EVIDENCE = "evidence"


class ConflictSeverity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_ORDER: tuple[ConflictSeverity, ...] = (
    ConflictSeverity.CRITICAL,
    ConflictSeverity.HIGH,
    ConflictSeverity.MEDIUM,
    ConflictSeverity.LOW,
)


def severity_rank(severity: str) -> int:
    """0 for critical … 3 for low."""
    try:
        return SEVERITY_ORDER.index(ConflictSeverity(severity))
    except ValueError:  # pragma: no cover - the table only holds known severities
        return len(SEVERITY_ORDER)


class ConflictStatus(StrEnum):
    OPEN = "open"
    NEGOTIATING = "negotiating"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


UNRESOLVED = frozenset({ConflictStatus.OPEN, ConflictStatus.NEGOTIATING, ConflictStatus.ESCALATED})
"""Listed in the Open section."""
BLOCKING = frozenset({ConflictStatus.OPEN, ConflictStatus.ESCALATED})
"""Counted on the tab badge and returned by `list_open`."""


class DetectedBy(StrEnum):
    RULE = "rule"
    SEMANTIC = "semantic"
    CRITIC = "critic"
    RED_TEAM = "red_team"


class PositionSource(StrEnum):
    ASSESSMENT = "assessment"
    ESTIMATE = "estimate"


AGENT_ORDER: tuple[str, ...] = ("engineering_agent", "pm_agent", "security_agent")
"""The specialist agents in the order they are listed."""
AGENT_ROLES: dict[str, str] = {
    "engineering_agent": "Engineering",
    "pm_agent": "PM",
    "security_agent": "Security",
}


def agent_rank(agent: str | None) -> int:
    """Position of an agent in `AGENT_ORDER`; unknown agents, then the Estimate, last."""
    if agent is None:
        return len(AGENT_ORDER) + 1
    try:
        return AGENT_ORDER.index(agent)
    except ValueError:
        return len(AGENT_ORDER)


def agent_role(agent: str) -> str:
    """The role name ("Engineering", "PM", "Security"); an unknown agent id in words."""
    return AGENT_ROLES.get(agent) or " ".join(w.capitalize() for w in agent.split("_") if w)


TENTH = Decimal("0.1")


def tenth(value: Decimal) -> Decimal:
    """Hours to 0.1 (half up), as stored."""
    return value.quantize(TENTH, rounding=ROUND_HALF_UP)


def hours_label(value: Decimal) -> str:
    """Hours as shown, to 0.1: "24 h", "24.5 h"."""
    rounded = tenth(value)
    text = f"{rounded:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return f"{text} h"


EXCERPT_MAX = 140


def excerpt(text: str, limit: int = EXCERPT_MAX) -> str:
    """At most `limit` code points of `text` on one line, cut at whitespace where possible,
    ending in `…` when cut."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"
