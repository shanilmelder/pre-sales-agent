// Review Request display helpers (Story 9.1). Safe on server and client. Who may send or
// cancel a request is the API's decision (`can_request_review`, `can_create`, `can_cancel`);
// nothing here checks a role.
import type { LucideIcon } from "lucide-react";
import {
  BanIcon,
  CircleCheckIcon,
  CircleXIcon,
  ClockIcon,
  MessageSquareWarningIcon,
  RedoIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";
import type { PillTone } from "@/components/ui/pill";

export type ReviewType = components["schemas"]["ReviewType"];
export type RequestStatus = components["schemas"]["RequestStatus"];
export type ReviewRequest = components["schemas"]["ReviewRequestView"];
export type ReviewRequestsView = components["schemas"]["ReviewRequestsView"];
export type AssessmentOption = components["schemas"]["AssessmentOption"];
export type CreatedReviewRequests = components["schemas"]["CreatedReviewRequests"];

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

/** The trace frames after which the Estimate tab reads its requests again. */
export const REVIEW_TRACE_EVENTS: readonly string[] = [
  "reviews.review_request.created",
  "reviews.review_request.cancelled",
  "estimates.estimate_version.review_started",
  "estimates.estimate_version.review_ended",
  "estimates.estimate_version.submitted",
];
