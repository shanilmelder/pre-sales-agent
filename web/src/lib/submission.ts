// Submission blockers display helpers (Story 8.6). Safe on server and client. The API's
// `get_submission_blockers` is the only rule that decides submittability (AD-27): nothing here
// derives a blocker, it only groups and words what the API returned.
import type { components } from "@/lib/api/client";
import { tabHref, type WorkspaceTabSlug } from "@/lib/workspace";

export type Blocker = components["schemas"]["Blocker"];
export type BlockerKind = Blocker["kind"];
export type SubmissionBlockers = components["schemas"]["SubmissionBlockers"];
export type SubmissionBlockersView = components["schemas"]["SubmissionBlockersView"];
export type SubmissionVersion = components["schemas"]["SubmissionVersion"];
export type SubmittedVersion = components["schemas"]["SubmittedVersion"];

/** The trace frames after which the blockers are read again (with `gaps.changed` and
 * `conflicts.changed`, which carry no type): every `estimates.*` and `assessments.*` event
 * that can add or remove one, and Requirement changes (uncovered Requirements). */
export const BLOCKER_TRACE_EVENTS: readonly string[] = [
  "estimates.estimate_version.created",
  "estimates.estimate_version.submitted",
  "estimates.estimate_version.superseded",
  // Story 9.1: Review Requests are the Baseline group.
  "estimates.estimate_version.review_started",
  "estimates.estimate_version.review_ended",
  "reviews.review_request.created",
  "reviews.review_request.cancelled",
  // Story 9.7: decisions move the version towards the Baseline, which ends the gate.
  "reviews.review_decision.recorded",
  "estimates.estimate_version.approved",
  "estimates.estimate_version.rejected",
  "estimates.baseline.set",
  "estimates.assumption.proposed",
  "estimates.assumption.accepted",
  "estimates.assumption.edited",
  "estimates.risk.created",
  "estimates.estimate_line.edited",
  "assessments.finding.resolved",
  "assessments.finding.overridden",
  "assessments.red_team_review.completed",
  "assessments.critic_review.completed",
  "intake.requirement.created",
  "intake.requirement.edited",
  "intake.requirement_change.accepted",
  "intake.requirement.deleted",
  "intake.requirement.split",
  "intake.requirement.merged",
  "intake.extraction.completed",
];

/** The id of the Overview's Submission blockers card heading (the Resolve button's target). */
export const BLOCKERS_CARD_ID = "overview-blockers";

export const SUBMIT = "Submit";
export const CANCEL = "Cancel";
export const SUBMIT_DESCRIPTION = "Submitted versions can't be edited.";
export const NO_REVIEW_REQUESTS = "No Review Request sent yet";
export const READY_TITLE = "0 blockers — ready to submit";
export const READY_BODY = "Both gates are clear. Submit is now the primary action.";
export const NOTHING_YET = "Nothing blocks yet. Blockers appear as the pipeline runs.";
export const BLOCKERS_LOAD_FAILED =
  "The submission blockers could not be loaded. Try again in a moment.";
export const SUBMIT_FAILED = "Not submitted: the platform is not reachable. Try again.";
export const SUBMIT_STALE = "Not submitted: the Estimate changed since you opened it. Reload it.";
export const SUBMIT_NOT_DRAFT = "Not submitted: this version is no longer the draft. Reload it.";
export const SUBMIT_FORBIDDEN = "You can't submit this Estimate.";
/** Story 9.7: the Baseline gate's ready state. */
export const BASELINE_READY_TITLE = "0 blockers to Baseline";
export const BASELINE_READY_BODY =
  "Every requested review approved. Set Baseline is now the primary action.";

