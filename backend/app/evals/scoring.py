"""Deterministic scoring of one eval run against the annotations (Story 7.6). Pure: the
harness collects what the job chain stored (`OpportunityOutput`) and this module counts.

Matching (see `evals/README.md`):

- An extracted Requirement matches an annotated one when one of its evidence passages
  overlaps the annotated quote's span in the same parsed Source.
- A detected Gap matches an annotated Gap (or an irrelevant-Gap label) when any keyword
  appears as whole words, ignoring case, in its title or why-it-matters.
- A Finding→Requirement pair is judged when an Evidence judgement names the annotated
  Requirement its cited Requirement matches and one of the judgement's keywords appears in
  the Finding's title or detail. Unjudged pairs are pending: never counted as passes.

Overall values are micro-averages (summed numerators over summed denominators) in percent,
null when nothing was measured. A failed stage scores that Opportunity's later metrics 0:
its numerators are zeroed and, where its denominator was empty, set to one (for irrelevant
Gaps, one irrelevant Gap out of one).
"""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.evals.annotations import Annotations, find_spans
from app.modules.registry.application.public import EVIDENCE_AGENTS, SPECIALIST_AGENTS, Metric

STAGES = ("parse", "extraction", "gap_detection", "specialists", "estimate", "red_team", "critic")
"""In scoring order. The Critic (Story 6.4) runs in the assessment run, before the Estimate,
but no metric depends on it, so its failure zeroes nothing: it is listed last."""
_STAGE_ORDER = {stage: i for i, stage in enumerate(STAGES)}
EXTRACTION_AGENT = "intake_agent"
GAP_AGENT = "clarification_agent"
RED_TEAM_AGENT = "red_team_agent"
INTEGRATION_CATEGORY = "integration_harder"
SPECIALIST_RISK_KIND = "risk"


# --- what the job chain stored ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Span:
    source: str
    """The Source's filename."""
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ExtractedRequirement:
    id: str
    text: str
    spans: tuple[Span, ...]


@dataclass(frozen=True, slots=True)
class DetectedGap:
    id: str
    title: str
    why_it_matters: str


@dataclass(frozen=True, slots=True)
class Finding:
    id: str
    agent_id: str
    kind: str
    """A specialist Finding's kind (`risk`, …) or a Red Team Finding's category."""
    title: str
    detail: str
    requirement_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StageFailure:
    stage: str
    code: str


@dataclass(frozen=True, slots=True)
class CriticSummary:
    """The Opportunity's current Critic Review (Story 6.4): its version and Findings per
    severity. Reported, no bar."""

    version: int
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0

    @property
    def finding_count(self) -> int:
        return self.critical + self.high + self.medium + self.low


@dataclass(frozen=True, slots=True)
class OpportunityOutput:
    slug: str
    source_texts: Mapping[str, str]
    """Filename → parsed text."""
    requirements: Sequence[ExtractedRequirement]
    valid_citations: int
    dropped_citations: int
    gaps: Sequence[DetectedGap]
    findings: Sequence[Finding]
    failures: Sequence[StageFailure] = ()
    critic: CriticSummary | None = None


# --- counts ----------------------------------------------------------------------------------


@dataclass(slots=True)
class Ratio:
    hit: int = 0
    total: int = 0

    def add(self, other: "Ratio") -> None:
        self.hit += other.hit
        self.total += other.total

    def percent(self) -> float | None:
        return None if self.total == 0 else round(100 * self.hit / self.total, 1)

    def zeroed(self) -> "Ratio":
        """The worst score: nothing hit, at least one counted."""
        return Ratio(0, max(self.total, 1))


@dataclass(frozen=True, slots=True)
class PendingPair:
    slug: str
    agent_id: str
    finding_id: str
    finding_title: str
    requirement_id: str
    requirement_text: str
    annotated_requirements: tuple[str, ...]


@dataclass(slots=True)
class OpportunityScore:
    slug: str
    extraction_recall: Ratio = field(default_factory=Ratio)
    citation_validity: Ratio = field(default_factory=Ratio)
    gap_recall: Ratio = field(default_factory=Ratio)
    irrelevant_gaps: Ratio = field(default_factory=Ratio)
    mandatory_gap_recall: Ratio = field(default_factory=Ratio)
    integration_risk_recall: Ratio = field(default_factory=Ratio)
    evidence: dict[str, Ratio] = field(default_factory=dict)
    pending: list[PendingPair] = field(default_factory=list)
    missed_requirements: list[str] = field(default_factory=list)
    missed_gaps: list[str] = field(default_factory=list)
    failures: list[StageFailure] = field(default_factory=list)
    critic: CriticSummary | None = None

    def metrics(self) -> dict[str, float | None]:
        evidence = Ratio()
        for ratio in self.evidence.values():
            evidence.add(ratio)
        return {
            Metric.EXTRACTION_RECALL.value: self.extraction_recall.percent(),
            Metric.CITATION_VALIDITY.value: self.citation_validity.percent(),
            Metric.GAP_RECALL.value: self.gap_recall.percent(),
            Metric.IRRELEVANT_GAPS.value: self.irrelevant_gaps.percent(),
            Metric.MANDATORY_GAP_RECALL.value: self.mandatory_gap_recall.percent(),
            Metric.EVIDENCE_SUPPORT.value: evidence.percent(),
            Metric.INTEGRATION_RISK_RECALL.value: self.integration_risk_recall.percent(),
        }


