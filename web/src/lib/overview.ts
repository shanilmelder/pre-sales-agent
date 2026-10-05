// Overview summary derivations (Story 1.8, demo slice). Pure and safe on server and client.
// Every number is counted from what the tabs' reads return; Estimate totals come from the
// server and are never added up here.
import { agentLabel, type AssessmentsView } from "@/lib/assessments";
import { hours, type Assumption, type EstimateView } from "@/lib/estimates";
import type { Gap, GapList } from "@/lib/gaps";
import type { RedTeamView, Severity } from "@/lib/red-team";
import { groupRequirements, type RequirementList } from "@/lib/requirements";
import type { Source } from "@/lib/sources";
import type { WorkspaceTabSlug } from "@/lib/workspace";

/** How many Needs attention rows the Overview shows before "+N more". */
export const ATTENTION_LIMIT = 8;

export const NOTHING_NEEDS_ATTENTION = "Nothing needs attention.";
export const ATTENTION_INCOMPLETE = "Some items could not be loaded, so this list may be incomplete.";
export const NO_ESTIMATE_YET = "No Estimate yet.";
export const NO_ASSESSMENT_YET = "No assessment yet.";
export const NOT_RUN = "—";

/** A card whose read failed. */
export function couldNotLoad(what: string): string {
  return `${what} could not be loaded. Try again in a moment.`;
}

export type AttentionKind = "critical-finding" | "high-finding" | "gap" | "assumption";

export type AttentionItem = {
  /** Unique within the list. */
  key: string;
  kind: AttentionKind;
  /** "Red Team: <title>", "Open Gap: <title>", "Unaccepted Assumption: <wording> — 80.0 h". */
  label: string;
  tab: WorkspaceTabSlug;
};

/** Most severe first: critical Findings, then high Findings and high-impact Gaps, then
 * unaccepted Assumptions. */
const RANK: Record<AttentionKind, number> = {
  "critical-finding": 0,
  "high-finding": 1,
  gap: 2,
  assumption: 3,
};

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
 * contributes nothing). Within a rank the order is: Red Team, then the Engineering, PM and
 * Security Agents, keeping each source's own order. Read-only; it blocks nothing. */
export function attentionItems({
  redTeam,
  assessments,
  gaps,
  estimate,
}: {
  redTeam: RedTeamView | null;
  assessments: AssessmentsView | null;
  gaps: GapList | null;
  estimate: EstimateView | null;
}): AttentionItem[] {
  const items: AttentionItem[] = [
    ...findingItems("Red Team", redTeam?.review?.findings ?? []),
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

/** A step with nothing to count yet: still running ("Extracting…") or failed. */
export type StepStatus = { status: string };

type StepRun = { status: "queued" | "running" | "succeeded" | "failed" } | null;

/** Null before the step has run; its status while the first run is queued, running or has
 * failed with nothing to show; otherwise null too (the caller counts). */
function stepStatus(run: StepRun, itemCount: number, running: string): StepStatus | null {
  if (itemCount > 0 || run === null || run.status === "succeeded") return null;
  return { status: run.status === "failed" ? "Failed" : running };
}

export type RequirementCounts = {
  active: number;
  byType: { label: string; count: number }[];
};

/** The active Requirements by type; the extraction's status while there is nothing to count
 * and it hasn't succeeded; null when no extraction has run. */
export function requirementCounts(list: RequirementList): RequirementCounts | StepStatus | null {
  if (list.extraction === null && list.items.length === 0) return null;
  const pending = stepStatus(list.extraction, list.items.length, "Extracting…");
  if (pending) return pending;
  return {
    active: list.items.length,
    byType: groupRequirements(list.items).map((g) => ({ label: g.label, count: g.items.length })),
  };
}

export type GapCounts = { open: number; high: number };

/** The open Gaps and how many are high impact; the detection's status while there is nothing
 * to count and it hasn't succeeded; null when no detection has run. */
export function gapCounts(list: GapList): GapCounts | StepStatus | null {
  if (list.detection === null && list.items.length === 0) return null;
  const pending = stepStatus(list.detection, list.items.length, "Detecting…");
  if (pending) return pending;
  const open = openGaps(list);
  return { open: open.length, high: open.filter((g) => g.impact === "high").length };
}

/** True for a step's status rather than its counts. */
export function isStepStatus(value: object): value is StepStatus {
  return "status" in value;
}

/** "3 Functional · 1 Integration". */
export function byTypeLabel(byType: RequirementCounts["byType"]): string {
  return byType.map((t) => `${t.count} ${t.label}`).join(" · ");
}

/** "3 of 4 parsed", "2 of 3 parsed, 1 failed". */
export function parsedLabel(counts: SourceCounts): string {
  const parsed = `${counts.parsed} of ${counts.total} parsed`;
  return counts.failed > 0 ? `${parsed}, ${counts.failed} failed` : parsed;
}

/** "3 items". */
export function itemCountLabel(n: number): string {
  return `${n} ${n === 1 ? "item" : "items"}`;
}

/** "2 high impact". */
export function highImpactLabel(n: number): string {
  return `${n} high impact`;
}

/** "Estimate v2". */
export function estimateTitle(version: number): string {
  return `Estimate v${version}`;
}

/** True when there is nothing yet to show on the Assessments card. */
export function noAssessmentYet(
  assessments: AssessmentsView | null,
  redTeam: RedTeamView | null,
): boolean {
  const anySpecialist =
    assessments !== null &&
    (assessments.run !== null || assessments.assessments.some((s) => s.assessment !== null));
  const anyRedTeam = redTeam !== null && (redTeam.review !== null || redTeam.run !== null);
  return !anySpecialist && !anyRedTeam;
}

/** "1 critical · 2 high". */
export function criticalHighLabel(counts: { critical: number; high: number }): string {
  return `${counts.critical} critical · ${counts.high} high`;
}
