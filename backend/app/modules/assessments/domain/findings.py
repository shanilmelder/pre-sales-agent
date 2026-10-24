"""Blocking Findings and overrides (Story 6.6): a Critic or Red Team Finding's status, its
fingerprint, how it is resolved, and the reason rule. Pure.

- **Status**: `open` when stored, then `resolved` (Evidence supplied, or addressed with a
  reason) or `overridden` (a permitted person accepts it with a reason). Only `open` Findings
  change.
- **Blocking**: an `open`, `critical` Finding of a current Critic or Red Team Review blocks
  submission until resolved or overridden.
- **Fingerprint**: a hash of the Review kind, the category and the sorted cited Requirement
  ids, plus (Red Team) the cited Estimate lines' keys or (Critic) the cited specialist
  Finding ids. A newer Finding with the fingerprint of an overridden one starts `open` and
  shows that override; nothing carries over by itself.
- **Line key**: an Estimate line's section and its title (trimmed, case-folded, spaces
  collapsed), so that the same line keeps its key across Estimate Versions.
"""

import hashlib
from collections.abc import Iterable
from enum import StrEnum

FINDING_SUBJECT_TYPE = "assessments.finding"
"""The trace subject of a Critic or Red Team Finding."""
REASON_MAX = 1000
REASON_RULE = "Give a reason of 1 to 1,000 characters."
EVIDENCE_MAX = 20
POLICY_KIND = "checklist_item"


class FindingStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    OVERRIDDEN = "overridden"


class ResolutionKind(StrEnum):
    EVIDENCE_SUPPLIED = "evidence_supplied"
    ADDRESSED = "addressed"


BLOCKING_SEVERITY = "critical"


def is_blocking(status: str, severity: str) -> bool:
    """Whether a Finding of a current Review blocks submission."""
    return status == FindingStatus.OPEN and severity == BLOCKING_SEVERITY


def finding_reason(raw: str | None) -> str | None:
    """The reason trimmed, if it is 1-1,000 characters; None otherwise."""
    if raw is None:
        return None
    text = raw.strip()
    return text if 1 <= len(text) <= REASON_MAX else None


def line_key(section: str, title: str) -> str:
    """An Estimate line's key across versions: `<section>:<title>` normalised."""
    return f"{section.strip().casefold()}:{' '.join(title.split()).casefold()}"


def fingerprint(
    kind: str, category: str, requirement_ids: Iterable[object], keys: Iterable[str] = ()
) -> str:
    """The Finding's fingerprint: SHA-256 (hex) of the kind, category, sorted Requirement ids
    and sorted extra keys (line keys or specialist Finding ids). The migration that
    backfilled it holds a literal copy of this function; a test keeps them equal."""
    parts = [
        kind,
        category,
        ",".join(sorted(str(r) for r in requirement_ids)),
        ",".join(sorted(keys)),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()
