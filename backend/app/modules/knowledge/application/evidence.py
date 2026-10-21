"""The `knowledge_chunk` Evidence resolver (AD-13, Story 3.3).

A reference `{kind: knowledge_chunk, id, version, span?}` resolves when the chunk `id`
exists, `version` is the Source version it belongs to, and the span (when given) is a
non-empty range inside the chunk's offsets in that version's extracted text. Chunks are
insert-only, so a reference to an earlier version keeps resolving after a new version or
retirement (the UI shows such a citation as superseded). Registered with
`app.platform.evidence` at import; `resolve_evidence` checks references of this kind
directly.
"""

from collections.abc import Sequence

from app.modules.knowledge.adapters import chunk_repository as chunks
from app.modules.knowledge.domain.embedding import EVIDENCE_KIND, span_inside
from app.platform import evidence
from app.platform.errors import EvidenceUnresolvableError
from app.platform.evidence import Ref
from app.platform.uow import UnitOfWork


async def check_chunk_refs(uow: UnitOfWork, refs: Sequence[Ref]) -> list[str | None]:
    """Per reference, None when it resolves, else why not (ids and numbers only)."""
    found = await chunks.chunk_refs(uow, [r.id for r in refs if r.kind == EVIDENCE_KIND])
    reasons: list[str | None] = []
    for ref in refs:
        chunk = found.get(ref.id) if ref.kind == EVIDENCE_KIND else None
        if ref.kind != EVIDENCE_KIND:
            reasons.append(f"not a {EVIDENCE_KIND} reference")
        elif chunk is None:
            reasons.append("no such Knowledge chunk")
        elif ref.version is None:
            reasons.append("the Source version is missing")
        elif ref.version != chunk.version:
            reasons.append(f"the chunk belongs to version {chunk.version}")
        elif ref.span is not None and not span_inside(
            ref.span.start, ref.span.end, chunk.start, chunk.end
        ):
            reasons.append(f"the span lies outside the chunk [{chunk.start}, {chunk.end})")
        else:
            reasons.append(None)
    return reasons


async def resolve_evidence(uow: UnitOfWork, refs: Sequence[Ref]) -> None:
    """Return when every reference is a resolvable `knowledge_chunk`; else raise
    `EvidenceUnresolvableError` (422) naming the first that isn't."""
    for ref, reason in zip(refs, await check_chunk_refs(uow, refs), strict=True):
        if reason is not None:
            raise EvidenceUnresolvableError(
                f"Evidence {evidence.describe(ref)} does not resolve: {reason}."
            )


evidence.register_resolver(EVIDENCE_KIND, check_chunk_refs)
