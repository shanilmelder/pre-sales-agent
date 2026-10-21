"""Source data for answering Clarification Questions (Story 4.7). No authorization here:
callers (`gaps`) have already checked that the actor may act on the Opportunity, or run as
the worker.

- `resolve_passage`: the passage of a parsed Source version that a quote resolves to
  (`domain.requirements.resolve_quote` over the extracted text), stored if new.
- `passage_refs`: passages with their `S<n> · <file name>` label and their cited text.
- `requirement_changes_for_source`: the Requirements a Source changed, as
  `{requirement_id, label, kind}`: `added` or `versioned` for those whose Evidence cites one
  of its passages, `pending` (an open change), `accepted`, `rejected` or `superseded` for those
  with a change proposing one of its passages. One entry per Requirement, a change's kind
  first, ordered by label.

Logs nothing: callers log ids.
"""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.application.requirements import LABEL_SEPARATOR
from app.modules.intake.application.texts import extracted_text
from app.modules.intake.domain.requirements import resolve_quote
from app.platform.storage import BlobStore
from app.platform.uow import UnitOfWork

RequirementChangeKind = Literal[
    "added", "versioned", "pending", "accepted", "rejected", "superseded"
]
INACTIVE_LABEL = "Superseded"
_CHANGE_KINDS: dict[str, RequirementChangeKind] = {
    "open": "pending",
    "accepted": "accepted",
    "rejected": "rejected",
    "superseded": "superseded",
}
_CHANGE_ORDER = ("pending", "accepted", "rejected", "superseded")


class RequirementChangeRef(BaseModel):
    """A Requirement a Source changed (Story 4.7). `label` is `R<n>`, the Requirement's
    stable number within the Opportunity, or `Superseded` once it is no longer active.
    `kind`: `added` (created from the Source), `versioned` (a new version cites it), or the
    status of a pending change proposing one of its passages (`pending`, `accepted`,
    `rejected`, `superseded`)."""

    requirement_id: str
    label: str
    kind: RequirementChangeKind


@dataclass(frozen=True, slots=True)
class ResolvedPassage:
    passage_id: UUID
    text: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class PassageRef:
    """A passage with its Source version and label, and its cited text ("" when the text
    can't be read)."""

    passage_id: UUID
    source_id: UUID
    source_version: int
    filename: str
    label: str
    text: str = field(repr=False)


async def resolve_passage(
    uow: UnitOfWork,
    source_id: UUID,
    version: int,
    quote: str,
    *,
    store: BlobStore | None = None,
) -> ResolvedPassage | None:
    """The passage of the parsed Source version that `quote` resolves to (exactly, or
    ignoring case and spacing), stored if new; None when the version has no readable text or
    the quote isn't in it."""
    text = await extracted_text(uow, source_id, version, store=store)
    if text is None:
        return None
    span = resolve_quote(text, quote)
    if span is None:
        return None
    start, end = span
    passage_id = await repo.passage(uow, source_id=source_id, version=version, start=start, end=end)
    return ResolvedPassage(passage_id=passage_id, text=text[start:end])


async def passage_refs(
    uow: UnitOfWork,
    opportunity_id: UUID,
    passage_ids: list[UUID],
    *,
    store: BlobStore | None = None,
) -> dict[UUID, PassageRef]:
    """These passages of the Opportunity's Sources, keyed by id; unknown ones and those of
    other Opportunities are left out."""
    found = await repo.passages_by_id(uow, list(set(passage_ids)))
    if not found:
        return {}
    numbers = await repo.source_numbers(uow, opportunity_id)
    texts: dict[tuple[UUID, int], str | None] = {}
    refs: dict[UUID, PassageRef] = {}
    for record in found.values():
        number = numbers.get(record.source_id)
        if number is None:
            continue
        key = (record.source_id, record.source_version)
        if key not in texts:
            texts[key] = await extracted_text(uow, *key, store=store)
        text = texts[key]
        refs[record.id] = PassageRef(
            passage_id=record.id,
            source_id=record.source_id,
            source_version=record.source_version,
            filename=record.filename,
            label=f"S{number}{LABEL_SEPARATOR}{record.filename}",
            text="" if text is None or record.end > len(text) else text[record.start : record.end],
        )
    return refs


async def requirement_changes_for_source(
    uow: UnitOfWork, source_id: UUID
) -> list[RequirementChangeRef]:
    """The Requirements the Source added, versioned or proposed changes to (see the module
    docstring), ordered by label (`Superseded` last)."""
    opportunity_id = await repo.source_opportunity(uow, source_id)
    if opportunity_id is None:
        return []
    kinds: dict[UUID, RequirementChangeKind] = {}
    for requirement_id, status in await repo.changes_citing_source(uow, source_id):
        kind = _CHANGE_KINDS.get(status)
        current = kinds.get(requirement_id)
        if kind is not None and (
            current is None or _CHANGE_ORDER.index(kind) < _CHANGE_ORDER.index(current)
        ):
            kinds[requirement_id] = kind
    for citation in await repo.requirements_citing_source(uow, source_id):
        kinds.setdefault(
            citation.requirement_id, "added" if citation.created_after_source else "versioned"
        )
    if not kinds:
        return []
    # The stable `R<n>` (Story 2.6), so a label never moves after a delete, split or merge.
    numbers = {r.id: r.number for r in await repo.active_requirements(uow, opportunity_id)}
    last = max(numbers.values(), default=0) + 1
    ordered = sorted(kinds.items(), key=lambda item: (numbers.get(item[0], last), str(item[0])))
    return [
        RequirementChangeRef(
            requirement_id=str(requirement_id),
            label=f"R{numbers[requirement_id]}" if requirement_id in numbers else INACTIVE_LABEL,
            kind=kind,
        )
        for requirement_id, kind in ordered
    ]