def _overlaps(a: tuple[int, int], b: Span) -> bool:
    return a[0] < b.end and b.start < a[1]


def _hits(keywords: Iterable[str], *texts: str) -> bool:
    """Any keyword appears as whole words, ignoring case ("line" does not hit "timeline")."""
    haystack = " ".join(texts)
    return any(
        re.search(rf"(?<!\w){re.escape(k)}(?!\w)", haystack, flags=re.IGNORECASE) for k in keywords
    )


def match_requirements(annotations: Annotations, output: OpportunityOutput) -> dict[str, set[str]]:
    """Extracted Requirement id → the annotated Requirement ids it matches."""
    spans: dict[str, tuple[str, list[tuple[int, int]]]] = {}
    for req in annotations.requirements:
        text = output.source_texts.get(req.source)
        found = [] if text is None else find_spans(text, req.quote)
        if found:
            spans[req.id] = (req.source, found)
    matched: dict[str, set[str]] = defaultdict(set)
    for extracted in output.requirements:
        for annotated_id, (source, occurrences) in spans.items():
            if any(
                s.source == source and _overlaps(span, s)
                for s in extracted.spans
                for span in occurrences
            ):
                matched[extracted.id].add(annotated_id)
    return dict(matched)


def _failed_from(failures: Sequence[StageFailure]) -> int:
    """The index of the earliest failed stage, past the last stage when none failed."""
    return min((_STAGE_ORDER.get(f.stage, 0) for f in failures), default=len(STAGES))


def score_opportunity(annotations: Annotations, output: OpportunityOutput) -> OpportunityScore:
    score = OpportunityScore(
        slug=annotations.slug, failures=list(output.failures), critic=output.critic
    )
    matches = match_requirements(annotations, output)
    found = set().union(*matches.values()) if matches else set()

    # FR-5: extraction.
    score.extraction_recall = Ratio(
        sum(1 for r in annotations.requirements if r.id in found), len(annotations.requirements)
    )
    score.missed_requirements = [r.id for r in annotations.requirements if r.id not in found]
    score.citation_validity = Ratio(
        output.valid_citations, output.valid_citations + output.dropped_citations
    )

    # FR-11: Gaps.
    text = [(g.title, g.why_it_matters) for g in output.gaps]
    matched_gaps = [g for g in annotations.gaps if any(_hits(g.keywords, *t) for t in text)]
    score.gap_recall = Ratio(len(matched_gaps), len(annotations.gaps))
    score.missed_gaps = [g.id for g in annotations.gaps if g not in matched_gaps]
    mandatory = [g for g in annotations.gaps if g.mandatory]
    score.mandatory_gap_recall = Ratio(
        sum(1 for g in mandatory if g in matched_gaps), len(mandatory)
    )
    irrelevant = sum(
        1 for t in text if any(_hits(label.keywords, *t) for label in annotations.irrelevant_gaps)
    )
    score.irrelevant_gaps = Ratio(irrelevant, len(output.gaps))

    # FR-25: Evidence support, per Agent.
    texts = {r.id: r.text for r in output.requirements}
    for agent in EVIDENCE_AGENTS:
        score.evidence[agent] = Ratio()
    for finding in output.findings:
        ratio = score.evidence.setdefault(finding.agent_id, Ratio())
        for requirement_id in finding.requirement_ids:
            annotated = matches.get(requirement_id, set())
            judgement = next(
                (
                    j
                    for j in annotations.evidence
                    if j.requirement in annotated
                    and _hits(j.finding_keywords, finding.title, finding.detail)
                ),
                None,
            )
            if judgement is None:
                score.pending.append(
                    PendingPair(
                        slug=annotations.slug,
                        agent_id=finding.agent_id,
                        finding_id=finding.id,
                        finding_title=finding.title,
                        requirement_id=requirement_id,
                        requirement_text=texts.get(requirement_id, ""),
                        annotated_requirements=tuple(sorted(annotated)),
                    )
                )
                continue
            ratio.total += 1
            ratio.hit += int(judgement.supported)

    # Integration risks (reported for Story 7.7).
    risks = [
        f
        for f in output.findings
        if (f.agent_id == RED_TEAM_AGENT and f.kind == INTEGRATION_CATEGORY)
        or (f.agent_id in SPECIALIST_AGENTS and f.kind == SPECIALIST_RISK_KIND)
    ]
    score.integration_risk_recall = Ratio(
        sum(
            1
            for risk in annotations.integration_risks
            if any(_hits(risk.keywords, f.title, f.detail) for f in risks)
        ),
        len(annotations.integration_risks),
    )
    _apply_failures(score, _failed_from(output.failures))
    return score


