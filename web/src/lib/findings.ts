// Blocking Findings and overrides (Story 6.6): a Critic or Red Team Finding's status, what blocks
// submission, and the words of the resolve and override actions. Safe on server and client.
import { CircleCheckIcon, CircleDotIcon, ShieldIcon, type LucideIcon } from "lucide-react";

import type { components } from "@/lib/api/client";
import type { PillTone } from "@/components/ui/pill";

export type FindingState = components["schemas"]["FindingState"];
export type FindingStatus = FindingState["status"];
export type FindingOverride = components["schemas"]["FindingOverride"];
export type FindingResolution = components["schemas"]["FindingResolution"];
export type EvidenceOption = components["schemas"]["EvidenceOption"];
export type EvidenceRef = components["schemas"]["EvidenceRefIn"];

/** The kinds of Evidence a Finding accepts: Requirements and Sources. */
export function isEvidenceKind(kind: string): kind is EvidenceRef["kind"] {
  return kind === "requirement" || kind === "source_document";
}

/** A Finding's status pill: always an icon and a label. Open is blocker-coloured only when
 * critical (it then blocks submission); Resolved uses the resolved tone with a check;
 * Overridden is neutral with a shield. */
export function findingStatusInfo(
  status: FindingStatus,
  severity: string,
): { label: string; icon: LucideIcon; tone: PillTone } {
  switch (status) {
    case "resolved":
      return { label: "Resolved", icon: CircleCheckIcon, tone: "resolved" };
    case "overridden":
      return { label: "Overridden", icon: ShieldIcon, tone: "neutral" };
    default:
      return {
        label: "Open",
        icon: CircleDotIcon,
        tone: severity === "critical" ? "blocker" : "neutral",
      };
  }
}

/** Whether the Finding blocks submission (open and critical). */
export function blocksSubmission(finding: Pick<FindingState, "status"> & { severity: string }) {
  return finding.status === "open" && finding.severity === "critical";
}

/** The note on an open critical row. */
export const BLOCKS_SUBMISSION = "Blocks submission until resolved";

/** "Previously overridden by Ravi Kumar: <reason>". */
export function previousOverrideNote(override: Pick<FindingOverride, "by" | "reason">): string {
  return `Previously overridden by ${override.by.name}: ${override.reason}`;
}

/** "Overridden by Ravi Kumar". */
export function overriddenBy(override: Pick<FindingOverride, "by">): string {
  return `Overridden by ${override.by.name}`;
}

/** "Resolved by Ravi Kumar" (with the kind). */
export function resolvedBy(resolution: Pick<FindingResolution, "by" | "kind">): string {
  return resolution.kind === "evidence_supplied"
    ? `Evidence supplied by ${resolution.by.name}`
    : `Resolved by ${resolution.by.name}`;
}

/** The blocking count across the current Red Team and Critic Reviews (the Assessments tab
 * badge); null unless every one could be read (a partial sum would undercount). */
export function totalBlocking(
  ...counts: readonly ({ blocking_count: number } | null | undefined)[]
): number | null {
  let total = 0;
  for (const c of counts) {
    if (c == null) return null;
    total += c.blocking_count;
  }
  return total;
}

/** "2 blocking" (the badge's screen-reader label). */
export function blockingCountLabel(n: number): string {
  return `${n} blocking`;
}

export const SUPPLY_EVIDENCE = "Supply Evidence";
export const MARK_RESOLVED = "Mark resolved";
export const OVERRIDE = "Override";
export const REAPPLY_OVERRIDE = "Re-apply override";
export const OVERRIDE_TITLE = "Override this Finding?";
export const OVERRIDE_DESCRIPTION =
  "It will stop blocking submission. Your name and reason are recorded in the trace.";
export const OVERRIDE_CONFIRM = "Override";
export const OVERRIDE_KEEP = "Keep open";
export const EVIDENCE_LABEL = "Evidence";
export const EVIDENCE_PLACEHOLDER = "Choose Requirements or Sources";
export const EVIDENCE_SEARCH = "Search Requirements and Sources";
export const EVIDENCE_EMPTY = "Nothing matches.";
export const EVIDENCE_LIMIT = "Up to 20 Requirements or Sources can be cited.";
export const EVIDENCE_REQUIRED = "Choose at least one Requirement or Source.";
export const NOTE_LABEL = "Note (required)";
export const REASON_LABEL = "Reason (required)";
export const REASON_REQUIRED = "Give a reason of 1 to 1,000 characters.";
export const NOT_OVERRIDABLE =
  "Tied to a mandatory security Checklist item: it can't be overridden. Supply Evidence or " +
  "mark it resolved instead.";
export const FINDING_NOT_ALLOWED = "You are not allowed to do this.";
export const FINDING_GONE = "This Finding is no longer there. Reload to see the latest.";
export const FINDING_DECISION_FAILED = "The change could not be saved. Try again.";
export const EVIDENCE_NOT_LOADED = "The Requirements and Sources could not be loaded.";
export const REASON_MAX = 1000;
export const EVIDENCE_MAX = 20;

/** What was done, announced after a saved action. */
export const DONE: Record<"evidence" | "resolved" | "overridden", string> = {
  evidence: "Evidence supplied. The Finding is resolved.",
  resolved: "The Finding is marked resolved.",
  overridden: "The Finding is overridden.",
};

/** The trace frames that change a Finding's status or the Reviews (Story 6.6: the
 * Assessments tab badge follows them). */
export const FINDING_EVENTS: readonly string[] = [
  "assessments.finding.resolved",
  "assessments.finding.overridden",
  "assessments.red_team_review.completed",
  "assessments.critic_review.completed",
];
