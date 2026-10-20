"""Semantic Conflict detection (Story 6.2): the Findings the Conflict Agent reads, how they
are labelled, and the validation of the candidate Conflicts it proposes. Pure: shared by the
`conflicts.semantic_detection` job and the `make eval-conflicts` runner.

- Each current specialist Finding is labelled `F<n>` (agent order, then Finding order); the
  model cites Findings only by label, and the labels map back to (Finding id, Assessment id,
  version) here.
- A candidate is dropped when its type is not one of `architecture | assumption | evidence |
  scope`, its severity is unknown, it cites fewer than two known Findings or Findings from
  fewer than two agents, it cites an unknown label, a cited Assessment is no longer current
  at its cited version, it claims a mandatory-constraint violation (those are decided only by
  rules), its summary or a stance is blank or over 240 characters, or it duplicates an open
  or escalated rule Conflict (only `scope`: any Requirement every cited Finding cites has an
  open or escalated `scope:<r>` rule Conflict, see `rule_key`) or an earlier candidate of the
  same reply.
- Only a reply whose candidates were all dropped as malformed is bad output to retry
  (`SemanticValidation.retry`); drops for `LEGITIMATE_DROPS` count as zero found.
- The fingerprint is `semantic:<type>:<sorted Finding ids>`.
"""

import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.conflicts.domain.conflicts import (
    ConflictSeverity,
    ConflictType,
    agent_rank,
    agent_role,
)

SEMANTIC_PREFIX = "semantic"
SEMANTIC_TYPES: tuple[ConflictType, ...] = (
    ConflictType.ARCHITECTURE,
    ConflictType.ASSUMPTION,
    ConflictType.EVIDENCE,
    ConflictType.SCOPE,
)
SUMMARY_MAX = 240
STANCE_MAX = 240
NOT_RAISED_AGAIN = "Not raised again by the Conflict Agent."
NO_LONGER_PRESENT = "No longer present in"
SCOPE_RULE = "scope"
LEGITIMATE_DROPS = frozenset({"rule_duplicate", "mandatory_constraint", "not_current"})
"""Drops that are not bad output: a reply left with nothing for these reasons is not retried."""


@dataclass(frozen=True, slots=True)
class FindingSnapshot:
    """A Finding of an agent's current Assessment, as the job reads it: ids, the agent and
    Assessment version, kind, severity, title, detail and the Requirements it cites (id and
    version)."""

    finding_id: UUID
    assessment_id: UUID
    assessment_version: int
    agent: str
    position: int
    kind: str
    severity: str
    title: str = field(repr=False)
    detail: str = field(repr=False)
    requirements: tuple[tuple[UUID, int], ...] = ()


@dataclass(frozen=True, slots=True)
class FindingTitle:
    """A Finding's title and kind, shown on a semantic Conflict's position card."""

    id: UUID
    kind: str
    title: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class LabelledFinding:
    """A Finding with its prompt label `F<n>` and its cited Requirements' labels `R<n>`
    (inactive ones left out), in Requirement order."""

    label: str
    finding: FindingSnapshot
    requirement_labels: tuple[str, ...] = ()

    @property
    def first_requirement(self) -> tuple[UUID, int] | None:
        return self.finding.requirements[0] if self.finding.requirements else None


def label_findings(
    findings: Sequence[FindingSnapshot], requirement_numbers: Mapping[UUID, int]
) -> list[LabelledFinding]:
    """Label the Findings `F1…Fn` in agent order, then Finding order. Each Finding's
    Requirements are put in Requirement order (`requirement_numbers`: the active ones' `R<n>`
    numbers; inactive ones last)."""
    ordered = sorted(findings, key=lambda f: (agent_rank(f.agent), f.agent, f.position))
    labelled: list[LabelledFinding] = []
    for n, finding in enumerate(ordered, start=1):
        cited = tuple(
            sorted(
                finding.requirements,
                key=lambda r: (
                    requirement_numbers.get(r[0], math.inf),
                    str(r[0]),
                ),
            )
        )
        ordered_finding = FindingSnapshot(
            finding_id=finding.finding_id,
            assessment_id=finding.assessment_id,
            assessment_version=finding.assessment_version,
            agent=finding.agent,
            position=finding.position,
            kind=finding.kind,
            severity=finding.severity,
            title=finding.title,
            detail=finding.detail,
            requirements=cited,
        )
        labels = tuple(
            f"R{requirement_numbers[rid]}" for rid, _ in cited if rid in requirement_numbers
        )
        labelled.append(LabelledFinding(f"F{n}", ordered_finding, labels))
    return labelled


