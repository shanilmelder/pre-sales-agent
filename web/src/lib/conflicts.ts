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

export type ConflictsView = components["schemas"]["ConflictsView"];
export type Conflict = components["schemas"]["ConflictView"];
export type ConflictPosition = components["schemas"]["ConflictPosition"];
export type ConflictType = components["schemas"]["ConflictType"];
export type ConflictStatus = components["schemas"]["ConflictStatus"];

/** The empty-state sentence. */
export const NO_CONFLICTS = "No Conflicts between the specialist Assessments.";

/** Shown when the Conflicts could not be read. */
export const CONFLICTS_NOT_LOADED = "The Conflicts could not be loaded. Try again in a moment.";

export const OPEN_SECTION = "Open";
export const RESOLVED_SECTION = "Resolved";

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

/** Where a position comes from: "Engineering Assessment v2", "Estimate v3". */
export function positionSource(position: ConflictPosition): string {
  if (position.source === "estimate") return positionRole(position);
  const version = position.assessment_version === null ? "" : ` v${position.assessment_version}`;
  return `${positionRole(position)} Assessment${version}`;
}

function lowerFirst(text: string): string {
  return /^[A-Z][a-z]/.test(text) ? text[0]!.toLowerCase() + text.slice(1) : text;
}

/** The row's positions summary: "Engineering: 24 h · PM: not sized". */
export function positionsSummary(positions: readonly ConflictPosition[]): string {
  return positions.map((p) => `${positionRole(p)}: ${lowerFirst(p.summary)}`).join(" · ");
}

/** The tab label's count: "3 open" for screen readers. */
export function openCountLabel(n: number): string {
  return `${n} open`;
}
