// Overview summary derivations (Story 1.8, redesigned to the new mockups). Pure and safe on
// server and client. Every number is counted from what the tabs' reads return; Estimate
// totals come from the server and are never added up here.
import {
  agentLabel,
  decisionSentence,
  isAssessing,
  openDecisions,
  runStatusLabel,
  type Assessment,
  type AssessmentFinding,
  type AssessmentsView,
} from "@/lib/assessments";
import { isUnresolved, typeLabel, type ConflictsView } from "@/lib/conflicts";
import {
  DRAFTING,
  hours,
  isDrafting,
  type Assumption,
  type EstimateView,
  type RoleHours,
} from "@/lib/estimates";
import type { Gap, GapList } from "@/lib/gaps";
import type { RedTeamView, Severity } from "@/lib/red-team";
import { unconfirmed, type RequirementList } from "@/lib/requirements";
import type { Source } from "@/lib/sources";
import type { SubmissionBlockersView } from "@/lib/submission";
import type { TraceEvent } from "@/lib/trace";
import type { WorkspaceTabSlug } from "@/lib/workspace";

/** One read's outcome: its data, or `null` when it failed. */
export type OverviewReads = {
  sources: Source[] | null;
  requirements: RequirementList | null;
  gaps: GapList | null;
  estimate: EstimateView | null;
  assessments: AssessmentsView | null;
  redTeam: RedTeamView | null;
  trace: TraceEvent[] | null;
  /** Story 6.3: for the escalated Conflicts (left out by older callers). */
  conflicts?: ConflictsView | null;
  /** Story 8.6: the submission blockers (the API's one check), for the card when no
   * workspace provider is above (left out by older callers). */
  blockers?: SubmissionBlockersView | null;
};

/** How many Needs you rows the Overview shows before "+N more". */
export const ATTENTION_LIMIT = 8;

export const NOTHING_NEEDS_ATTENTION = "Nothing needs attention.";
export const ATTENTION_INCOMPLETE = "Some items could not be loaded, so this list may be incomplete.";
export const NO_ESTIMATE_YET = "No Estimate yet.";
export const NOT_RUN = "—";

/** A card whose read failed. */
export function couldNotLoad(what: string): string {
  return `${what} could not be loaded. Try again in a moment.`;
}

// --- Needs you -------------------------------------------------------------------------------

export type AttentionKind =
  | "critical-finding"
  | "escalated-conflict"
  | "waiting-run"
  | "high-finding"
  | "gap"
  | "assumption";

export type AttentionItem = {
  /** Unique within the list. */
  key: string;
  kind: AttentionKind;
  /** "Red Team: <title>", "Open Gap: <title>", "Unaccepted Assumption: <wording> — 80.0 h",
   * "Effort Conflict on R2 escalated to Sam". */
  label: string;
  tab: WorkspaceTabSlug;
};

/** Most severe first: critical Findings, then escalated Conflicts (Story 6.3), a run waiting
 * for a decision (Story 5.5), high Findings and high-impact Gaps, then unaccepted
 * Assumptions. */
const RANK: Record<AttentionKind, number> = {
  "critical-finding": 0,
  "escalated-conflict": 1,
  "waiting-run": 1,
  "high-finding": 1,
  gap: 2,
  assumption: 3,
};

/** The escalated Conflicts, naming the reviewer: "Effort Conflict on R2 escalated to Sam". */
export function escalatedConflictItems(conflicts: ConflictsView | null | undefined): AttentionItem[] {
  return (conflicts?.conflicts ?? [])
    .filter((c) => c.status === "escalated" && c.escalated_to !== null)
    .map((c) => ({
      key: `conflict:${c.id}`,
      kind: "escalated-conflict",
      label: `${typeLabel(c.type)} Conflict${c.requirement ? ` on ${c.requirement.label}` : ""} escalated to ${c.escalated_to!.name}`,
      tab: "conflicts",
    }));
}

/** The latest run's open decisions (Story 5.5): "Security assessment not planned: Security
 * Agent is disabled", resolved in the Assessments tab. */
export function waitingRunItems(assessments: AssessmentsView | null | undefined): AttentionItem[] {
  const run = assessments?.run;
  if (run?.status !== "waiting_for_human") return [];
  return openDecisions(run).map((d) => ({
    key: `decision:${d.id}`,
    kind: "waiting-run",
    label: decisionSentence(d),
    tab: "assessments",
  }));
}

