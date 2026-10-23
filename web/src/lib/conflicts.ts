// Conflicts tab display helpers (Story 6.1, demo slice). Safe on server and client.
import {
  ArrowUpIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  MessagesSquareIcon,
  type LucideIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";
import { agentLabel, type AssessmentAgent } from "@/lib/assessments";
import { severityInfo } from "@/lib/red-team";

export type ConflictsView = components["schemas"]["ConflictsView"];
export type Conflict = components["schemas"]["ConflictView"];
export type ConflictPosition = components["schemas"]["ConflictPosition"];
export type ConflictType = components["schemas"]["ConflictType"];
export type ConflictStatus = components["schemas"]["ConflictStatus"];

/** The empty-tab card's copy. */
export const NO_CONFLICTS_TITLE = "No Conflicts detected";
export const NO_CONFLICTS_BODY = "Conflicts appear when Assessments or Sources disagree.";
export const OPEN_ASSESSMENTS = "Open Assessments";

/** Shown when the Conflicts could not be read. */
export const CONFLICTS_NOT_LOADED = "The Conflicts could not be loaded. Try again in a moment.";

export const RESOLVED_SECTION = "Resolved";
export const NO_OPEN_CONFLICTS = "No open Conflicts.";

/** The Conflict types with their labels. */
export const TYPES: readonly { value: ConflictType; label: string }[] = [
  { value: "timeline", label: "Timeline" },
  { value: "effort", label: "Effort" },
  { value: "resource", label: "Resource" },
  { value: "architecture", label: "Architecture" },
  { value: "security", label: "Security" },
  { value: "scope", label: "Scope" },
  { value: "assumption", label: "Assumption" },
  { value: "evidence", label: "Evidence" },
];

/** A type's label (its own name for one this build doesn't know). */
export function typeLabel(value: ConflictType): string {
  return TYPES.find((t) => t.value === value)?.label ?? value;
}

/** The statuses, each with its label, icon and icon tone (never colour alone). Blocker red is
 * only for Open, the one status that still needs someone. */
export const STATUSES: readonly {
  value: ConflictStatus;
  label: string;
  icon: LucideIcon;
  tone: "text-blocker" | "text-agent" | "text-resolved" | "text-gap";
}[] = [
  { value: "open", label: "Open", icon: CircleAlertIcon, tone: "text-blocker" },
  { value: "negotiating", label: "Negotiating", icon: MessagesSquareIcon, tone: "text-agent" },
  { value: "resolved", label: "Resolved", icon: CircleCheckIcon, tone: "text-resolved" },
  { value: "escalated", label: "Escalated", icon: ArrowUpIcon, tone: "text-gap" },
];

/** A status's display (a neutral one for a status this build doesn't know). */
export function statusInfo(value: ConflictStatus): (typeof STATUSES)[number] {
  return (
    STATUSES.find((s) => s.value === value) ?? {
      value,
      label: value,
      icon: CircleAlertIcon,
      tone: "text-gap",
    }
  );
}

/** True for a Conflict listed in the Open section (anything not resolved). */
export function isUnresolved(conflict: Pick<Conflict, "status">): boolean {
  return conflict.status !== "resolved";
}

/** The Conflicts split into the Open and Resolved sections, keeping the API's order. */
export function sections(conflicts: readonly Conflict[]): {
  open: Conflict[];
  resolved: Conflict[];
} {
  return {
    open: conflicts.filter(isUnresolved),
    resolved: conflicts.filter((c) => !isUnresolved(c)),
  };
}

/** Who holds a position: the agent by role ("Engineering", "PM", "Security"), or the
 * Estimate with its version ("Estimate v3"). */
export function positionRole(position: ConflictPosition): string {
  if (position.source === "estimate") {
    return position.estimate_version === null
      ? "Estimate"
      : `Estimate v${position.estimate_version}`;
  }
  if (!position.agent) return "Agent";
  return agentLabel(position.agent as AssessmentAgent).replace(/ Agent$/, "");
}

/** Story 6.2: the tag on a Conflict the Conflict Agent found in the Findings' text. */
export const DETECTED_FROM_TEXT = "Detected from text";

/** Whether the Conflict was found by the Conflict Agent (semantic detection, Story 6.2). */
export function isFromText(conflict: Pick<Conflict, "detected_by">): boolean {
  return conflict.detected_by === "semantic";
}

/** The tab heading's counts: "2 open · 5 resolved". */
export function headerCounts(conflicts: readonly Conflict[]): string {
  const { open, resolved } = sections(conflicts);
  return `${open.length} open · ${resolved.length} resolved`;
}

/** A row's sub-line: "Effort · R1", the type alone without a Requirement, and "· Detected from
 * text" for one the Conflict Agent found (6.2). */
export function rowSubline(
  conflict: Pick<Conflict, "type" | "requirement" | "detected_by">,
): string {
  const parts = [typeLabel(conflict.type)];
  if (conflict.requirement) parts.push(conflict.requirement.label);
  if (isFromText(conflict)) parts.push(DETECTED_FROM_TEXT);
  return parts.join(" · ");
}

/** The decision card's note: "Effort Conflict · Medium severity", plus "Detected from text". */
export function conflictNote(
  conflict: Pick<Conflict, "type" | "severity" | "detected_by">,
): string {
  const parts = [
    `${typeLabel(conflict.type)} Conflict`,
    `${severityInfo(conflict.severity).label} severity`,
  ];
  if (isFromText(conflict)) parts.push(DETECTED_FROM_TEXT);
  return parts.join(" · ");
}

/** A resolved row's tag: "Resolved by Alex", or "No longer present" when the system closed it. */
export function resolvedTag(conflict: Pick<Conflict, "resolved_by_name">): string {
  return conflict.resolved_by_name
    ? `Resolved by ${conflict.resolved_by_name}`
    : "No longer present";
}

/** A resolved row's muted line: a person's decision without who made it (the tag names them):
 * "Engineering's position, 96 h" or the entered text; else the system's reason ("No longer
 * present in PM Assessment v2"); null when there is neither. */
export function resolvedLine(conflict: Conflict): string | null {
  if (conflict.resolved_by_name) {
    if (conflict.entered_position) return conflict.entered_position;
    const chosen = conflict.positions.find((p) => p.position === conflict.chosen_position);
    if (chosen) return `${positionName(chosen)}, ${chosen.summary}`;
  }
  return conflict.resolution_reason ?? null;
}

/** A position card's pill: the agent in full ("Engineering Agent"), or the Estimate with its
 * version ("Estimate v3"). */
export function agentPillLabel(position: ConflictPosition): string {
  if (position.source === "estimate") return positionRole(position);
  if (!position.agent) return "Agent";
  return agentLabel(position.agent as AssessmentAgent);
}

/** A position card's version line: "Assessment v2"; null for the Estimate (its pill names the
 * version) or an Assessment without one. */
export function positionVersion(position: ConflictPosition): string | null {
  if (position.source === "estimate" || position.assessment_version === null) return null;
  return `Assessment v${position.assessment_version}`;
}

/** The tab label's count: "3 open" for screen readers. */
export function openCountLabel(n: number): string {
  return `${n} open`;
}

// --- decisions (Story 6.3) ------------------------------------------------------------------

export type Person = components["schemas"]["Person"];

/** The API's limits, in characters (code points). */
export const DECISION_REASON_MAX = 1000;
export const ENTERED_MAX = 200;

export const REASON_REQUIRED = "Give a reason for the decision.";
export const CHOICE_REQUIRED = "Choose a position, or enter a different one.";
export const ENTERED_REQUIRED = "Enter the different position.";
export const HOURS_REQUIRED =
  "Enter hours from 0 to 2,000, to 0.1 h (for example 48).";
export const REVIEWER_REQUIRED = "Choose a reviewer.";
export const DIFFERENT_POSITION = "A different position";

/** Whether an entered position reads as hours the API accepts for an effort Conflict:
 * "48", "48.5", "48 h", 0 to 2,000. */
export function isEnteredHours(text: string): boolean {
  const match = /^(\d{1,4}(?:\.\d)?)\s*h?$/.exec(text.trim());
  return match !== null && Number(match[1]) <= 2000;
}

/** "Engineering's position" or "Estimate v3's position". */
export function positionName(position: ConflictPosition): string {
  return `${positionRole(position)}'s position`;
}

/** The decision on a resolved Conflict a person resolved: "Resolved by Alex: Engineering's
 * position, 64 h" or "Resolved by Alex: In scope: PM to size in v2"; null otherwise. */
export function decisionLabel(conflict: Conflict): string | null {
  if (conflict.status !== "resolved" || !conflict.resolved_by_name) return null;
  const by = `Resolved by ${conflict.resolved_by_name}`;
  if (conflict.entered_position) return `${by}: ${conflict.entered_position}`;
  const chosen = conflict.positions.find(
    (p) => p.position === conflict.chosen_position,
  );
  return chosen ? `${by}: ${positionName(chosen)}, ${chosen.summary}` : by;
}

const NOT_APPLIED: Record<string, string> = {
  shared_line: "Not applied: the Estimate line covers several Requirements.",
  several_lines: "Not applied: several Estimate lines cover it.",
  no_line: "Not applied: no Estimate line covers it.",
  not_permitted: "Not applied: you can't edit the Estimate.",
};

/** What an effort decision did to the Estimate: "Estimate line set to 100 h." or why it did
 * nothing; null when there is nothing to say. */
export function estimateEffect(conflict: Conflict): string | null {
  if (conflict.applied_hours !== null) {
    return `Estimate line set to ${formatHours(conflict.applied_hours)}.`;
  }
  if (conflict.not_applied) return NOT_APPLIED[conflict.not_applied] ?? null;
  return null;
}

/** Before resolving an effort Conflict with an agent's position: "Choosing an agent's position
 * sets the Estimate line to the agents' total, 100 h." (the figure the API applies). */
export function agentsTotalEffect(
  positions: readonly ConflictPosition[],
): string {
  const total = positions
    .filter((p) => p.source === "assessment" && p.value !== null)
    .reduce((sum, p) => sum + (p.value ?? 0), 0);
  return `Choosing an agent's position sets the Estimate line to the agents' total, ${formatHours(Math.round(total * 10) / 10)}.`;
}

function formatHours(hours: number): string {
  const text = hours.toFixed(1);
  return `${text.endsWith(".0") ? text.slice(0, -2) : text} h`;
}

/** "Escalated to Sam", or null. */
export function escalatedLabel(
  conflict: Pick<Conflict, "escalated_to">,
): string | null {
  return conflict.escalated_to
    ? `Escalated to ${conflict.escalated_to.name}`
    : null;
}

/** "Resolved earlier by Alex; positions have changed.", or null. */
export function previousDecisionLabel(
  conflict: Pick<Conflict, "previous_decision">,
): string | null {
  return conflict.previous_decision
    ? `Resolved earlier by ${conflict.previous_decision.name}; positions have changed.`
    : null;
}
