// Specialist Assessments display helpers (Epic 5 slice 5A, demo scope). Safe on server and
// client.
import {
  CircleCheckIcon,
  OctagonXIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";
import {
  categoryLabel,
  REVIEW_FAILURE_REASONS,
  SEVERITIES,
  type RedTeamFinding,
  type RedTeamReview,
  type RunErrorCode,
  type Severity,
  type SeverityCounts,
} from "@/lib/red-team";

export type AssessmentsView = components["schemas"]["AssessmentsView"];
export type AgentAssessment = components["schemas"]["AgentAssessment"];
export type Assessment = components["schemas"]["AssessmentView"];
export type AssessmentFinding = components["schemas"]["AssessmentFinding"];
export type AssessmentEffort = components["schemas"]["AssessmentEffort"];
export type AssessmentRun = components["schemas"]["AssessmentRun"];
export type AssessmentTask = components["schemas"]["AssessmentTask"];
export type AssessmentAgent = components["schemas"]["AssessmentAgent"];
export type Recommendation = components["schemas"]["Recommendation"];
export type Confidence = components["schemas"]["Confidence"];
export type FindingKind = components["schemas"]["FindingKind"];

/** The specialist agents by role, in the order the tab lists them. */
export const AGENTS: readonly { value: AssessmentAgent; label: string }[] = [
  { value: "engineering_agent", label: "Engineering Agent" },
  { value: "pm_agent", label: "PM Agent" },
  { value: "security_agent", label: "Security Agent" },
];

/** An agent's role in words (its own id for one this build doesn't know). */
export function agentLabel(value: AssessmentAgent): string {
  return AGENTS.find((a) => a.value === value)?.label ?? value;
}

/** One line on what each agent assesses, shown on its run card. */
export const AGENT_ROLES: Record<AssessmentAgent, string> = {
  engineering_agent: "Feasibility, architecture and per-integration effort",
  pm_agent: "Delivery approach, phases and customer dependencies",
  security_agent: "Mandatory controls and the effort they need",
};

/** An agent's role description ("" for one this build doesn't know). */
export function agentRole(value: AssessmentAgent): string {
  return AGENT_ROLES[value] ?? "";
}

/** The recommendations, each with its label, icon and icon tone (never colour alone). */
export const RECOMMENDATIONS: readonly {
  value: Recommendation;
  label: string;
  icon: LucideIcon;
  tone: "text-resolved" | "text-gap" | "text-blocker";
}[] = [
  {
    value: "proceed",
    label: "Proceed",
    icon: CircleCheckIcon,
    tone: "text-resolved",
  },
  {
    value: "proceed_with_conditions",
    label: "Proceed with conditions",
    icon: TriangleAlertIcon,
    tone: "text-gap",
  },
  {
    value: "do_not_proceed",
    label: "Do not proceed",
    icon: OctagonXIcon,
    tone: "text-blocker",
  },
];

export function recommendationInfo(
  value: Recommendation,
): (typeof RECOMMENDATIONS)[number] {
  return (
    RECOMMENDATIONS.find((r) => r.value === value) ?? {
      value,
      label: value,
      icon: TriangleAlertIcon,
      tone: "text-gap",
    }
  );
}

/** "High confidence", "Medium confidence", "Low confidence". */
export function confidenceLabel(value: Confidence): string {
  const word = { high: "High", medium: "Medium", low: "Low" }[value] ?? value;
  return `${word} confidence`;
}

/** The Finding kinds with their labels. */
export const KINDS: readonly { value: FindingKind; label: string }[] = [
  { value: "risk", label: "Risk" },
  { value: "constraint", label: "Constraint" },
  { value: "dependency", label: "Dependency" },
  { value: "opportunity", label: "Opportunity" },
];

/** A kind's label (its own name for one this build doesn't know). */
export function kindLabel(value: FindingKind): string {
  return KINDS.find((k) => k.value === value)?.label ?? value;
}

/** "Engineering Agent v2". */
export function assessmentLabel(
  assessment: Pick<Assessment, "agent" | "version">,
): string {
  return `${agentLabel(assessment.agent)} v${assessment.version}`;
}

/** True while the run is queued or running. */
export function isAssessing(run: AssessmentRun | null | undefined): boolean {
  return run?.status === "queued" || run?.status === "running";
}

/** The latest run's status in words. */
export const RUN_STATUS_LABELS: Record<AssessmentRun["status"], string> = {
  queued: "Assessment queued",
  running: "Assessing",
  succeeded: "Assessment complete",
  partially_failed: "Assessment partly failed",
  failed: "Assessment failed",
  cancelled: "Cancelled — completed results kept",
};

export function runStatusLabel(run: AssessmentRun): string {
  return RUN_STATUS_LABELS[run.status] ?? run.status;
}

/** Why a task failed, in words (a general reason for a code this build doesn't know). */
export function failureReason(code: RunErrorCode | null | undefined): string {
  return (
    (code ? REVIEW_FAILURE_REASONS[code] : undefined) ?? "something went wrong"
  );
}

/** A task's status pill label: Queued, Running, Done, Failed, Skipped. */
export const TASK_STATUS_LABELS: Record<AssessmentTask["status"], string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
  skipped: "Skipped",
};

