"""The Evidence resolver registry (AD-13, Story 3.3): one resolver per Evidence kind.

An Evidence reference is `{kind, id, version?, span?}` (`app.agents.contract.EvidenceRef`).
The module that owns a kind registers a resolver at import (knowledge registers
`knowledge_chunk`); an `accept_*` command calls `resolve_all(uow, refs)` before writing, and
any reference that doesn't resolve (an unknown kind included) rejects the whole call with a
422 `evidence_unresolvable` naming the first bad reference. Nothing calls `resolve_all` yet:
no `accept_*` command emits a registered kind so far.

This module is platform code, so it sees references only through the `Ref` Protocol and never
imports `app.agents` or a business module.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Protocol
from uuid import UUID

from app.platform.errors import EvidenceUnresolvableError
from app.platform.uow import UnitOfWork


class SpanLike(Protocol):
    @property
    def start(self) -> int: ...

    @property
    def end(self) -> int: ...


class Ref(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def id(self) -> UUID: ...

    @property
    def version(self) -> int | None: ...

    @property
    def span(self) -> SpanLike | None: ...


type Resolver = Callable[[UnitOfWork, Sequence[Ref]], Awaitable[list[str | None]]]
"""Checks references of its kind; per reference, None when it resolves, else the reason."""

_RESOLVERS: dict[str, Resolver] = {}
RESOLVERS: Mapping[str, Resolver] = MappingProxyType(_RESOLVERS)


def register_resolver(kind: str, resolver: Resolver) -> None:
    if kind in _RESOLVERS and _RESOLVERS[kind] is not resolver:
        raise ValueError(f"an Evidence resolver for {kind!r} is already registered")
    _RESOLVERS[kind] = resolver


def describe(ref: Ref) -> str:
    """The reference as the error names it: kind, id, version and span, no text."""
    parts = [f"{ref.kind}:{ref.id}"]
    if ref.version is not None:
        parts.append(f"v{ref.version}")
    if ref.span is not None:
        parts.append(f"[{ref.span.start}, {ref.span.end})")
    return " ".join(parts)


async def check_all(uow: UnitOfWork, refs: Sequence[Ref]) -> list[str | None]:
    """Per reference, None when it resolves, else why not. Unknown kinds don't resolve."""
    reasons: list[str | None] = [None] * len(refs)
    by_kind: dict[str, list[int]] = {}
    for index, ref in enumerate(refs):
        by_kind.setdefault(ref.kind, []).append(index)
    for kind, indexes in by_kind.items():
        resolver = _RESOLVERS.get(kind)
        if resolver is None:
            for index in indexes:
                reasons[index] = f"no resolver for Evidence kind {kind!r}"
            continue
        results = await resolver(uow, [refs[i] for i in indexes])
        for index, reason in zip(indexes, results, strict=True):
            reasons[index] = reason
    return reasons


async def resolve_all(uow: UnitOfWork, refs: Sequence[Ref]) -> None:
    """Return when every reference resolves; else raise `EvidenceUnresolvableError` naming
    the first that doesn't."""
    for ref, reason in zip(refs, await check_all(uow, refs), strict=True):
        if reason is not None:
            raise EvidenceUnresolvableError(f"Evidence {describe(ref)} does not resolve: {reason}.")