type Sourced = { severity: Severity; title: string; id: string };

function findingItems(source: string, findings: readonly Sourced[]): AttentionItem[] {
  return findings
    .filter((f) => f.severity === "critical" || f.severity === "high")
    .map((f) => ({
      key: `finding:${f.id}`,
      kind: f.severity === "critical" ? "critical-finding" : "high-finding",
      label: `${source}: ${f.title}`,
      tab: "assessments",
    }));
}

/** The proposed Assumptions of the current version that nobody has accepted yet. */
export function unacceptedAssumptions(estimate: EstimateView | null | undefined): Assumption[] {
  const groups = estimate?.version?.assumptions;
  if (!groups) return [];
  return [...groups.conditions, ...groups.contingencies].filter((a) => a.accepted_at === null);
}

/** The open Gaps (the list may also carry converted or superseded ones). */
export function openGaps(list: GapList | null | undefined): Gap[] {
  return (list?.items ?? []).filter((g) => g.status === "open");
}

/** Everything that needs attention, most severe first (a read that failed is `null` and
 * contributes nothing). Within a rank the order is: Red Team, escalated Conflicts, a waiting
 * run's decisions, then the
 * Engineering, PM and Security Agents, keeping each source's own order. Read-only; it blocks nothing. */
export function attentionItems({
  redTeam,
  assessments,
  gaps,
  estimate,
  conflicts = null,
}: Pick<OverviewReads, "redTeam" | "assessments" | "gaps" | "estimate" | "conflicts">): AttentionItem[] {
  const items: AttentionItem[] = [
    ...findingItems("Red Team", redTeam?.review?.findings ?? []),
    ...escalatedConflictItems(conflicts),
    ...waitingRunItems(assessments),
    ...(assessments?.assessments ?? []).flatMap((slot) =>
      findingItems(agentLabel(slot.agent), slot.assessment?.findings ?? []),
    ),
    ...openGaps(gaps)
      .filter((g) => g.impact === "high")
      .map<AttentionItem>((g) => ({
        key: `gap:${g.id}`,
        kind: "gap",
        label: `Open Gap: ${g.title}`,
        tab: "gaps",
      })),
    ...unacceptedAssumptions(estimate).map<AttentionItem>((a) => ({
      key: `assumption:${a.id}`,
      kind: "assumption",
      label:
        a.amount_hours === null
          ? `Unaccepted Assumption: ${a.wording}`
          : `Unaccepted Assumption: ${a.wording} — ${hours(a.amount_hours)} h`,
      tab: "estimate",
    })),
  ];
  // Array.prototype.sort is stable: equal ranks keep the order built above.
  return items.sort((a, b) => RANK[a.kind] - RANK[b.kind]);
}

/** True when a read the Needs you list draws on failed, so it may be incomplete. */
export function attentionIncomplete(data: OverviewReads): boolean {
  return (
    data.redTeam === null ||
    data.assessments === null ||
    data.gaps === null ||
    data.estimate === null ||
    data.conflicts === null
  );
}

/** The first `limit` items and, when some are cut, how many and the tab "+N more" links to:
 * only when every cut item lives on that one tab (otherwise `null`, plain text). */
export function cutAttention(
  items: readonly AttentionItem[],
  limit: number = ATTENTION_LIMIT,
): { shown: AttentionItem[]; more: number; moreTab: WorkspaceTabSlug | null } {
  const shown = items.slice(0, limit);
  const rest = items.slice(limit);
  const tab = rest[0]?.tab ?? null;
  return { shown, more: rest.length, moreTab: rest.every((i) => i.tab === tab) ? tab : null };
}

/** "+4 more". */
export function moreLabel(n: number): string {
  return `+${n} more`;
}

/** "3 items". */
export function itemCountLabel(n: number): string {
  return `${n} ${n === 1 ? "item" : "items"}`;
}

// --- Counts ----------------------------------------------------------------------------------

export type SourceCounts = { parsed: number; failed: number; total: number };

/** Sources parsed (and failed) of total, or null when there are none yet. */
export function sourceCounts(sources: readonly Source[]): SourceCounts | null {
  if (sources.length === 0) return null;
  return {
    parsed: sources.filter((s) => s.parse?.status === "parsed").length,
    failed: sources.filter((s) => s.parse?.status === "failed").length,
    total: sources.length,
  };
}

