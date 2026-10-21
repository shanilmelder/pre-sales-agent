"""Embedding state of a Knowledge Source version, and search limits (Story 3.3). Pure.

A parsed version is `queued`, then `embedding`, then `ready` (its chunks are searchable) or
`failed` with an `EmbedErrorCode`. A version parsed before Story 3.3 has no embedding state
and can be embedded on request.
"""

from enum import StrEnum

EVIDENCE_KIND = "knowledge_chunk"
"""The Evidence kind of a citation of a Knowledge chunk (AD-13)."""
SEARCH_K_DEFAULT = 8
SEARCH_K_MAX = 50
QUERY_MAX = 2000


class EmbedStatus(StrEnum):
    QUEUED = "queued"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class EmbedErrorCode(StrEnum):
    """Why embedding a version failed, once its retries ran out."""

    MODEL_UNAVAILABLE = "model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_BAD_OUTPUT = "model_bad_output"
    TEXT_MISSING = "text_missing"
    INTERNAL_ERROR = "internal_error"


IN_PROGRESS: tuple[str, ...] = (EmbedStatus.QUEUED.value, EmbedStatus.EMBEDDING.value)


def search_query(value: str) -> str:
    """The trimmed query; `ValueError` (the sentence to show) when blank or too long."""
    trimmed = value.strip()
    if not trimmed:
        raise ValueError("Enter something to search for.")
    if len(trimmed) > QUERY_MAX:
        raise ValueError(f"The query must be at most {QUERY_MAX:,} characters.")
    return trimmed


def span_inside(start: int, end: int, chunk_start: int, chunk_end: int) -> bool:
    """True when the cited span `[start, end)` is non-empty and lies inside the chunk's."""
    return chunk_start <= start < end <= chunk_end
