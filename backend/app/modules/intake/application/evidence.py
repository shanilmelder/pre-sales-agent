"""intake's Evidence kinds (AD-13, Story 6.6): `requirement` and `source_document`.

A reference `{kind: requirement, id, version}` resolves when that version of the Requirement
exists (versions are immutable, so a reference keeps resolving after an edit or a removal);
`{kind: source_document, id, version}` when that version of the Source exists. Both need a
version. The resolvers are registered with `app.platform.evidence` at import; they see no
Opportunity, so a command citing them also checks `foreign_evidence` (the references must
belong to the Opportunity whose record they support).

`evidence_options` is the picker: the Opportunity's active Requirements at their current
versions (`R<n>`) and its Sources at their latest versions (`S<n> · <file name>`), for
anyone who can read the Opportunity. Ids and numbers only in errors, never text.
"""

from collections.abc import Sequence
from uuid import UUID

from app.modules.identity.application.public import Principal
from app.modules.intake.adapters import repository as sources_repo
from app.modules.intake.adapters import requirements_repository as repo
from app.modules.intake.application.models import EvidenceOption, EvidenceOptions
from app.modules.opportunities.application import public as opportunities
from app.platform import evidence
from app.platform.evidence import Ref
from app.platform.uow import UnitOfWork

REQUIREMENT_KIND = "requirement"
SOURCE_DOCUMENT_KIND = "source_document"
EXCERPT_MAX = 140


def _excerpt(text: str, limit: int = EXCERPT_MAX) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip() + "…"


def _pairs(refs: Sequence[Ref], kind: str) -> list[tuple[UUID, int]]:
    return [(r.id, r.version) for r in refs if r.kind == kind and r.version is not None]


async def check_requirement_refs(uow: UnitOfWork, refs: Sequence[Ref]) -> list[str | None]:
    """Per reference, None when that Requirement version exists, else why not."""
    found = await repo.requirement_version_owners(uow, _pairs(refs, REQUIREMENT_KIND))
    reasons: list[str | None] = []
    for ref in refs:
        if ref.kind != REQUIREMENT_KIND:
            reasons.append(f"not a {REQUIREMENT_KIND} reference")
        elif ref.version is None:
            reasons.append("the Requirement version is missing")
        elif (ref.id, ref.version) not in found:
            reasons.append("no such Requirement version")
        else:
            reasons.append(None)
    return reasons


async def check_source_refs(uow: UnitOfWork, refs: Sequence[Ref]) -> list[str | None]:
    """Per reference, None when that Source version exists, else why not."""
    found = await repo.source_version_owners(uow, _pairs(refs, SOURCE_DOCUMENT_KIND))
    reasons: list[str | None] = []
    for ref in refs:
        if ref.kind != SOURCE_DOCUMENT_KIND:
            reasons.append(f"not a {SOURCE_DOCUMENT_KIND} reference")
        elif ref.version is None:
            reasons.append("the Source version is missing")
        elif (ref.id, ref.version) not in found:
            reasons.append("no such Source version")
        else:
            reasons.append(None)
    return reasons


async def foreign_evidence(
    uow: UnitOfWork, opportunity_id: UUID, refs: Sequence[Ref]
) -> Ref | None:
    """The first `requirement` or `source_document` reference that exists but belongs to
    another Opportunity; None when all of them are this one's. Other kinds are ignored."""
    requirements = await repo.requirement_version_owners(uow, _pairs(refs, REQUIREMENT_KIND))
    sources = await repo.source_version_owners(uow, _pairs(refs, SOURCE_DOCUMENT_KIND))
    for ref in refs:
        if ref.version is None:
            continue
        key = (ref.id, ref.version)
        if ref.kind == REQUIREMENT_KIND and requirements.get(key, opportunity_id) != opportunity_id:
            return ref
        if ref.kind == SOURCE_DOCUMENT_KIND and key in sources:
            if sources[key][0] != opportunity_id:
                return ref
    return None


async def evidence_labels(
    uow: UnitOfWork, opportunity_id: UUID, refs: Sequence[tuple[str, UUID, int | None]]
) -> dict[tuple[str, UUID, int | None], str]:
    """How the Opportunity's cited Evidence reads: `R<n>` for a Requirement still active
    (`Superseded` otherwise), `S<n> · <file name>` for a Source. Unknown ones are left out."""
    numbers = {r.id: r.number for r in await repo.active_requirements(uow, opportunity_id)}
    source_numbers = await repo.source_numbers(uow, opportunity_id)
    files = await repo.source_version_owners(
        uow, [(i, v) for k, i, v in refs if k == SOURCE_DOCUMENT_KIND and v is not None]
    )
    labels: dict[tuple[str, UUID, int | None], str] = {}
    for key in refs:
        kind, ref_id, version = key
        if kind == REQUIREMENT_KIND:
            number = numbers.get(ref_id)
            labels[key] = f"R{number}" if number is not None else "Superseded"
        elif kind == SOURCE_DOCUMENT_KIND and version is not None:
            found = files.get((ref_id, version))
            number = source_numbers.get(ref_id)
            if found is not None and number is not None:
                labels[key] = f"S{number} · {found[1]}"
    return labels


async def evidence_options(
    uow: UnitOfWork, actor: Principal, opportunity_id: UUID
) -> EvidenceOptions:
    """The Evidence picker (module docstring); the Opportunity's 404 for those who can't
    read it."""
    await opportunities.readable_resource(uow, actor, opportunity_id)
    numbers = await repo.source_numbers(uow, opportunity_id)
    sources = sorted(
        await sources_repo.list_for(uow, opportunity_id), key=lambda s: numbers.get(s.id, 0)
    )
    return EvidenceOptions(
        items=[
            *(
                EvidenceOption(
                    kind=REQUIREMENT_KIND,
                    id=str(r.id),
                    version=r.version,
                    label=f"R{r.number}",
                    excerpt=_excerpt(r.text),
                )
                for r in await repo.active_requirements(uow, opportunity_id)
            ),
            *(
                EvidenceOption(
                    kind=SOURCE_DOCUMENT_KIND,
                    id=str(s.id),
                    version=s.version,
                    label=f"S{numbers.get(s.id, 0)} · {s.filename}",
                    excerpt="",
                )
                for s in sources
            ),
        ]
    )


evidence.register_resolver(REQUIREMENT_KIND, check_requirement_refs)
evidence.register_resolver(SOURCE_DOCUMENT_KIND, check_source_refs)