/** "3 of 4 parsed", "2 of 3 parsed, 1 failed". */
export function parsedLabel(counts: SourceCounts): string {
  const parsed = `${counts.parsed} of ${counts.total} parsed`;
  return counts.failed > 0 ? `${parsed}, ${counts.failed} failed` : parsed;
}

/** A step with nothing to count yet: still running ("Extracting…") or failed. */
export type StepStatus = { status: string };

type StepRun = { status: "queued" | "running" | "succeeded" | "failed" } | null;

/** Null before the step has run; its status while the first run is queued, running or has
 * failed with nothing to show; otherwise null too (the caller counts). */
function stepStatus(run: StepRun, itemCount: number, running: string): StepStatus | null {
  if (itemCount > 0 || run === null || run.status === "succeeded") return null;
  return { status: run.status === "failed" ? "Failed" : running };
}

/** True for a step's status rather than its counts. */
export function isStepStatus(value: object): value is StepStatus {
  return "status" in value;
}

/** The active Requirements and how many are confirmed. */
export type RequirementCounts = { active: number; confirmed: number; unconfirmed: number };

/** The active Requirements and how many are confirmed; the extraction's status while there is
 * nothing to count and it hasn't succeeded; null when no extraction has run. */
export function requirementCounts(list: RequirementList): RequirementCounts | StepStatus | null {
  if (list.extraction === null && list.items.length === 0) return null;
  const pending = stepStatus(list.extraction, list.items.length, "Extracting…");
  if (pending) return pending;
  const waiting = unconfirmed(list.items).length;
  return { active: list.items.length, confirmed: list.items.length - waiting, unconfirmed: waiting };
}

/** "3 awaiting confirmation". */
export function awaitingLabel(n: number): string {
  return `${n} awaiting confirmation`;
}

/** The open Gaps by impact. */
export type GapCounts = { open: number; high: number; medium: number; low: number };

/** The open Gaps by impact; the detection's status while there is nothing to count and it
 * hasn't succeeded; null when no detection has run. */
export function gapCounts(list: GapList): GapCounts | StepStatus | null {
  if (list.detection === null && list.items.length === 0) return null;
  const pending = stepStatus(list.detection, list.items.length, "Detecting…");
  if (pending) return pending;
  const open = openGaps(list);
  const count = (impact: Gap["impact"]) => open.filter((g) => g.impact === impact).length;
  return { open: open.length, high: count("high"), medium: count("medium"), low: count("low") };
}

/** "2 High, 1 Medium, 0 Low". */
export function impactLabel(counts: Pick<GapCounts, "high" | "medium" | "low">): string {
  return `${counts.high} High, ${counts.medium} Medium, ${counts.low} Low`;
}

/** The Conflicts not yet resolved, and how many of them are escalated. */
export function conflictCounts(conflicts: ConflictsView): { unresolved: number; escalated: number } {
  const open = conflicts.conflicts.filter(isUnresolved);
  return { unresolved: open.length, escalated: open.filter((c) => c.status === "escalated").length };
}

/** True once an Assessment run or an Assessment exists. */
export function assessmentsStarted(assessments: AssessmentsView | null): boolean {
  return (
    assessments !== null &&
    (assessments.run !== null || assessments.assessments.some((s) => s.assessment !== null))
  );
}

/** "Engineer 225.4 h · PM 52.6 h", plus " · QA 8.0 h" when QA has hours. */
export function roleHoursLabel(roles: RoleHours): string {
  const parts = [`Engineer ${hours(roles.engineer)} h`, `PM ${hours(roles.project_manager)} h`];
  if (roles.qa > 0) parts.push(`QA ${hours(roles.qa)} h`);
  return parts.join(" · ");
}

/** "From Assessments run 2". */
export function sourceRunLabel(run: number): string {
  return `From Assessments run ${run}`;
}

/** "Estimate · v3", or "Estimate" before there is one. */
export function estimateKpiLabel(version: number | null): string {
  return version === null ? "Estimate" : `Estimate · v${version}`;
}

/** The Estimate's status before a version exists: drafting, or none yet. */
export function estimatePending(estimate: EstimateView): string {
  return isDrafting(estimate.draft) ? DRAFTING : NO_ESTIMATE_YET;
}

