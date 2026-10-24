import { describe, expect, it } from "vitest";

import {
  anchorId,
  blockersAnnouncement,
  blockersCardHref,
  blockersPillLabel,
  groupBlockers,
  resolveLabel,
  resolveToSubmitLabel,
  submittedBanner,
  submitTitle,
  type Blocker,
} from "@/lib/submission";

const b = (kind: Blocker["kind"], id: string): Blocker => ({
  kind,
  subject_id: id,
  title: id,
  detail: "",
  href: `#${id}`,
});

describe("submission helpers (Story 8.6)", () => {
  it("words the counts", () => {
    expect(blockersAnnouncement(3)).toBe("3 blockers before you can submit");
    expect(blockersAnnouncement(1)).toBe("1 blocker before you can submit");
    expect(blockersAnnouncement(0)).toBe("0 blockers — ready to submit");
    expect(blockersPillLabel({ to_submit: [b("gap", "g")], to_baseline: [] })).toBe(
      "1 to submit · 0 to Baseline",
    );
    expect(blockersPillLabel({ to_submit: [], to_baseline: [] })).toBe("0 blockers");
    expect(resolveLabel(2)).toBe("Resolve 2 blockers");
    expect(resolveToSubmitLabel(1)).toBe("Resolve 1 blocker to submit");
    expect(submitTitle(3)).toBe("Submit Estimate v3?");
    expect(blockersCardHref("abc")).toBe("/opportunities/abc/overview#overview-blockers");
  });

  it("names the row anchors the API's hrefs point at", () => {
    expect(anchorId("gap", "g1")).toBe("gap-g1");
    expect(anchorId("requirement", "r1")).toBe("requirement-r1");
    expect(anchorId("finding", "f1")).toBe("finding-f1");
  });

  it("dates the submitted banner in UTC", () => {
    expect(submittedBanner(3, "2026-10-14T23:30:00Z")).toBe("Submitted v3, 14 Oct");
    expect(submittedBanner(2, null)).toBe("Submitted v2");
  });

  it("groups by kind in the API's order, leaving out empty kinds", () => {
    const groups = groupBlockers([
      b("finding", "f1"),
      b("gap", "g1"),
      b("uncovered_requirement", "r1"),
      b("gap", "g2"),
    ]);
    expect(groups.map((g) => [g.kind, g.title, g.action, g.tab, g.items.length])).toEqual([
      ["gap", "2 open Gaps", "Open Gaps", "gaps", 2],
      ["finding", "1 critical Finding", "Resolve", "assessments", 1],
      ["uncovered_requirement", "1 Requirement not covered", "Open Requirements", "requirements", 1],
    ]);
    expect(groupBlockers([])).toEqual([]);
  });
});