def _apply_failures(score: OpportunityScore, failed_from: int) -> None:
    """Score every metric of the failed stage and the stages after it 0."""
    if failed_from <= _STAGE_ORDER["extraction"]:
        score.extraction_recall = score.extraction_recall.zeroed()
        score.citation_validity = score.citation_validity.zeroed()
    if failed_from <= _STAGE_ORDER["gap_detection"]:
        score.gap_recall = score.gap_recall.zeroed()
        score.mandatory_gap_recall = score.mandatory_gap_recall.zeroed()
        worst = max(score.irrelevant_gaps.total, 1)
        score.irrelevant_gaps = Ratio(worst, worst)
    if failed_from <= _STAGE_ORDER["specialists"]:
        for agent in SPECIALIST_AGENTS:
            score.evidence[agent] = score.evidence.get(agent, Ratio()).zeroed()
        score.integration_risk_recall = score.integration_risk_recall.zeroed()
    if failed_from <= _STAGE_ORDER["red_team"]:
        score.evidence[RED_TEAM_AGENT] = score.evidence.get(RED_TEAM_AGENT, Ratio()).zeroed()


# --- the whole set ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ModelCallStats:
    """`platform_model_calls` of one Agent in the eval database."""

    agent_id: str
    calls: int
    invalid_output: int
    tokens: int
    latency_ms: int
    digests: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Cost:
    gpu_seconds: float
    tokens: int
    amount_minor: int
    currency: str


def cost(
    calls: Iterable[ModelCallStats],
    *,
    per_gpu_second_minor: int,
    per_1k_tokens_minor: int,
    currency: str,
) -> Cost:
    """GPU seconds are the summed model-call wall time (a proxy until Story 7.5); cost is
    `gpu_s * rate + tokens / 1000 * rate`, rounded to whole minor units."""
    stats = list(calls)
    gpu_seconds = round(sum(s.latency_ms for s in stats) / 1000, 3)
    tokens = sum(s.tokens for s in stats)
    amount = round(gpu_seconds * per_gpu_second_minor + tokens / 1000 * per_1k_tokens_minor)
    return Cost(gpu_seconds=gpu_seconds, tokens=tokens, amount_minor=amount, currency=currency)


def schema_valid_rate(stats: ModelCallStats) -> float | None:
    if stats.calls == 0:
        return None
    return round(100 * (stats.calls - stats.invalid_output) / stats.calls, 1)


@dataclass(frozen=True, slots=True)
class SetScores:
    overall: dict[str, float | None]
    per_agent: dict[str, dict[str, float | None]]
    opportunities: list[OpportunityScore]
    pending: list[PendingPair]


def aggregate(scores: Sequence[OpportunityScore], calls: Iterable[ModelCallStats]) -> SetScores:
    """Overall and per-Agent values across the reference set."""
    totals: dict[str, Ratio] = defaultdict(Ratio)
    evidence: dict[str, Ratio] = defaultdict(Ratio)
    for score in scores:
        totals["extraction_recall"].add(score.extraction_recall)
        totals["citation_validity"].add(score.citation_validity)
        totals["gap_recall"].add(score.gap_recall)
        totals["irrelevant_gaps"].add(score.irrelevant_gaps)
        totals["mandatory_gap_recall"].add(score.mandatory_gap_recall)
        totals["integration_risk_recall"].add(score.integration_risk_recall)
        for agent, ratio in score.evidence.items():
            evidence[agent].add(ratio)
            totals["evidence_support"].add(ratio)
    stats = {s.agent_id: s for s in calls}
    all_calls = sum(s.calls for s in stats.values())
    invalid = sum(s.invalid_output for s in stats.values())
    overall: dict[str, float | None] = {m.value: totals[m.value].percent() for m in Metric}
    overall[Metric.SCHEMA_VALID_RATE.value] = Ratio(all_calls - invalid, all_calls).percent()

    per_agent: dict[str, dict[str, float | None]] = defaultdict(dict)
    per_agent[EXTRACTION_AGENT] = {
        "extraction_recall": overall["extraction_recall"],
        "citation_validity": overall["citation_validity"],
    }
    per_agent[GAP_AGENT] = {
        "gap_recall": overall["gap_recall"],
        "irrelevant_gaps": overall["irrelevant_gaps"],
        "mandatory_gap_recall": overall["mandatory_gap_recall"],
    }
    for agent in EVIDENCE_AGENTS:
        per_agent[agent]["evidence_support"] = evidence[agent].percent()
    for agent_id, stat in stats.items():
        per_agent[agent_id]["schema_valid_rate"] = schema_valid_rate(stat)
    pending = [p for s in scores for p in s.pending]
    return SetScores(
        overall=overall,
        per_agent={k: dict(v) for k, v in sorted(per_agent.items())},
        opportunities=list(scores),
        pending=pending,
    )