export function taskStatusLabel(status: AssessmentTask["status"]): string {
  return TASK_STATUS_LABELS[status] ?? status;
}

/** What a queued task's row says. */
export const WAITING_FOR_WORKER = "Waiting for the worker";

/** What a task skipped because its Agent is disabled in the Agent Registry says (Story 7.1). */
export const AGENT_DISABLED = "Agent disabled — assess manually";

/** The note on a skipped task's row: why it was skipped, when the API says (a cancel's
 * skipped tasks have no reason, and no note). */
export function skipNote(task: Pick<AssessmentTask, "status" | "skip_reason">): string | null {
  return task.status === "skipped" && task.skip_reason === "agent_disabled"
    ? AGENT_DISABLED
    : null;
}

/** A duration as `m:ss` (minutes keep counting past an hour; negative reads as 0:00). */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** A task's elapsed time for the run panel, given the browser's clock: its final duration
 * once it succeeded, failed or was skipped by a cancel, the time since it started while it
 * runs, and "" otherwise (before it starts, a task skipped before it started, or a failed
 * task with no finish time, e.g. a lost run's). */
export function taskElapsed(
  task: Pick<AssessmentTask, "status" | "started_at" | "finished_at">,
  now: number,
): string {
  if (!task.started_at) return "";
  const started = Date.parse(task.started_at);
  if (Number.isNaN(started)) return "";
  if (task.status === "running") return formatElapsed(now - started);
  if (!["succeeded", "failed", "skipped"].includes(task.status)) return "";
  if (!task.finished_at) return "";
  const finished = Date.parse(task.finished_at);
  return Number.isNaN(finished) ? "" : formatElapsed(finished - started);
}

/** The empty-state sentence. */
export const NO_ASSESSMENT =
  "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.";

/** A finished run that had no active Requirements to assess. */
export const NOTHING_TO_ASSESS = "There were no active Requirements to assess.";

/** An agent without a current Assessment while others have one. */
export const NO_AGENT_ASSESSMENT = "No Assessment yet.";

/** Shown instead of the running indicator once polling has stopped (15 minutes). */
export const STILL_ASSESSING = "Still assessing — reload to check.";

export const RUN_ASSESSMENT = "Run assessment";

/** The start button's label once a run exists. */
export const START_NEW_RUN = "Start new run";

/** The Red Team's name and role on its task and result cards. */
export const RED_TEAM_LABEL = "Red Team";
export const RED_TEAM_ROLE =
  "Argues integrations are harder and Requirements incomplete";

/** A task status (a Red Team run's status is one of these too). */
export type TaskStatus = AssessmentTask["status"];

/** The run header's counters over the given task statuses: "{done}/{total}" Complete always,
 * then Failed, Running, Queued and Skipped, each only when above zero. */
export function taskCounters(
  statuses: readonly TaskStatus[],
): { key: string; value: string; label: string }[] {
  const count = (status: TaskStatus) =>
    statuses.filter((s) => s === status).length;
  const counters = [
    {
      key: "complete",
      value: `${count("succeeded")}/${statuses.length}`,
      label: "Complete",
    },
  ];
  for (const [status, word] of [
    ["failed", "Failed"],
    ["running", "Running"],
    ["queued", "Queued"],
    ["skipped", "Skipped"],
  ] as const) {
    const n = count(status);
    if (n > 0) counters.push({ key: status, value: String(n), label: word });
  }
  return counters;
}

/** The Agent tasks heading's summary: "1 running · 2 queued" ("" when nothing is active). */
export function activitySummary(statuses: readonly TaskStatus[]): string {
  const running = statuses.filter((s) => s === "running").length;
  const queued = statuses.filter((s) => s === "queued").length;
  return [
    running > 0 ? `${running} running` : "",
    queued > 0 ? `${queued} queued` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The alert under the run header for a run that stopped early: why, and that completed
 * results are kept (null for a run that is in progress or succeeded). */
export function runAlert(
  run: Pick<AssessmentRun, "status" | "tasks">,
): { title: string; detail: string } | null {
  const kept = "Completed results are kept.";
  if (run.status === "cancelled") {
    return { title: "The run was cancelled", detail: kept };
  }
  if (run.status !== "failed" && run.status !== "partially_failed") return null;
  const reasons = run.tasks
    .filter((t) => t.status === "failed")
    .map((t) => `${agentLabel(t.agent)}: ${failureReason(t.error_code)}.`);
  return {
    title:
      run.status === "failed" ? "The run failed" : "The run partly failed",
    detail: [...reasons, kept].join(" "),
  };
}

/** One row of the Assessments tab's Findings table: a specialist agent's or the Red Team's
 * Finding. */
export type FindingRow =
  | {
      source: "specialist";
      agent: AssessmentAgent;
      finding: AssessmentFinding;
      id: string;
      severity: Severity;
      type: string;
      raisedBy: string;
      requirements: number;
      lines: null;
    }
  | {
      source: "red-team";
      finding: RedTeamFinding;
      id: string;
      severity: Severity;
      type: string;
      raisedBy: string;
      requirements: number;
      lines: number;
    };

/** A Finding row's selection key, unique across both sources ("red-team:<id>",
 * "<agent>:<id>"). */
export function findingKey(row: FindingRow): string {
  return `${row.source === "red-team" ? "red-team" : row.agent}:${row.id}`;
}

function severityRank(value: Severity): number {
  const index = SEVERITIES.findIndex((s) => s.value === value);
  return index === -1 ? SEVERITIES.length : index;
}

/** Every agent's Findings and the Red Team's in one list, ranked critical to low (a stable
 * sort: the agents in tab order, then the Red Team, each in the API's order). */
export function mergeFindings(
  assessments: readonly AgentAssessment[],
  review: Pick<RedTeamReview, "findings"> | null | undefined,
): FindingRow[] {
  const rows: FindingRow[] = [];
  for (const slot of assessments) {
    for (const finding of slot.assessment?.findings ?? []) {
      rows.push({
        source: "specialist",
        agent: slot.agent,
        finding,
        id: finding.id,
        severity: finding.severity,
        type: kindLabel(finding.kind),
        raisedBy: agentLabel(slot.agent),
        requirements: finding.requirements.length,
        lines: null,
      });
    }
  }
  for (const finding of review?.findings ?? []) {
    rows.push({
      source: "red-team",
      finding,
      id: finding.id,
      severity: finding.severity,
      type: categoryLabel(finding.category),
      raisedBy: RED_TEAM_LABEL,
      requirements: finding.requirements.length,
      lines: finding.lines.length,
    });
  }
  return rows
    .map((row, index) => ({ row, index }))
    .sort(
      (a, b) =>
        severityRank(a.row.severity) - severityRank(b.row.severity) ||
        a.index - b.index,
    )
    .map(({ row }) => row);
}

/** The rows' severity counts. */
export function severityTotals(rows: readonly FindingRow[]): SeverityCounts {
  const counts: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0 };
  for (const row of rows) {
    if (row.severity in counts) counts[row.severity] += 1;
  }
  return counts;
}

/** "1 Critical · 3 High · 2 Medium · 0 Low". */
export function severitySummary(counts: SeverityCounts): string {
  return SEVERITIES.map((s) => `${counts[s.value]} ${s.label}`).join(" · ");
}

/** Up to `max` distinct Requirement labels (one chip per label) an agent's result cites, its Findings' first,
 * then its effort rows'. */
export function evidenceLabels(
  findings: readonly { requirements: readonly { id: string; label: string }[] }[],
  effort: readonly { requirement: { id: string; label: string } }[] = [],
  max = 3,
): { id: string; label: string }[] {
  const seen = new Map<string, { id: string; label: string }>();
  const all = [
    ...findings.flatMap((f) => f.requirements),
    ...effort.map((e) => e.requirement),
  ];
  for (const requirement of all) {
    if (seen.size >= max) break;
    if (!seen.has(requirement.label))
      seen.set(requirement.label, {
        id: requirement.id,
        label: requirement.label,
      });
  }
  return Array.from(seen.values());
}

/** The run status pill's tone class (the label carries the meaning too). */
export function runStatusTone(status: AssessmentRun["status"]): string {
  switch (status) {
    case "succeeded":
      return "text-resolved";
    case "running":
      return "text-agent";
    case "partially_failed":
      return "text-gap";
    case "failed":
      return "text-blocker";
    default:
      return "text-muted-foreground";
  }
}

/** Cancelling a queued or running run (Story 5.5). */
export const CANCEL_RUN = "Cancel run";
export const CANCEL_RUN_TITLE = "Cancel this run?";
export const CANCEL_RUN_DESCRIPTION = "Completed results are kept.";
export const CANCEL_RUN_CONFIRM = "Confirm";
export const CANCEL_RUN_KEEP = "Keep running";