def agents_with_findings(findings: Sequence[FindingSnapshot]) -> int:
    return len({f.agent for f in findings})


@dataclass(frozen=True, slots=True)
class StanceCandidate:
    finding_label: str
    stance: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    """One Conflict as the agent proposed it, before validation."""

    type: str
    severity: str
    finding_labels: tuple[str, ...]
    summary: str = field(repr=False)
    stances: tuple[StanceCandidate, ...] = ()
    mandatory_constraint: bool = False


@dataclass(frozen=True, slots=True)
class SemanticPosition:
    finding: LabelledFinding
    stance: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class ValidSemantic:
    type: ConflictType
    severity: ConflictSeverity
    summary: str = field(repr=False)
    positions: tuple[SemanticPosition, ...] = ()
    requirement_id: UUID | None = None
    """The single Requirement every cited Finding cites, else None."""

    @property
    def finding_ids(self) -> tuple[UUID, ...]:
        return tuple(p.finding.finding.finding_id for p in self.positions)

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.type, self.finding_ids)


@dataclass(frozen=True, slots=True)
class SemanticValidation:
    conflicts: tuple[ValidSemantic, ...]
    dropped: int
    reasons: Mapping[str, int] = field(default_factory=dict)
    """Dropped candidates per reason (for logs: kinds and counts only)."""

    @property
    def retry(self) -> bool:
        """Bad output worth a retry: candidates were proposed, none survived, and none was
        dropped for a legitimate reason (`LEGITIMATE_DROPS`)."""
        return (
            not self.conflicts
            and self.dropped > 0
            and not any(r in LEGITIMATE_DROPS for r in self.reasons)
        )


def fingerprint(type_: ConflictType | str, finding_ids: Collection[UUID]) -> str:
    return f"{SEMANTIC_PREFIX}:{type_}:" + "+".join(sorted(str(i) for i in finding_ids))


def is_semantic(fingerprint_: str) -> bool:
    return fingerprint_.split(":", 1)[0] == SEMANTIC_PREFIX


def rule_key(fingerprint_: str) -> tuple[str, UUID | None] | None:
    """A rule Conflict's dedupe key (type, Requirement): `scope:<r>:…` → (scope, r); None for
    other rules (only `scope` candidates are deduped against rules)."""
    parts = fingerprint_.split(":")
    if parts[0] == SCOPE_RULE and len(parts) >= 2:
        try:
            return ConflictType.SCOPE.value, UUID(parts[1])
        except ValueError:
            return None
    return None


def requirement_of(findings: Sequence[LabelledFinding]) -> UUID | None:
    """The single Requirement every Finding cites; None when they share none or several."""
    if not findings:
        return None
    shared = {rid for rid, _ in findings[0].finding.requirements}
    for f in findings[1:]:
        shared &= {rid for rid, _ in f.finding.requirements}
    return next(iter(shared)) if len(shared) == 1 else None


def shared_requirements(findings: Sequence[LabelledFinding]) -> set[UUID]:
    """The Requirements every Finding cites."""
    if not findings:
        return set()
    shared = {rid for rid, _ in findings[0].finding.requirements}
    for f in findings[1:]:
        shared &= {rid for rid, _ in f.finding.requirements}
    return shared


def _bounded(raw: str, limit: int) -> str | None:
    trimmed = " ".join(raw.split())
    return trimmed if 0 < len(trimmed) <= limit else None


