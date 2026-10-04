// Red Team display helpers (Story 6.5, demo scope). Safe on server and client.
import {
  CircleAlertIcon,
  InfoIcon,
  OctagonAlertIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";

export type RedTeamView = components["schemas"]["RedTeamView"];
export type RedTeamReview = components["schemas"]["RedTeamReviewView"];
export type RedTeamFinding = components["schemas"]["RedTeamFinding"];
export type RedTeamRun = components["schemas"]["RedTeamRun"];
export type RunErrorCode = components["schemas"]["RunErrorCode"];
export type FindingCategory = components["schemas"]["FindingCategory"];
export type Severity = components["schemas"]["Severity"];
export type SeverityCounts = components["schemas"]["SeverityCounts"];

/** The severities most severe first, each with its label, icon and icon tone. Blocker red is
 * only for `critical`, gap amber only for `high` (the pill always shows icon and label). */
export const SEVERITIES: readonly {
  value: Severity;
  label: string;
  icon: LucideIcon;
  tone: "text-blocker" | "text-gap" | "text-muted-foreground";
}[] = [
  { value: "critical", label: "Critical", icon: OctagonAlertIcon, tone: "text-blocker" },
  { value: "high", label: "High", icon: TriangleAlertIcon, tone: "text-gap" },
  { value: "medium", label: "Medium", icon: CircleAlertIcon, tone: "text-muted-foreground" },
  { value: "low", label: "Low", icon: InfoIcon, tone: "text-muted-foreground" },
];

/** A severity's display (a neutral "info" one for a severity this build doesn't know). */
export function severityInfo(value: Severity): (typeof SEVERITIES)[number] {
  return (
    SEVERITIES.find((s) => s.value === value) ?? {
      value,
      label: value,
      icon: InfoIcon,
      tone: "text-muted-foreground",
    }
  );
}

/** The categories with their labels. */
export const CATEGORIES: readonly { value: FindingCategory; label: string }[] = [
  { value: "integration_harder", label: "Integration harder" },
  { value: "requirement_incomplete", label: "Requirement incomplete" },
  { value: "capability_overstated", label: "Capability overstated" },
  { value: "hidden_dependency", label: "Hidden dependency" },
];

/** A category's label (its own name for one this build doesn't know). */
export function categoryLabel(value: FindingCategory): string {
  return CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

/** The review's header label: "Red Team v2". */
export function reviewLabel(review: Pick<RedTeamReview, "version">): string {
  return `Red Team v${review.version}`;
}

/** "1 critical · 2 high · 0 medium · 1 low". */
export function countsLabel(counts: SeverityCounts): string {
  return SEVERITIES.map((s) => `${counts[s.value]} ${s.value}`).join(" · ");
}

/** "1 Finding", "3 Findings". */
export function findingCount(n: number): string {
  return `${n} ${n === 1 ? "Finding" : "Findings"}`;
}

/** The header while a review is queued or running. */
export const REVIEWING = "Red Team reviewing";

/** Shown instead of the running indicator once polling has stopped (15 minutes). */
export const STILL_REVIEWING = "Still reviewing — reload to check.";

/** The empty-state sentence. */
export const NO_REVIEW = "The Red Team reviews the Opportunity after the Estimate is drafted.";

/** A finished run that had no active Requirements to challenge. */
export const NOTHING_TO_REVIEW = "There were no active Requirements to review.";

/** Why a review failed, as the Assessments tab says it. */
export const REVIEW_FAILURE_REASONS: Record<RunErrorCode, string> = {
  model_unavailable: "the model service couldn't be reached",
  model_timeout: "the model took too long to answer",
  output_invalid: "the model's answer couldn't be used",
};

/** "Red Team review failed: <reason>" (a general reason for a code this build doesn't know). */
export function reviewFailure(code: RunErrorCode | null | undefined): string {
  const reason = (code ? REVIEW_FAILURE_REASONS[code] : undefined) ?? "something went wrong";
  return `Red Team review failed: ${reason}`;
}

/** True while the run is queued or running. */
export function isReviewing(run: RedTeamRun | null | undefined): boolean {
  return run?.status === "queued" || run?.status === "running";
}

/** How often the Assessments tab re-reads the review while one runs. */
export const REVIEW_POLL_MS = 2000;

/** Polling stops after this long of continuous reviewing (a reload resumes it). */
export const REVIEW_POLL_LIMIT_MS = 15 * 60 * 1000;
