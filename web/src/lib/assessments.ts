// Specialist Assessments display helpers (Epic 5 slice 5A, demo scope). Safe on server and
// client.
import {
  CircleCheckIcon,
  OctagonXIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";
import { REVIEW_FAILURE_REASONS, type RunErrorCode } from "@/lib/red-team";

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

/** A task's status pill label: Queued, Running, Done, Failed. */
export const TASK_STATUS_LABELS: Record<AssessmentTask["status"], string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Done",
  failed: "Failed",
};

export function taskStatusLabel(status: AssessmentTask["status"]): string {
  return TASK_STATUS_LABELS[status] ?? status;
}

/** What a queued task's row says. */
export const WAITING_FOR_WORKER = "Waiting for the worker";

/** A duration as `m:ss` (minutes keep counting past an hour; negative reads as 0:00). */
export function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/** A task's elapsed time for the run panel, given the browser's clock: its final duration
 * once it succeeded or failed, the time since it started while it runs, and "" otherwise
 * (before it starts, or a failed task with no finish time, e.g. a lost run's). */
export function taskElapsed(
  task: Pick<AssessmentTask, "status" | "started_at" | "finished_at">,
  now: number,
): string {
  if (!task.started_at) return "";
  const started = Date.parse(task.started_at);
  if (Number.isNaN(started)) return "";
  if (task.status === "running") return formatElapsed(now - started);
  if (task.status !== "succeeded" && task.status !== "failed") return "";
  if (!task.finished_at) return "";
  const finished = Date.parse(task.finished_at);
  return Number.isNaN(finished) ? "" : formatElapsed(finished - started);
}

/** The empty-state sentence. */
export const NO_ASSESSMENT =
  "No assessment yet. Run assessment to have the Engineering, PM and Security Agents review this Opportunity.";

/** A finished run that had no active Requirements to assess. */
export const NOTHING_TO_ASSESS = "There were no active Requirements to assess.";

/** An agent without a current Assessment while others have one. */
export const NO_AGENT_ASSESSMENT = "No Assessment yet.";

/** Shown instead of the running indicator once polling has stopped (15 minutes). */
export const STILL_ASSESSING = "Still assessing — reload to check.";

export const RUN_ASSESSMENT = "Run assessment";
