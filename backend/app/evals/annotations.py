"""The reference set (Story 7.6): `evals/reference/<slug>/sources/*` plus `annotations.yaml`
per Opportunity, loaded and checked here. See `evals/README.md` for the format and the
matching rules. Pure apart from reading files.
"""

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

REFERENCE_DIR = Path(__file__).resolve().parents[3] / "evals" / "reference"
"""`<repo>/evals/reference`."""
SOURCE_SUFFIXES = frozenset({".txt", ".eml", ".vtt"})
ANNOTATIONS_FILE = "annotations.yaml"
PLACEHOLDER_RE = re.compile(r"\[(?:CUSTOMER|SITE|PERSON_\d+|VENDOR|PRODUCT|CITY)\]")
EMAIL_RE = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)*)")
_ID_RE = r"^[A-Z]+\d+$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _keywords(values: list[str]) -> list[str]:
    cleaned = [v.strip() for v in values if v.strip()]
    if not cleaned:
        raise ValueError("at least one keyword is required")
    return cleaned


class AnnotatedRequirement(_Strict):
    """A Requirement the Intake Agent should extract. `quote` is a verbatim span of the
    named Source (whitespace may differ); an extracted Requirement matches when one of its
    evidence passages overlaps the quote's span."""

    id: str = Field(pattern=_ID_RE)
    text: str
    source: str
    quote: str = Field(min_length=8)


class AnnotatedGap(_Strict):
    """A Gap detection should raise. Matches a detected Gap when any keyword appears,
    ignoring case, in its title or why-it-matters. `mandatory`: a mandatory checklist item
    (marked here until Checklists exist, Stories 4.1/4.2)."""

    id: str = Field(pattern=_ID_RE)
    keywords: list[str]
    mandatory: bool = False

    _check = field_validator("keywords")(_keywords)


class IrrelevantGap(_Strict):
    """A label for Gaps that would be noise: a detected Gap hitting any keyword counts as
    irrelevant."""

    label: str
    keywords: list[str]

    _check = field_validator("keywords")(_keywords)


class IntegrationRisk(_Strict):
    """An integration risk the Specialists or the Red Team should raise (reported for Story
    7.7, no bar)."""

    id: str = Field(pattern=_ID_RE)
    keywords: list[str]

    _check = field_validator("keywords")(_keywords)


class EvidenceJudgement(_Strict):
    """A judged Finding→Requirement pair: a Finding whose title or detail hits any of
    `finding_keywords` and that cites the Requirement matching `requirement` is
    `supported` (or not) by that Requirement."""

    requirement: str = Field(pattern=_ID_RE)
    finding_keywords: list[str]
    supported: bool

    _check = field_validator("finding_keywords")(_keywords)


class Annotations(_Strict):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    title: str
    customer: str
    industry: str = "Warehouse automation"
    products: list[str] = Field(default_factory=lambda: ["Warehouse automation"])
    annotator: str
    """`draft` until a domain expert has reviewed the annotations."""
    requirements: list[AnnotatedRequirement]
    gaps: list[AnnotatedGap] = Field(default_factory=list)
    irrelevant_gaps: list[IrrelevantGap] = Field(default_factory=list)
    integration_risks: list[IntegrationRisk] = Field(default_factory=list)
    evidence: list[EvidenceJudgement] = Field(default_factory=list)

    @property
    def is_draft(self) -> bool:
        return self.annotator.strip().lower() == "draft"


@dataclass(frozen=True, slots=True)
class SourceFile:
    name: str
    data: bytes

    @property
    def text(self) -> str:
        return self.data.decode("utf-8")


@dataclass(frozen=True, slots=True)
class ReferenceOpportunity:
    annotations: Annotations
    sources: tuple[SourceFile, ...]

    @property
    def slug(self) -> str:
        return self.annotations.slug


class ReferenceSetError(ValueError):
    """The reference set is malformed (a message naming the file)."""


