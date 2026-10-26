"""Replies (Story 9.4; AD-28): what the author of a Review Request may answer, and when. Pure,
no I/O.

A reply answers a reviewer's request for evidence or for an alternative, so it is allowed only
while the request is `pending` and its latest decision is one of those. It never changes the
request's status. Only after `alternative_requested` may it name a newer draft Estimate
Version as the alternative; once that draft is submitted, the original request is superseded
and a request linked to it goes to the same reviewer for the new version.
"""

from app.modules.reviews.domain.decisions import Decision

REPLY_MAX = 2000
"""Code points, on the trimmed message."""
REPLY_EVIDENCE_MAX = 20

REPLYABLE = frozenset({Decision.EVIDENCE_REQUESTED, Decision.ALTERNATIVE_REQUESTED})
"""The latest decisions a reply answers."""


def may_reply(latest: Decision | None) -> bool:
    return latest in REPLYABLE


def may_link_alternative(latest: Decision | None) -> bool:
    return latest is Decision.ALTERNATIVE_REQUESTED


def clean_reply_message(raw: str) -> str:
    """The trimmed message; `ValueError` when blank or over `REPLY_MAX`."""
    text = raw.strip()
    if not 1 <= len(text) <= REPLY_MAX:
        raise ValueError("message")
    return text
