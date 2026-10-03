// Opportunity display helpers. Safe on server and client.
import {
  CircleDashedIcon,
  CircleDotIcon,
  CircleHelpIcon,
  CircleXIcon,
  ClipboardCheckIcon,
  FlagIcon,
  type LucideIcon,
  SearchCheckIcon,
  SigmaIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";

export type OpportunityStatus = components["schemas"]["OpportunityStatus"];
export type OpportunitySummary = components["schemas"]["OpportunitySummary"];
export type OpportunityPage = components["schemas"]["OpportunityPage"];
export type Opportunity = components["schemas"]["Opportunity"];
export type UserRef = components["schemas"]["UserRef"];
export type UserSummary = components["schemas"]["UserSummary"];
export type OpportunityFacets = components["schemas"]["OpportunityFacets"];

/** The empty-state sentence for people who can create Opportunities. */
export const EMPTY_LIST_CREATOR = "No Opportunities yet. Press c to create one.";
/** The empty-state sentence for everyone else (they have no `c`). */
export const EMPTY_LIST = "No Opportunities yet.";
/** The empty-state sentence when the All Opportunities filters match nothing. */
export const EMPTY_FILTERED = "No Opportunities match these filters.";
/** What anyone sees for an Opportunity they may not read, or one that doesn't exist. */
export const NO_ACCESS_TO_OPPORTUNITY = "You don't have access to this Opportunity";

/** Skeleton rows stay up at least this long on a list's first load. */
export const SKELETON_MIN_MS = 150;

/** Every status with its label and icon (the pill always shows both). */
export const STATUSES: Record<OpportunityStatus, { label: string; icon: LucideIcon }> = {
  intake: { label: "Intake", icon: CircleDashedIcon },
  gaps_open: { label: "Gaps open", icon: CircleHelpIcon },
  assessing: { label: "Assessing", icon: SearchCheckIcon },
  estimating: { label: "Estimating", icon: SigmaIcon },
  in_review: { label: "In review", icon: CircleDotIcon },
  baselined: { label: "Baselined", icon: ClipboardCheckIcon },
  delivered: { label: "Delivered", icon: FlagIcon },
  closed: { label: "Closed", icon: CircleXIcon },
};

export function statusLabel(status: OpportunityStatus): string {
  return STATUSES[status]?.label ?? status;
}

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** A calendar date (`YYYY-MM-DD`) as "4 Oct 2026", the same in every time zone. */
export function formatDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) return value;
  const [, y, m, d] = match;
  return DATE_FORMAT.format(new Date(Date.UTC(Number(y), Number(m) - 1, Number(d))));
}

/** Today's date in UTC as `YYYY-MM-DD`: the API checks "not in the past" against it. */
export function utcToday(now: Date = new Date()): string {
  return now.toISOString().slice(0, 10);
}

/** Length in Unicode code points, as the API (Python) counts it; `.length` counts UTF-16
 * units, so one emoji would count as two. */
export function codePointLength(value: string): number {
  return Array.from(value).length;
}

/** The first `max` code points of `value`, never splitting a surrogate pair. */
export function sliceCodePoints(value: string, max: number): string {
  return Array.from(value).slice(0, max).join("");
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