/** "Estimate v3 is the Baseline" (the gate once the version is the Baseline). */
export function isBaselineTitle(version: number): string {
  return `Estimate v${version} is the Baseline`;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "3 blockers before you can submit", or "0 blockers — ready to submit" (the polite
 * announcement when the count changes). */
export function blockersAnnouncement(count: number): string {
  return count === 0 ? READY_TITLE : `${plural(count, "blocker")} before you can submit`;
}

/** The card's pill: "3 to submit · 0 to Baseline", or "0 blockers" when nothing blocks. */
export function blockersPillLabel(view: SubmissionBlockers): string {
  const n = view.to_submit.length;
  const m = view.to_baseline.length;
  return n + m === 0 ? "0 blockers" : `${n} to submit · ${m} to Baseline`;
}

/** "Resolve 3 blockers" (the header's primary action while blocked). */
export function resolveLabel(count: number): string {
  return `Resolve ${plural(count, "blocker")}`;
}

/** "Resolve 3 blockers to submit" (the reason next to the disabled Submit). */
export function resolveToSubmitLabel(count: number): string {
  return `${resolveLabel(count)} to submit`;
}

/** "Submit Estimate v3?". */
export function submitTitle(version: number): string {
  return `Submit Estimate v${version}?`;
}

/** "Submitted Estimate v3" (announced after a submission). */
export function submittedAnnouncement(version: number): string {
  return `Submitted Estimate v${version}`;
}

const SHORT_DATE = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  timeZone: "UTC",
});

/** "Submitted v3, 14 Oct" (the Estimate tab's banner on a submitted version). */
export function submittedBanner(version: number, submittedAt: string | null | undefined): string {
  const date = submittedAt ? new Date(submittedAt) : null;
  return date && !Number.isNaN(date.getTime())
    ? `Submitted v${version}, ${SHORT_DATE.format(date)}`
    : `Submitted v${version}`;
}

/** The Overview href of the Submission blockers card. */
export function blockersCardHref(opportunityId: string): string {
  return `${tabHref(opportunityId, "overview")}#${BLOCKERS_CARD_ID}`;
}

/** One card row: every blocker of a kind, with the mockup's title, meta line and tab action. */
export type BlockerGroup = {
  kind: BlockerKind;
  title: string;
  meta: string;
  action: string;
  tab: WorkspaceTabSlug;
  items: Blocker[];
};

const KIND_ORDER: readonly BlockerKind[] = [
  "gap",
  "assumption",
  "conflict",
  "finding",
  "uncovered_requirement",
  "review_request",
  "no_review_request",
];

const GROUPS: Record<
  BlockerKind,
  { title: (n: number) => string; meta: string; action: string; tab: WorkspaceTabSlug }
> = {
  gap: {
    title: (n) => plural(n, "open Gap"),
    meta: "Answer, convert to an Assumption or dismiss each one.",
    action: "Open Gaps",
    tab: "gaps",
  },
  assumption: {
    title: (n) => `${plural(n, "Assumption")} not accepted`,
    meta: "Each needs a named accepting person.",
    action: "Open Estimate",
    tab: "estimate",
  },
  conflict: {
    title: (n) => plural(n, "open Conflict"),
    meta: "Each needs a decision.",
    action: "Open Conflicts",
    tab: "conflicts",
  },
  finding: {
    title: (n) => plural(n, "critical Finding"),
    meta: "Resolve or override each one.",
    action: "Resolve",
    tab: "assessments",
  },
  uncovered_requirement: {
    title: (n) => `${plural(n, "Requirement")} not covered`,
    meta: "No Estimate line covers them.",
    action: "Open Requirements",
    tab: "requirements",
  },
  review_request: {
    title: (n) => `${plural(n, "Review Request")} pending`,
    meta: "Each needs a reviewer's decision.",
    action: "Open Estimate",
    tab: "estimate",
  },
  no_review_request: {
    title: () => NO_REVIEW_REQUESTS,
    meta: "A Baseline needs every requested review to approve the version.",
    action: "Open Estimate",
    tab: "estimate",
  },
};

/** The blockers grouped by kind, in the API's kind order; kinds with none are left out. */
export function groupBlockers(blockers: readonly Blocker[]): BlockerGroup[] {
  return KIND_ORDER.flatMap((kind) => {
    const items = blockers.filter((b) => b.kind === kind);
    if (items.length === 0) return [];
    const group = GROUPS[kind];
    return [
      {
        kind,
        title: group.title(items.length),
        meta: group.meta,
        action: group.action,
        tab: group.tab,
        items,
      },
    ];
  });
}

/** The DOM id a blocker's `href` points at (`gap-<id>`, …), for the rows of each tab. */
export function anchorId(
  kind: "gap" | "assumption" | "conflict" | "finding" | "requirement",
  id: string,
): string {
  return `${kind}-${id}`;
}