// --- Submission pipeline ---------------------------------------------------------------------

export type PipelineState = "complete" | "in-progress" | "blocked" | "not-started" | "unknown";

export type PipelineStep = {
  key: string;
  title: string;
  sub: string;
  state: PipelineState;
};

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

function sourcesStep(sources: Source[] | null): Omit<PipelineStep, "key" | "title"> {
  if (sources === null) return { sub: couldNotLoad("Sources"), state: "unknown" };
  const counts = sourceCounts(sources);
  if (counts === null) return { sub: "No Sources yet", state: "not-started" };
  const state: PipelineState =
    counts.failed > 0 ? "blocked" : counts.parsed < counts.total ? "in-progress" : "complete";
  return { sub: parsedLabel(counts), state };
}

function extractedStep(list: RequirementList | null): Omit<PipelineStep, "key" | "title"> {
  if (list === null) return { sub: couldNotLoad("Requirements"), state: "unknown" };
  const counts = requirementCounts(list);
  if (counts === null) return { sub: "Not extracted yet", state: "not-started" };
  if (isStepStatus(counts))
    return { sub: counts.status, state: counts.status === "Failed" ? "blocked" : "in-progress" };
  const running = list.extraction?.status === "queued" || list.extraction?.status === "running";
  return { sub: plural(counts.active, "Requirement"), state: running ? "in-progress" : "complete" };
}

function confirmedStep(list: RequirementList | null): Omit<PipelineStep, "key" | "title"> {
  if (list === null) return { sub: couldNotLoad("Requirements"), state: "unknown" };
  const counts = requirementCounts(list);
  if (counts === null || isStepStatus(counts) || counts.active === 0)
    return { sub: "Nothing to confirm yet", state: "not-started" };
  const sub = `${counts.confirmed} of ${counts.active}`;
  if (counts.unconfirmed === 0) return { sub, state: "complete" };
  return { sub, state: counts.confirmed > 0 ? "in-progress" : "not-started" };
}

function gapsStep(list: GapList | null): Omit<PipelineStep, "key" | "title"> {
  if (list === null) return { sub: couldNotLoad("Open Gaps"), state: "unknown" };
  const counts = gapCounts(list);
  if (counts === null) return { sub: "Gaps not detected yet", state: "not-started" };
  if (isStepStatus(counts))
    return { sub: counts.status, state: counts.status === "Failed" ? "blocked" : "in-progress" };
  if (counts.open === 0) return { sub: "No open Gaps", state: "complete" };
  return { sub: `${counts.open} open, ${counts.high} High`, state: "blocked" };
}

function assessmentsStep(view: AssessmentsView | null): Omit<PipelineStep, "key" | "title"> {
  if (view === null) return { sub: couldNotLoad("The Assessments"), state: "unknown" };
  const run = view.run;
  if (run === null) {
    const done = view.assessments.filter((s) => s.assessment !== null).length;
    return done > 0
      ? { sub: plural(done, "Assessment"), state: "complete" }
      : { sub: "Not run yet", state: "not-started" };
  }
  const sub = runStatusLabel(run);
  if (run.status === "succeeded") return { sub, state: "complete" };
  if (run.status === "queued" || run.status === "running") return { sub, state: "in-progress" };
  // Failed, cancelled, or waiting for a person's decision (Story 5.5): someone has to act.
  return { sub, state: "blocked" };
}

function conflictsStep(
  conflicts: ConflictsView | null | undefined,
  assessments: AssessmentsView | null,
): Omit<PipelineStep, "key" | "title"> {
  if (!conflicts) return { sub: couldNotLoad("The Conflicts"), state: "unknown" };
  const { unresolved, escalated } = conflictCounts(conflicts);
  if (unresolved > 0)
    return {
      sub: escalated > 0 ? `${unresolved} open, ${escalated} escalated` : `${unresolved} open`,
      state: "blocked",
    };
  if (conflicts.conflicts.length === 0 && !assessmentsStarted(assessments))
    return { sub: "Appear after the Assessments", state: "not-started" };
  if (conflicts.conflicts.length === 0 && isAssessing(assessments?.run))
    return { sub: "Waiting for the Assessments", state: "in-progress" };
  return { sub: "No open Conflicts", state: "complete" };
}

