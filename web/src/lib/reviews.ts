// Review Request display helpers (Story 9.1). Safe on server and client. Who may send or
// cancel a request is the API's decision (`can_request_review`, `can_create`, `can_cancel`);
// nothing here checks a role.
import type { LucideIcon } from "lucide-react";
import {
  ArrowUpIcon,
  BanIcon,
  CircleCheckIcon,
  CircleXIcon,
  ClockIcon,
  FileSearchIcon,
  GitCompareArrowsIcon,
  MessageSquareWarningIcon,
  RedoIcon,
  ReplyIcon,
  TriangleAlertIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";
import type { PillTone } from "@/components/ui/pill";

export type ReviewType = components["schemas"]["ReviewType"];
export type RequestStatus = components["schemas"]["RequestStatus"];
export type ReviewRequest = components["schemas"]["ReviewRequestView"];
export type ReviewRequestsView = components["schemas"]["ReviewRequestsView"];
export type AssessmentOption = components["schemas"]["AssessmentOption"];
export type CreatedReviewRequests = components["schemas"]["CreatedReviewRequests"];
// Story 9.3
export type Decision = components["schemas"]["Decision"];
export type ReviewDecision = components["schemas"]["ReviewDecisionView"];
export type ReviewPanel = components["schemas"]["ReviewPanel"];
export type RecordedDecision = components["schemas"]["RecordedDecision"];
export type VersionDiff = components["schemas"]["VersionDiff"];
export type LineDiff = components["schemas"]["LineDiff"];
export type ReviewPerson = components["schemas"]["ReviewPerson"];
// Story 9.4
export type ReviewReply = components["schemas"]["ReviewReplyView"];
export type RecordedReply = components["schemas"]["RecordedReply"];
export type ReviewEvidence = components["schemas"]["ReviewEvidence"];
export type CreatedVersion = components["schemas"]["CreatedVersion"];

/** The review types, in the segmented control's order. */
export const REVIEW_TYPES: readonly { value: ReviewType; label: string }[] = [
  { value: "engineering", label: "Engineering" },
  { value: "pm", label: "PM" },
  { value: "security", label: "Security" },
];

export function reviewTypeLabel(value: ReviewType): string {
  return REVIEW_TYPES.find((t) => t.value === value)?.label ?? value;
}

/** Each status's label, tone and icon (EXPERIENCE.md: Review Request states): never colour
 * alone. */
export const REQUEST_STATUSES: Record<
  RequestStatus,
  { label: string; tone: PillTone; icon: LucideIcon }
> = {
  pending: { label: "Pending", tone: "gap", icon: ClockIcon },
  approved: { label: "Approved", tone: "resolved", icon: CircleCheckIcon },
  rejected: { label: "Rejected", tone: "blocker", icon: CircleXIcon },
  challenged: { label: "Challenged", tone: "gap", icon: MessageSquareWarningIcon },
  superseded: { label: "Superseded", tone: "neutral", icon: RedoIcon },
  cancelled: { label: "Cancelled", tone: "neutral", icon: BanIcon },
};

export const REQUEST_REVIEW = "Request review";
export const REVIEW_REQUESTS_TITLE = "Review requests";
export const NO_REQUESTS = "No Review Request sent yet";
export const REVIEW_TYPE_LABEL = "Review type";
export const REVIEWERS_LABEL = "Reviewers";
export const REVIEWERS_PLACEHOLDER = "Choose reviewers";
export const REVIEWERS_SEARCH = "Search reviewers";
export const REVIEWERS_EMPTY = "No one with this review role matches.";
export const REVIEWERS_NOT_LOADED = "The reviewers could not be loaded. Try again.";
export const ASSESSMENTS_LABEL = "Assessments to review (optional)";
export const ASSESSMENTS_HELP = "Leave all unticked to review the whole Estimate Version.";
export const MESSAGE_LABEL = "Message (optional)";
export const MESSAGE_MAX = 2000;
export const CANCEL = "Cancel";
export const CANCEL_REQUEST = "Cancel request";
export const CANCEL_REASON_LABEL = "Reason for cancelling";
export const CANCEL_REASON_MAX = 1000;
export const KEEP_REQUEST = "Keep request";
export const REASON_REQUIRED = "Give a reason of 1 to 1,000 characters.";
export const MESSAGE_TOO_LONG = "The message can be at most 2,000 characters.";
export const REQUEST_FAILED = "Not sent: the platform is not reachable. Try again.";
export const REQUEST_STALE = "Not sent: the Estimate changed since you opened it (412). Reload it.";
export const REQUEST_FORBIDDEN = "You can't request a review of this Estimate.";
export const CANCEL_FAILED = "Not cancelled: the platform is not reachable. Try again.";
export const CANCEL_STALE = "Not cancelled: this request changed since you opened it (412).";
export const CANCEL_FORBIDDEN = "You can't cancel this Review Request.";
export const CANCELLED_ANNOUNCEMENT = "Review request cancelled";

/** "Request review of Estimate v3". */
export function requestReviewTitle(version: number): string {
  return `Request review of Estimate v${version}`;
}

/** How many requests a send makes: one per reviewer and picked Assessment, or one per
 * reviewer for the whole version. */
export function requestCount(reviewers: number, assessments: number): number {
  return reviewers * Math.max(1, assessments);
}

/** "Send 2 requests" / "Send 1 request" / "Send requests" (none chosen yet). */
export function sendLabel(count: number): string {
  if (count === 0) return "Send requests";
  return `Send ${count} ${count === 1 ? "request" : "requests"}`;
}

/** "Review requested from 2 reviewers" (announced after a send). */
export function requestedAnnouncement(reviewers: number): string {
  return `Review requested from ${reviewers} ${reviewers === 1 ? "reviewer" : "reviewers"}`;
}

const SHORT_DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

/** "Sent 24 Oct". */
export function sentLabel(createdAt: string): string {
  const date = new Date(createdAt);
  return Number.isNaN(date.getTime()) ? "Sent" : `Sent ${SHORT_DATE.format(date)}`;
}

/** The DOM id of a request's row on the Estimate tab (`?review={id}` scrolls to it). */
export function reviewRowId(requestId: string): string {
  return `review-${requestId}`;
}

/** The trace frames after which the Estimate tab reads its requests (and the open review
 * panel) again. */
export const REVIEW_TRACE_EVENTS: readonly string[] = [
  "reviews.review_request.created",
  "reviews.review_request.cancelled",
  "reviews.review_decision.recorded",
  "estimates.estimate_version.review_started",
  "estimates.estimate_version.review_ended",
  "estimates.estimate_version.approved",
  "estimates.estimate_version.rejected",
  "estimates.estimate_version.submitted",
  // Story 9.4
  "reviews.review_request.replied",
  "reviews.review_request.superseded",
  "estimates.estimate_version.created",
  // Story 9.7
  "estimates.baseline.set",
];

// --- Review Decisions and the review panel (Story 9.3) --------------------------------------

type DecisionStyle = { label: string; tone: PillTone; icon: LucideIcon };

/** Each decision's label, tone and icon: never colour alone. */
export const DECISION_STYLES: Record<Decision, DecisionStyle> = {
  approved: { label: "Approved", tone: "resolved", icon: CircleCheckIcon },
  rejected: { label: "Rejected", tone: "blocker", icon: CircleXIcon },
  challenged: { label: "Challenged", tone: "gap", icon: MessageSquareWarningIcon },
  evidence_requested: { label: "Evidence requested", tone: "gap", icon: FileSearchIcon },
  alternative_requested: {
    label: "Alternative requested",
    tone: "gap",
    icon: GitCompareArrowsIcon,
  },
  escalated: { label: "Escalated", tone: "gap", icon: ArrowUpIcon },
};

/** A decision the panel's reason form records: every one but Approve, and not Challenge
 * (Story 9.5 builds its dialog). */
export type ReasonedDecision =
  | "rejected"
  | "evidence_requested"
  | "alternative_requested"
  | "escalated";

export const DECISION_REASON_MAX = 1000;
export const APPROVE = "Approve";
export const REJECT = "Reject";
export const CHALLENGE = "Challenge";
export const REQUEST_EVIDENCE = "Request evidence";
export const REQUEST_ALTERNATIVE = "Request alternative";
export const ESCALATE = "Escalate";
export const CHALLENGE_LATER = "Challenge arrives with Story 9.5";
export const CHOOSE_REVIEWER = "Choose a reviewer";
export const OPEN_IN_TAB = "Open in tab";
export const FIRST_VERSION = "First version";
export const NO_CHANGES = "No line changed.";
export const DECISION_FAILED = "Not recorded: the platform is not reachable. Try again.";
export const DECISION_FORBIDDEN = "You can't decide this Review Request.";
export const LOADING_PANEL = "Loading the review…";
export const PANEL_NOT_LOADED = "The review could not be loaded. Try again in a moment.";
export const DECISIONS_TITLE = "Decisions";
export const ACTIONS_LABEL = "Review decision";
export const VIEW_DIFF = "View diff";
export const HIDE_DIFF = "Hide diff";

const REASON_VERB: Record<ReasonedDecision, string> = {
  rejected: "rejecting",
  evidence_requested: "requesting evidence",
  alternative_requested: "requesting an alternative",
  escalated: "escalating",
};

const ACTION_LABEL: Record<ReasonedDecision, string> = {
  rejected: REJECT,
  evidence_requested: REQUEST_EVIDENCE,
  alternative_requested: REQUEST_ALTERNATIVE,
  escalated: ESCALATE,
};

/** "Reason for rejecting (required)". */
export function reasonLabel(decision: ReasonedDecision): string {
  return `Reason for ${REASON_VERB[decision]} (required)`;
}

/** "Confirm Reject", "Confirm Escalate". */
export function confirmLabel(decision: ReasonedDecision): string {
  return `Confirm ${ACTION_LABEL[decision]}`;
}

/** What is announced once a decision is recorded: "Estimate v3 approved" when the approval
 * approved the version, else "Review approved", "Review rejected", "Evidence requested",
 * "Alternative requested" or "Review escalated to Cy Ruiz". */
export function decisionAnnouncement(recorded: RecordedDecision): string {
  const { decision, request, version_status } = recorded;
  switch (decision.decision) {
    case "approved":
      return version_status === "approved"
        ? `Estimate v${request.estimate_version} approved`
        : "Review approved";
    case "rejected":
      return "Review rejected";
    case "escalated":
      return `Review escalated to ${decision.escalated_to?.name ?? "another reviewer"}`;
    default:
      return DECISION_STYLES[decision.decision].label;
  }
}

const DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

function formatted(format: Intl.DateTimeFormat, value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : format.format(date);
}

/** The panel header's eyebrow: "Engineering review · From Owner Person · 24 Oct 2026". */
export function panelEyebrow(request: ReviewRequest): string {
  const when = formatted(DATE, request.created_at);
  const head = `${reviewTypeLabel(request.review_type)} review · From ${request.requested_by.name}`;
  return when ? `${head} · ${when}` : head;
}

/** The panel's title: "Review request: Estimate v3, {Opportunity}". */
export function panelTitle(request: ReviewRequest, opportunityTitle: string | null): string {
  const head = `Review request: ${request.target.label}`;
  return opportunityTitle ? `${head}, ${opportunityTitle}` : head;
}

/** A decision's line: "Ana Ruiz · Evidence requested · 25 Oct, 10:02" ("Escalated to Cy Ruiz"
 * for an escalation). */
export function decisionLine(decision: ReviewDecision): string {
  const what =
    decision.decision === "escalated" && decision.escalated_to
      ? `${decision.label} to ${decision.escalated_to.name}`
      : decision.label;
  const when = formatted(DATE_TIME, decision.decided_at);
  const head = `${decision.decided_by.name} · ${what}`;
  return when ? `${head} · ${when}` : head;
}

/** "Superseded by v4" (just "Superseded" when the newer version is unknown). */
export function supersededLabel(supersededBy: number | null): string {
  return supersededBy == null ? "Superseded" : `Superseded by v${supersededBy}`;
}

/** Whether the panel shows greyed and read only: the request or its version is superseded. */
export function isSupersededPanel(panel: Pick<ReviewPanel, "request" | "version_status">): boolean {
  return panel.request.status === "superseded" || panel.version_status === "superseded";
}

/** "+12 h", "−10 h" (a minus sign), "0 h". */
export function deltaLabel(hours: number): string {
  const rounded = Math.round(hours * 10) / 10;
  if (rounded > 0) return `+${rounded} h`;
  if (rounded < 0) return `−${Math.abs(rounded)} h`;
  return "0 h";
}

/** The diff's heading: "Compared with v2", or "First version". */
export function diffHeading(diff: VersionDiff): string {
  return diff.first || diff.previous_version == null
    ? FIRST_VERSION
    : `Compared with v${diff.previous_version}`;
}

/** `/opportunities/{id}/estimate/reviews/{rid}`: the panel full width (**Open in tab**). */
export function reviewPanelHref(opportunityId: string, requestId: string): string {
  return `/opportunities/${opportunityId}/estimate/reviews/${requestId}`;
}

// --- the author's side (Story 9.4) ----------------------------------------------------------

export const REVIEW_OUTCOMES_TITLE = "Review outcomes";
export const REPLY = "Reply";
export const REPLY_MAX = 2000;
export const LINK_ALTERNATIVE = "Link as alternative";
export const ALTERNATIVE_DRAFT = "Alternative draft";
export const ADD_SOURCE = "Add Source";
export const HIDE_ADD_SOURCE = "Done adding Sources";
export const NEW_VERSION = "New version";
export const ALL_APPROVED = "All requested reviews approved. Baseline can be set.";
export const REPLY_FAILED = "Not sent: the platform is not reachable. Try again.";
export const REPLY_FORBIDDEN = "You can't reply to this Review Request.";
export const REPLY_SENT = "Reply sent";
export const NEW_VERSION_FAILED = "No new version: the platform is not reachable. Try again.";
export const NEW_VERSION_FORBIDDEN = "You can't start a new version of this Estimate.";

/** "Reply to Ana Ruiz (required)". */
export function replyLabel(reviewer: string): string {
  return `Reply to ${reviewer} (required)`;
}

/** "Escalated to Cy Ruiz". */
export function escalatedLabel(name: string): string {
  return `Escalated to ${name}`;
}

/** "Alternative to the v3 request". */
export function alternativeToLabel(version: number): string {
  return `Alternative to the v${version} request`;
}

/** "Draft v4 started" (announced after **New version**). */
export function newVersionAnnouncement(version: number): string {
  return `Draft v${version} started`;
}

/** An outcome row's icon and colour (EXPERIENCE.md: icon and text, never colour alone):
 * approved green, rejected blocker, the requests and escalations amber, a reply primary. */
export type OutcomeTone = "resolved" | "blocker" | "gap" | "primary";

export const OUTCOME_TONES: Record<OutcomeTone, { icon: LucideIcon; className: string }> = {
  resolved: { icon: CircleCheckIcon, className: "text-resolved" },
  blocker: { icon: CircleXIcon, className: "text-blocker" },
  gap: { icon: TriangleAlertIcon, className: "text-gap" },
  primary: { icon: ReplyIcon, className: "text-primary-text" },
};

/** One row of the Review outcomes list: "**who** · what", the time and a note (a reason or
 * the reply's message), with the reply's Evidence. */
export type OutcomeRow = {
  id: string;
  tone: OutcomeTone;
  who: string;
  what: string;
  when: string;
  at: string;
  note: string | null;
  evidence: ReviewEvidence[];
};

const DECISION_TONES: Record<Decision, OutcomeTone> = {
  approved: "resolved",
  rejected: "blocker",
  challenged: "gap",
  evidence_requested: "gap",
  alternative_requested: "gap",
  escalated: "gap",
};

const OUTCOME_DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "UTC",
});

/** The Review outcomes list: one row per decision and per reply, oldest first. */
export function outcomeRows(
  panel: Pick<ReviewPanel, "decisions" | "replies">,
): OutcomeRow[] {
  const decided: OutcomeRow[] = panel.decisions.map((d) => ({
    id: d.id,
    tone: DECISION_TONES[d.decision],
    who: d.decided_by.name,
    what:
      d.decision === "escalated" && d.escalated_to
        ? escalatedLabel(d.escalated_to.name)
        : d.label,
    when: formatted(OUTCOME_DATE, d.decided_at),
    at: d.decided_at,
    note: d.reason,
    evidence: [],
  }));
  const replied: OutcomeRow[] = panel.replies.map((r) => ({
    id: r.id,
    tone: "primary",
    who: r.replied_by.name,
    what: r.alternative ? `Replied with v${r.alternative.version} as the alternative` : "Replied",
    when: formatted(OUTCOME_DATE, r.replied_at),
    at: r.replied_at,
    note: r.message,
    evidence: r.evidence,
  }));
  return [...decided, ...replied].sort(
    (a, b) => new Date(a.at).getTime() - new Date(b.at).getTime(),
  );
}
