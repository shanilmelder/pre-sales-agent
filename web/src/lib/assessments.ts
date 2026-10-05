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

/** A task's line in the header: "Engineering Agent — Assessing…", "PM Agent — Done",
 * "Security Agent — Failed: <reason>". */
export function taskLine(task: AssessmentTask): string {
  const name = agentLabel(task.agent);
  switch (task.status) {
    case "succeeded":
      return `${name} — Done`;
    case "failed":
      return `${name} — Failed: ${failureReason(task.error_code)}`;
    default:
      return `${name} — Assessing…`;
  }
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