def _normalised(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def _source_files(folder: Path) -> list[Path]:
    sources = folder / "sources"
    if not sources.is_dir():
        raise ReferenceSetError(f"{folder.name}: no sources/ folder")
    files = sorted(p for p in sources.iterdir() if p.is_file())
    for path in files:
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            raise ReferenceSetError(f"{folder.name}: {path.name} is not .txt, .eml or .vtt")
    if not files:
        raise ReferenceSetError(f"{folder.name}: sources/ is empty")
    return files


def check_quotes(opportunity: ReferenceOpportunity) -> list[str]:
    """Problems with the annotations' references: unknown sources, quotes not in their
    source, duplicate ids, Evidence naming an unknown Requirement."""
    problems: list[str] = []
    by_name = {s.name: s.text for s in opportunity.sources}
    a = opportunity.annotations
    ids = [r.id for r in a.requirements]
    for kind, values in (
        ("requirement", ids),
        ("gap", [g.id for g in a.gaps]),
        ("integration risk", [r.id for r in a.integration_risks]),
    ):
        if len(set(values)) != len(values):
            problems.append(f"{a.slug}: duplicate {kind} ids")
    for req in a.requirements:
        text = by_name.get(req.source)
        if text is None:
            problems.append(f"{a.slug}: {req.id} names unknown source {req.source}")
        elif find_span(text, req.quote) is None:
            problems.append(f"{a.slug}: {req.id} quote is not in {req.source}")
    for judged in a.evidence:
        if judged.requirement not in ids:
            problems.append(f"{a.slug}: evidence names unknown requirement {judged.requirement}")
    return problems


def load_opportunity(folder: Path) -> ReferenceOpportunity:
    path = folder / ANNOTATIONS_FILE
    if not path.is_file():
        raise ReferenceSetError(f"{folder.name}: no {ANNOTATIONS_FILE}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        annotations = Annotations.model_validate(raw)
    except (yaml.YAMLError, ValueError) as exc:
        raise ReferenceSetError(f"{folder.name}/{ANNOTATIONS_FILE}: {exc}") from None
    if annotations.slug != folder.name:
        raise ReferenceSetError(f"{folder.name}: slug {annotations.slug!r} differs")
    sources = tuple(
        SourceFile(name=p.name, data=_normalised(p.read_bytes())) for p in _source_files(folder)
    )
    opportunity = ReferenceOpportunity(annotations=annotations, sources=sources)
    problems = check_quotes(opportunity)
    if problems:
        raise ReferenceSetError("; ".join(problems))
    return opportunity


def load_reference_set(
    root: Path = REFERENCE_DIR, only: Iterable[str] = ()
) -> list[ReferenceOpportunity]:
    """Every reference Opportunity under `root`, by slug; `only` limits it to those slugs."""
    wanted = set(only)
    folders = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    found = [load_opportunity(f) for f in folders if not wanted or f.name in wanted]
    missing = wanted - {o.slug for o in found}
    if missing:
        raise ReferenceSetError(f"unknown reference Opportunities: {', '.join(sorted(missing))}")
    return found


def reference_set_digest(root: Path = REFERENCE_DIR, slugs: Iterable[str] = ()) -> str:
    """The sha256 (hex) of the reference Opportunities that ran: every file in the `slugs`
    folders under `root` (all folders when none are given), relative path and content, in
    path order, line endings normalised to LF. A subset run so gets its own version."""
    wanted = set(slugs)
    digest = hashlib.sha256()
    files = (
        p
        for p in root.rglob("*")
        if p.is_file()
        and len(p.relative_to(root).parts) > 1
        and (not wanted or p.relative_to(root).parts[0] in wanted)
    )
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8") + b"\0")
        digest.update(_normalised(path.read_bytes()) + b"\0")
    return digest.hexdigest()


# --- quote spans -----------------------------------------------------------------------------


def find_spans(text: str, quote: str) -> list[tuple[int, int]]:
    """Every `[start, end)` code-point span of `quote` in `text`, ignoring case and treating
    any run of whitespace as one space."""
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    if not pattern:
        return []
    return [(m.start(), m.end()) for m in re.finditer(pattern, text, flags=re.IGNORECASE)]


def find_span(text: str, quote: str) -> tuple[int, int] | None:
    """The first span of `quote` in `text` (`find_spans`), None when absent."""
    spans = find_spans(text, quote)
    return spans[0] if spans else None


# --- anonymisation -----------------------------------------------------------------------------

AnonymisationProblem = tuple[str, Literal["email", "placeholder", "name"], str]


def anonymisation_problems(
    opportunities: Iterable[ReferenceOpportunity], denied: Iterable[str] = ()
) -> list[AnonymisationProblem]:
    """(slug/file, kind, detail) for every email outside a `.example` domain, every
    Opportunity whose Sources never use the `[CUSTOMER]` placeholder, and every `denied`
    name (from the original scenarios) that appears in a Source or the annotations."""
    names = [n for n in denied if n.strip()]
    problems: list[AnonymisationProblem] = []
    for opportunity in opportunities:
        slug = opportunity.slug
        customer_seen = False
        texts = [(s.name, s.text) for s in opportunity.sources]
        texts.append((ANNOTATIONS_FILE, opportunity.annotations.model_dump_json()))
        for name, text in texts:
            where = f"{slug}/{name}"
            for match in EMAIL_RE.finditer(text):
                domain = match.group(1).lower()
                if not (domain == "example" or domain.endswith(".example")):
                    problems.append((where, "email", match.group(0)))
            if "[CUSTOMER]" in text and name != ANNOTATIONS_FILE:
                customer_seen = True
            lowered = text.lower()
            problems.extend((where, "name", n) for n in names if n.lower() in lowered)
        if not customer_seen:
            problems.append((slug, "placeholder", "no source uses [CUSTOMER]"))
    return problems
