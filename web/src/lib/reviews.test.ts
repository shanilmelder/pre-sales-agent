import { describe, expect, it } from "vitest";

import {
  CY,
  recorded,
  reviewDecision,
  reviewPanel,
  reviewRequest,
} from "@/test/review-fixtures";

import {
  DECISION_STYLES,
  REVIEW_TRACE_EVENTS,
  confirmLabel,
  decisionAnnouncement,
  decisionLine,
  deltaLabel,
  diffHeading,
  isSupersededPanel,
  panelEyebrow,
  panelTitle,
  reasonLabel,
  reviewPanelHref,
  supersededLabel,
  type Decision,
} from "./reviews";

describe("Review Decisions (Story 9.3)", () => {
  it("labels the reason and the confirm button of each action", () => {
    expect(reasonLabel("rejected")).toBe("Reason for rejecting (required)");
    expect(reasonLabel("evidence_requested")).toBe("Reason for requesting evidence (required)");
    expect(reasonLabel("alternative_requested")).toBe(
      "Reason for requesting an alternative (required)",
    );
    expect(reasonLabel("escalated")).toBe("Reason for escalating (required)");
    expect(confirmLabel("rejected")).toBe("Confirm Reject");
    expect(confirmLabel("escalated")).toBe("Confirm Escalate");
  });

  it("gives every decision an icon, a tone and a label", () => {
    const decisions: Decision[] = [
      "approved",
      "rejected",
      "challenged",
      "evidence_requested",
      "alternative_requested",
      "escalated",
    ];
    expect(decisions.map((d) => [DECISION_STYLES[d].label, DECISION_STYLES[d].tone])).toEqual([
      ["Approved", "resolved"],
      ["Rejected", "blocker"],
      ["Challenged", "gap"],
      ["Evidence requested", "gap"],
      ["Alternative requested", "gap"],
      ["Escalated", "gap"],
    ]);
    for (const d of decisions) expect(DECISION_STYLES[d].icon).toBeTruthy();
  });

  it("announces what was decided", () => {
    const approve = { decision: "approved" as const, label: "Approved", reason: null };
    expect(decisionAnnouncement(recorded(approve, { status: "approved" }, "approved"))).toBe(
      "Estimate v3 approved",
    );
    expect(decisionAnnouncement(recorded(approve, { status: "approved" }))).toBe(
      "Review approved",
    );
    expect(
      decisionAnnouncement(recorded({ decision: "rejected", label: "Rejected" }, {}, "rejected")),
    ).toBe("Review rejected");
    expect(decisionAnnouncement(recorded({}, {}))).toBe("Evidence requested");
    expect(
      decisionAnnouncement(
        recorded({ decision: "escalated", label: "Escalated", escalated_to: CY }, {}),
      ),
    ).toBe("Review escalated to Cy Reviewer");
  });

  it("writes the panel header and a decision's line", () => {
    const request = reviewRequest();
    expect(panelEyebrow(request)).toBe("Engineering review · From Owner Person · 24 Oct 2026");
    expect(panelTitle(request, "[OPPORTUNITY]")).toBe(
      "Review request: Estimate v3, [OPPORTUNITY]",
    );
    expect(panelTitle(request, null)).toBe("Review request: Estimate v3");
    expect(decisionLine(reviewDecision())).toBe(
      "Ana Reviewer · Evidence requested · 25 Oct, 10:02",
    );
    expect(
      decisionLine(reviewDecision({ decision: "escalated", label: "Escalated", escalated_to: CY })),
    ).toBe("Ana Reviewer · Escalated to Cy Reviewer · 25 Oct, 10:02");
  });

  it("knows a superseded panel, the diff's words and the Open in tab link", () => {
    expect(isSupersededPanel(reviewPanel())).toBe(false);
    expect(isSupersededPanel(reviewPanel({ version_status: "superseded" }))).toBe(true);
    expect(
      isSupersededPanel(reviewPanel({ request: reviewRequest({ status: "superseded" }) })),
    ).toBe(true);
    expect(supersededLabel(4)).toBe("Superseded by v4");
    expect(supersededLabel(null)).toBe("Superseded");
    expect([deltaLabel(12), deltaLabel(-10), deltaLabel(0), deltaLabel(0.04)]).toEqual([
      "+12 h",
      "−10 h",
      "0 h",
      "0 h",
    ]);
    expect(diffHeading(reviewPanel().diff!)).toBe("Compared with v2");
    expect(diffHeading({ ...reviewPanel().diff!, first: true, previous_version: null })).toBe(
      "First version",
    );
    expect(reviewPanelHref("o", "r")).toBe("/opportunities/o/estimate/reviews/r");
  });

  it("refreshes on decisions and on the version's review outcome", () => {
    for (const event of [
      "reviews.review_decision.recorded",
      "estimates.estimate_version.approved",
      "estimates.estimate_version.rejected",
    ]) {
      expect(REVIEW_TRACE_EVENTS).toContain(event);
    }
  });
});
