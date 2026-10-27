import { describe, expect, it } from "vitest";

import {
  badgeText,
  closedStatus,
  groupItems,
  inboxLinkName,
  isGreyedReviewItem,
  itemBody,
  itemMeta,
  kindLabel,
  opportunityIdOf,
  type InboxItem,
} from "./inbox";

function item(overrides: Partial<InboxItem> = {}): InboxItem {
  return {
    id: "1",
    kind: "review_requested",
    group: "reviews",
    summary: "Review: Estimate v3 — [OPPORTUNITY]",
    opportunity_id: "o",
    opportunity_title: "[OPPORTUNITY]",
    subject_type: "reviews.review_request",
    subject_id: "r",
    subject_version: 1,
    subject_status: "pending",
    subject_status_label: "Pending",
    subject_open: true,
    sender: "[SENDER]",
    href: "/opportunities/o/estimate?review=r",
    read: false,
    created_at: "2026-10-21T10:02:00Z",
    ...overrides,
  };
}

describe("inbox helpers", () => {
  it("Story 9.5: labels Challenge items, says what they ask and styles their status", () => {
    expect(kindLabel("challenge_raised")).toBe("Challenge");
    expect(kindLabel("challenge_declined")).toBe("Challenge");
    expect(itemBody(item({ kind: "challenge_raised", sender: "Ana" }))).toBe(
      "Ana challenged this on [OPPORTUNITY]. Confirm which Assessments rerun, or decline.",
    );
    expect(itemBody(item({ kind: "challenge_declined" }))).toBe(
      "Your Challenge on [OPPORTUNITY] was declined. The reason is below.",
    );
    const declined = closedStatus(
      item({
        kind: "challenge_declined",
        subject_type: "reviews.challenge",
        subject_status: "declined",
        subject_status_label: "Declined",
        subject_open: false,
        href: null,
      }),
    );
    expect(declined?.label).toBe("Declined");
    expect(declined?.tone).toBe("neutral");
    const reassessing = closedStatus(
      item({
        subject_type: "reviews.challenge",
        subject_status: "reassessing",
        subject_status_label: "Reassessing",
        subject_open: false,
      }),
    );
    expect(reassessing?.tone).toBe("agent");
  });

  it("labels review kinds Review and the rest Update", () => {
    expect(kindLabel("review_requested")).toBe("Review");
    expect(kindLabel("review_reminder")).toBe("Review");
    expect(kindLabel("review_cancelled")).toBe("Update");
    expect(kindLabel("run_waiting")).toBe("Update");
    expect(kindLabel("conflict_escalated")).toBe("Update");
  });

  it("groups in the Inbox order and drops empty groups", () => {
    const groups = groupItems([
      item({ id: "u", group: "updates" }),
      item({ id: "r" }),
      item({ id: "w", group: "waiting" }),
    ]);
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ["Review Requests", ["r"]],
      ["Waiting for your input", ["w"]],
      ["Updates", ["u"]],
    ]);
  });

  it("builds the meta from the sender, else the Opportunity", () => {
    expect(itemMeta(item())).toBe("From [SENDER] · 21 Oct 2026, 10:02");
    expect(itemMeta(item({ sender: null }))).toBe("[OPPORTUNITY] · 21 Oct 2026, 10:02");
    expect(itemMeta(item({ sender: null, opportunity_title: null }))).toBe("21 Oct 2026, 10:02");
  });

  it("has a body sentence for every kind", () => {
    for (const kind of [
      "review_requested",
      "review_reminder",
      "review_cancelled",
      "run_waiting",
      "conflict_escalated",
    ] as const) {
      expect(itemBody(item({ kind }))).toMatch(/\.$/);
    }
  });

  it("gives a closed subject an icon and label, an open one none", () => {
    expect(closedStatus(item())).toBeNull();
    const cancelled = closedStatus(
      item({ subject_open: false, subject_status: "cancelled", subject_status_label: "Cancelled" }),
    );
    expect(cancelled?.label).toBe("Cancelled");
    expect(cancelled?.icon).toBeTruthy();
    const resolved = closedStatus(
      item({
        subject_type: "conflicts.conflict",
        subject_open: false,
        subject_status: "resolved",
        subject_status_label: "Resolved",
      }),
    );
    expect(resolved?.tone).toBe("resolved");
    expect(closedStatus(item({ subject_open: false, subject_status: null }))).toBeNull();
  });

  it("names the Inbox link with its count and caps the badge at 99+", () => {
    expect(inboxLinkName(0)).toBe("Inbox");
    expect(inboxLinkName(3)).toBe("Inbox, 3 unread");
    expect(badgeText(99)).toBe("99");
    expect(badgeText(100)).toBe("99+");
  });

  it("finds the Opportunity of a workspace path", () => {
    const id = "00000000-0000-7000-8000-000000000001";
    expect(opportunityIdOf(`/opportunities/${id}/estimate`)).toBe(id);
    expect(opportunityIdOf(`/opportunities/${id}`)).toBe(id);
    expect(opportunityIdOf("/opportunities/new")).toBeNull();
    expect(opportunityIdOf("/inbox")).toBeNull();
  });
});

describe("outcome and reply items (Story 9.4)", () => {
  it("are Review items with their own sentence", () => {
    expect(kindLabel("review_outcome")).toBe("Review");
    expect(kindLabel("review_replied")).toBe("Review");
    expect(itemBody(item({ kind: "review_outcome" }))).toBe(
      "A reviewer decided on a Review Request on [OPPORTUNITY].",
    );
    expect(itemBody(item({ kind: "review_replied" }))).toBe(
      "The author replied on a Review Request on [OPPORTUNITY].",
    );
  });

  it("grey only superseded, cancelled and handed-on subjects", () => {
    const closed = { subject_open: false, href: null };
    expect(isGreyedReviewItem(item())).toBe(false);
    for (const status of ["approved", "rejected"]) {
      expect(
        isGreyedReviewItem(item({ ...closed, kind: "review_outcome", subject_status: status })),
      ).toBe(false);
      expect(isGreyedReviewItem(item({ ...closed, subject_status: status }))).toBe(true);
    }
    for (const status of ["superseded", "cancelled"]) {
      expect(
        isGreyedReviewItem(item({ ...closed, kind: "review_outcome", subject_status: status })),
      ).toBe(true);
    }
    expect(isGreyedReviewItem(item({ ...closed, subject_status: "escalated" }))).toBe(true);
    // A reply item is the reviewer's: greyed once escalated away.
    expect(
      isGreyedReviewItem(item({ ...closed, kind: "review_replied", subject_status: "escalated" })),
    ).toBe(true);
  });
});
