// Inbox display helpers (Story 9.2). Safe on server and client. Which items a user sees, and
// where each one links, is the API's decision (`href` is null once the subject is closed);
// nothing here checks a role.
import type { LucideIcon } from "lucide-react";
import {
  BanIcon,
  CircleCheckIcon,
  CircleXIcon,
  ClockIcon,
  MessageSquareWarningIcon,
  RedoIcon,
  TriangleAlertIcon,
} from "lucide-react";

import type { PillTone } from "@/components/ui/pill";
import type { components } from "@/lib/api/client";
import {
  CHALLENGE_STATUSES,
  REQUEST_STATUSES,
  type ChallengeStatus,
  type RequestStatus,
} from "@/lib/reviews";

export type InboxItem = components["schemas"]["InboxItem"];
export type InboxPage = components["schemas"]["InboxPage"];
export type NotificationKind = components["schemas"]["NotificationKind"];
export type InboxGroup = components["schemas"]["InboxGroup"];

export const INBOX_TITLE = "Inbox";
export const MARK_ALL_READ = "Mark all read";
export const OPEN = "Open";
export const EMPTY_TITLE = "Inbox is empty";
export const EMPTY_BODY = "Review requests and notifications for your Opportunities appear here.";
export const NOT_REACHABLE = "The platform is not reachable right now. Try again in a moment.";
export const NO_SELECTION = "Select an item to see it here.";
export const LIST_LABEL = "Inbox items";
/** A Review Request item's subject type (Story 9.3: its detail is the review panel). */
export const REVIEW_SUBJECT = "reviews.review_request";
/** A Challenge item's subject type (Story 9.5: its detail is the Challenge form). */
export const CHALLENGE_SUBJECT = "reviews.challenge";

/** How often the badge and the Inbox read again while the window is open. */
export const INBOX_POLL_MS = 30_000;

/** The groups, in the API's order, with their list labels. Only non-empty ones show. */
export const INBOX_GROUPS: readonly { group: InboxGroup; label: string }[] = [
  { group: "reviews", label: "Review Requests" },
  { group: "challenges", label: "Challenges" },
  { group: "waiting", label: "Waiting for your input" },
  { group: "updates", label: "Updates" },
];

const REVIEW_KINDS: readonly NotificationKind[] = [
  "review_requested",
  "review_reminder",
  "review_outcome",
  "review_replied",
];

/** Story 9.4: the author's outcome items, which follow the request whoever holds it (a reply
 * item is the reviewer's, like their other items). */
const AUTHOR_SIDE_KINDS: readonly NotificationKind[] = ["review_outcome"];

/** Review Requests, their reminders and (Story 9.4) outcomes and replies: a primary dot and the
 * "Review" kind label. */
export function isReviewKind(kind: NotificationKind): boolean {
  return REVIEW_KINDS.includes(kind);
}

const CHALLENGE_KINDS: readonly NotificationKind[] = ["challenge_raised", "challenge_declined"];

/** The label at the right of a row and in the detail's header (Story 9.5: "Challenge"). */
export function kindLabel(kind: NotificationKind): "Review" | "Challenge" | "Update" {
  if (CHALLENGE_KINDS.includes(kind)) return "Challenge";
  return isReviewKind(kind) ? "Review" : "Update";
}

/** Items grouped in `INBOX_GROUPS` order, keeping the API's order within each group. */
export function groupItems(
  items: readonly InboxItem[],
): { group: InboxGroup; label: string; items: InboxItem[] }[] {
  return INBOX_GROUPS.map(({ group, label }) => ({
    group,
    label,
    items: items.filter((item) => item.group === group),
  })).filter((section) => section.items.length > 0);
}

const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

/** "21 Oct 2026, 10:02" (UTC). */
export function itemDate(createdAt: string): string {
  const date = new Date(createdAt);
  return Number.isNaN(date.getTime()) ? "" : DATE_TIME.format(date);
}

/** The row's meta: "From {sender} · {date}" for a Review Request, else "{Opportunity} ·
 * {date}". */
export function itemMeta(item: InboxItem): string {
  const date = itemDate(item.created_at);
  const lead = item.sender
    ? `From ${item.sender}`
    : item.opportunity_title
      ? item.opportunity_title
      : null;
  return lead ? `${lead} · ${date}` : date;
}