def _check(
    candidate: SemanticCandidate,
    labels: Mapping[str, LabelledFinding],
    current: Mapping[str, tuple[UUID, int]] | None,
    rule_keys: Collection[tuple[str, UUID | None]],
) -> ValidSemantic | str:
    """The valid Conflict, or the reason it is dropped."""
    try:
        type_ = ConflictType(candidate.type.strip())
    except ValueError:
        return "unknown_type"
    if type_ not in SEMANTIC_TYPES:
        return "unknown_type"
    try:
        severity = ConflictSeverity(candidate.severity.strip())
    except ValueError:
        return "unknown_severity"
    if candidate.mandatory_constraint:
        return "mandatory_constraint"
    cited: list[LabelledFinding] = []
    for raw in candidate.finding_labels:
        found = labels.get(raw.strip())
        if found is None:
            return "unknown_label"
        if found not in cited:
            cited.append(found)
    if len(cited) < 2:
        return "too_few_findings"
    if len({f.finding.agent for f in cited}) < 2:
        return "one_agent"
    if current is not None:
        for f in cited:
            now = current.get(f.finding.agent)
            if now != (f.finding.assessment_id, f.finding.assessment_version):
                return "not_current"
    summary = _bounded(candidate.summary, SUMMARY_MAX)
    if summary is None:
        return "bad_summary"
    stances: dict[str, str] = {}
    for s in candidate.stances:
        label = s.finding_label.strip()
        if label not in stances:
            stances[label] = s.stance
    positions: list[SemanticPosition] = []
    for f in cited:
        stance = _bounded(stances.get(f.label, ""), STANCE_MAX)
        if stance is None:
            return "bad_stance"
        positions.append(SemanticPosition(f, stance))
    requirement_id = requirement_of(cited)
    if type_ == ConflictType.SCOPE and any(
        (ConflictType.SCOPE.value, r) in rule_keys for r in shared_requirements(cited)
    ):
        return "rule_duplicate"
    return ValidSemantic(
        type=type_,
        severity=severity,
        summary=summary,
        positions=tuple(positions),
        requirement_id=requirement_id,
    )


def validate_semantic(
    candidates: Sequence[SemanticCandidate],
    labels: Mapping[str, LabelledFinding],
    *,
    current: Mapping[str, tuple[UUID, int]] | None = None,
    rule_keys: Collection[tuple[str, UUID | None]] = (),
) -> SemanticValidation:
    """Validate every candidate (see the module docstring); invalid ones are dropped and
    counted. `current`: each agent's current (Assessment id, version), None to skip that check
    (the eval); `rule_keys`: the dedupe keys (`rule_key`) of the Opportunity's open or
    escalated rule Conflicts."""
    kept: list[ValidSemantic] = []
    reasons: dict[str, int] = {}
    seen: set[str] = set()
    for candidate in candidates:
        outcome = _check(candidate, labels, current, rule_keys)
        if isinstance(outcome, ValidSemantic) and outcome.fingerprint in seen:
            outcome = "duplicate"
        if isinstance(outcome, str):
            reasons[outcome] = reasons.get(outcome, 0) + 1
            continue
        seen.add(outcome.fingerprint)
        kept.append(outcome)
    return SemanticValidation(tuple(kept), sum(reasons.values()), reasons)


def gone_reason(positions: Sequence[tuple[str, int]], current_versions: Mapping[str, int]) -> str:
    """The system's reason when a semantic Conflict is not raised again: the agents whose
    current Assessment is newer than the cited one ("No longer present in Engineering
    Assessment v3"), else "Not raised again by the Conflict Agent." `positions`: each cited
    (agent, Assessment version)."""
    newer: list[tuple[str, int]] = []
    for agent, version in sorted(positions, key=lambda p: agent_rank(p[0])):
        now = current_versions.get(agent)
        if now is not None and now > version:
            named = (f"{agent_role(agent)} Assessment", now)
            if named not in newer:
                newer.append(named)
    if not newer:
        return NOT_RAISED_AGAIN
    return f"{NO_LONGER_PRESENT} " + " and ".join(f"{name} v{v}" for name, v in newer)