function estimateStep(estimate: EstimateView | null): Omit<PipelineStep, "key" | "title"> {
  if (estimate === null) return { sub: couldNotLoad("The Estimate"), state: "unknown" };
  const version = estimate.version;
  if (version === null) {
    if (isDrafting(estimate.draft)) return { sub: DRAFTING, state: "in-progress" };
    if (estimate.draft?.status === "failed") return { sub: "Drafting failed", state: "blocked" };
    return { sub: NO_ESTIMATE_YET, state: "not-started" };
  }
  const waiting = version.counts.not_accepted;
  if (waiting > 0)
    return { sub: `${plural(waiting, "Assumption")} not accepted`, state: "blocked" };
  if (version.uncovered_count > 0)
    return {
      sub: `${plural(version.uncovered_count, "Requirement")} not covered`,
      state: "blocked",
    };
  return { sub: `Estimate v${version.version}, every Assumption accepted`, state: "complete" };
}

/** The seven submission steps, each with a sub-line and a state, from the reads alone. */
export function pipelineSteps(data: OverviewReads): PipelineStep[] {
  return [
    { key: "sources", title: "Sources added", ...sourcesStep(data.sources) },
    { key: "extracted", title: "Requirements extracted", ...extractedStep(data.requirements) },
    { key: "confirmed", title: "Requirements confirmed", ...confirmedStep(data.requirements) },
    { key: "gaps", title: "Gaps answered", ...gapsStep(data.gaps) },
    { key: "assessments", title: "Assessments run", ...assessmentsStep(data.assessments) },
    {
      key: "conflicts",
      title: "Conflicts resolved",
      ...conflictsStep(data.conflicts, data.assessments),
    },
    { key: "estimate", title: "Estimate accepted", ...estimateStep(data.estimate) },
  ];
}

/** How many steps are complete, in progress and blocked, of all. */
export function pipelineProgress(steps: readonly PipelineStep[]): {
  done: number;
  inProgress: number;
  blocked: number;
  total: number;
} {
  const count = (state: PipelineState) => steps.filter((s) => s.state === state).length;
  return {
    done: count("complete"),
    inProgress: count("in-progress"),
    blocked: count("blocked"),
    total: steps.length,
  };
}

/** "Proposal due in 11 days", "Proposal due today", "Overdue by 3 days"; `null` for a bad date. */
export function dueLabel(days: number): { text: string; overdue: boolean } | null {
  if (Number.isNaN(days)) return null;
  if (days < 0) return { text: `Overdue by ${plural(-days, "day")}`, overdue: true };
  if (days === 0) return { text: "Proposal due today", overdue: false };
  return { text: `Proposal due in ${plural(days, "day")}`, overdue: false };
}

// --- Submission blockers ---------------------------------------------------------------------
// Story 8.6: the Submission blockers card reads the API's one check (`lib/submission.ts`);
// nothing here derives a blocker.

// --- Latest agent decision -------------------------------------------------------------------

const SEVERITY_RANK: Record<Severity, number> ={ critical: 0, high: 1, medium: 2, low: 3 };

/** The newest specialist Assessment and its most severe Finding (`null` when it has none);
 * `null` when there is no Assessment. */
export function latestDecision(
  assessments: AssessmentsView | null,
): { assessment: Assessment; finding: AssessmentFinding | null } | null {
  const all = (assessments?.assessments ?? [])
    .map((s) => s.assessment)
    .filter((a): a is Assessment => a !== null);
  if (all.length === 0) return null;
  const newest = all.reduce((a, b) => (Date.parse(b.created_at) > Date.parse(a.created_at) ? b : a));
  const finding =
    [...newest.findings].sort(
      (a, b) =>
        (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9) ||
        a.position - b.position,
    )[0] ?? null;
  return { assessment: newest, finding };
}

// --- Recent activity -------------------------------------------------------------------------

/** "Sam Delivery" -> "SD", "Red Team Agent" -> "RA", "system" -> "S"; "?" for an empty name. */
export function actorInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  const first = Array.from(words[0])[0] ?? "";
  const last = words.length > 1 ? (Array.from(words[words.length - 1])[0] ?? "") : "";
  return (first + last).toUpperCase();
}

// --- Agent run -------------------------------------------------------------------------------

/** "2 of 3 tasks complete". */
export function tasksCompleteLabel(done: number, total: number): string {
  return `${done} of ${total} ${total === 1 ? "task" : "tasks"} complete`;
}