/** The detail's sentence: what the item asks of the reader, in glossary terms. */
export function itemBody(item: InboxItem): string {
  const who = item.sender ?? "Someone";
  const where = item.opportunity_title ? ` on ${item.opportunity_title}` : "";
  switch (item.kind) {
    case "review_requested":
      return `${who} asks you to review this${where}. Open it to see what to review.`;
    case "review_reminder":
      return `This Review Request${where} is still waiting for your review.`;
    case "review_cancelled":
      return `This Review Request${where} was cancelled. Nothing is needed from you.`;
    case "run_waiting":
      return `A Workflow Run${where} is paused until someone decides how it goes on.`;
    case "conflict_escalated":
      return `A Conflict${where} was escalated to you to decide.`;
    case "review_outcome":
      return `A reviewer decided on a Review Request${where}.`;
    case "review_replied":
      return `The author replied on a Review Request${where}.`;
    case "challenge_raised":
      return `${who} challenged this${where}. Confirm which Assessments rerun, or decline.`;
    case "challenge_declined":
      return `Your Challenge${where} was declined. The reason is below.`;
  }
}

/** Story 9.4: whether a Review item's detail shows the review panel greyed: a superseded or
 * cancelled request, or (for the reviewer's own items) one handed to someone else. An author's
 * outcome on an approved or rejected request stays live (New version). */
export function isGreyedReviewItem(item: InboxItem): boolean {
  if (item.subject_open) return false;
  const status = item.subject_status;
  if (status === "superseded" || status === "cancelled") return true;
  return !AUTHOR_SIDE_KINDS.includes(item.kind);
}

type StatusStyle = { label: string; tone: PillTone; icon: LucideIcon };

const OTHER_STATUSES: Record<string, StatusStyle> = {
  open: { label: "Waiting", tone: "gap", icon: ClockIcon },
  resolved: { label: "Resolved", tone: "resolved", icon: CircleCheckIcon },
  escalated: { label: "Escalated", tone: "gap", icon: TriangleAlertIcon },
  negotiating: { label: "Negotiating", tone: "gap", icon: MessageSquareWarningIcon },
  cancelled: { label: "Cancelled", tone: "neutral", icon: BanIcon },
  approved: { label: "Approved", tone: "resolved", icon: CircleCheckIcon },
  rejected: { label: "Rejected", tone: "blocker", icon: CircleXIcon },
  superseded: { label: "Superseded", tone: "neutral", icon: RedoIcon },
};

/** The subject status pill (icon and label, never colour alone); null while the subject is
 * open or its status is unknown. */
export function closedStatus(item: InboxItem): StatusStyle | null {
  if (item.subject_open || !item.subject_status) return null;
  const status = item.subject_status;
  const style =
    item.subject_type === REVIEW_SUBJECT && status in REQUEST_STATUSES
      ? REQUEST_STATUSES[status as RequestStatus]
      : item.subject_type === CHALLENGE_SUBJECT && status in CHALLENGE_STATUSES
        ? CHALLENGE_STATUSES[status as ChallengeStatus]
        : OTHER_STATUSES[status];
  if (!style) return { label: item.subject_status_label ?? status, tone: "neutral", icon: BanIcon };
  return { ...style, label: item.subject_status_label ?? style.label };
}

/** "Inbox, 3 unread" (the sidebar link's accessible name); just "Inbox" at 0. */
export function inboxLinkName(unread: number): string {
  return unread > 0 ? `Inbox, ${unread} unread` : "Inbox";
}

/** The badge's text: the count, capped at "99+". */
export function badgeText(unread: number): string {
  return unread > 99 ? "99+" : String(unread);
}

/** The trace frames after which, inside an Opportunity, the badge and the Inbox read again. */
export const INBOX_TRACE_EVENTS: readonly string[] = [
  "reviews.review_request.created",
  "reviews.review_request.cancelled",
  "reviews.review_request.reminded",
  "reviews.review_decision.recorded",
  "reviews.review_request.replied",
  "reviews.review_request.superseded",
  "reviews.challenge.raised",
  "reviews.challenge.confirmed",
  "reviews.challenge.declined",
  "conflicts.conflict.escalated",
  "workflows.run.waiting_for_human",
];

const OPPORTUNITY_PATH = /^\/opportunities\/([0-9a-fA-F-]{36})(?:\/|$)/;

/** The Opportunity id of a workspace path (`/opportunities/{id}/…`), else null. */
export function opportunityIdOf(pathname: string): string | null {
  return OPPORTUNITY_PATH.exec(pathname)?.[1] ?? null;
}
