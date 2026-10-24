"""Knowledge coverage rule (Story 3.5). Pure, no I/O.

For one product and Integration Type pair: how many Ready Sources (and how many of those are
stale) and how many published Checklists cover it, and what that adds up to.

- **Ready**: at least one non-stale Source and at least one Checklist.
- **Partial**: exactly one kind, or Sources that are all stale with a Checklist.
- **Missing**: no Sources and no Checklists.
"""

from enum import StrEnum


class CoverageStatus(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    MISSING = "missing"


def coverage_status(sources: int, stale: int, checklists: int) -> CoverageStatus:
    """The status of a pair with `sources` Ready Sources (`stale` of them stale) and
    `checklists` published Checklists. Raises `ValueError` for a negative count or more stale
    Sources than Sources."""
    if sources < 0 or stale < 0 or checklists < 0:
        raise ValueError("Coverage counts can't be negative.")
    if stale > sources:
        raise ValueError("There can't be more stale Sources than Sources.")
    if sources == 0 and checklists == 0:
        return CoverageStatus.MISSING
    if sources - stale >= 1 and checklists >= 1:
        return CoverageStatus.READY
    return CoverageStatus.PARTIAL
