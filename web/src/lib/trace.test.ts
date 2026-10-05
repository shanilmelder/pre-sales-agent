import { describe, expect, it } from "vitest";

import {
  absoluteTime,
  actorText,
  eventLabel,
  EVENT_LABELS,
  fieldLabel,
  fieldValue,
  pageCount,
  parseTraceFilters,
  relativeTime,
  subjectHref,
  subjectLinkText,
  subjectText,
  traceHref,
  withTraceFilter,
} from "@/lib/trace";

const OPP = "00000000-0000-7000-8000-000000000001";
const NOW = Date.parse("2026-10-05T12:00:00Z");

describe("labels", () => {
  it("names catalogued events in words and falls back to the raw type", () => {
    expect(eventLabel("estimates.assumption.accepted")).toBe(
      "Assumption accepted",
    );
    expect(eventLabel("intake.source.parsed")).toBe("Source parsed");
    expect(eventLabel("estimates.estimate_version.exported")).toBe("Estimate exported");
    expect(eventLabel("brand.new.happened")).toBe("brand.new.happened");
    for (const [type, label] of Object.entries(EVENT_LABELS)) {
      expect(type).toMatch(/^[a-z_]+\.[a-z_]+\.[a-z_]+$/);
      expect(label).not.toBe("");
    }
  });

  it.each([
    ["intake.requirement", "requirements"],
    ["intake.extraction", "requirements"],
    ["gaps.gap", "gaps"],
    ["gaps.clarification_question", "gaps"],
    ["gaps.detection", "gaps"],
    ["estimates.estimate_version", "estimate"],
    ["estimates.assumption", "estimate"],
    ["assessments.review", "assessments"],
    ["intake.source", "sources"],
    ["opportunities.opportunity", "overview"],
  ])("links %s to the %s tab", (type, tab) => {
    expect(subjectHref(OPP, type)).toBe(`/opportunities/${OPP}/${tab}`);
  });

  it("names the inspector's link after the tab", () => {
    expect(subjectLinkText("estimates.assumption")).toBe("Open in Estimate");
    expect(subjectLinkText("gaps.clarification_question")).toBe("Open in Gaps");
    expect(subjectLinkText("identity.user")).toBeNull();
  });

  it("has no link for a subject without a tab", () => {
    expect(subjectHref(OPP, "identity.user")).toBeNull();
    expect(subjectHref(OPP, "unknown.thing")).toBeNull();
  });

  it("shows the subject with its version", () => {
    expect(
      subjectText({ type: "estimates.estimate_version", id: "x", version: 2 }),
    ).toBe("Estimate Version v2");
    expect(subjectText({ type: "gaps.gap", id: "x", version: null })).toBe(
      "Gap",
    );
    expect(subjectText({ type: "odd.type", id: "x", version: null })).toBe(
      "odd.type",
    );
  });

  it("shows an agent's version, not a person's", () => {
    expect(
      actorText({
        type: "agent",
        id: "a@1.0.0",
        name: "PM Agent",
        version: "1.0.0",
      }),
    ).toBe("PM Agent (v1.0.0)");
    expect(
      actorText({ type: "user", id: "u", name: "[NAME]", version: null }),
    ).toBe("[NAME]");
    expect(actorText({ type: "system", id: "s", name: "System" })).toBe(
      "System",
    );
  });

  it("names payload fields and values", () => {
    expect(fieldLabel("gap_count")).toBe("Gap count");
    expect(fieldLabel("line_id")).toBe("Line id");
    expect(fieldLabel("amount_hours")).toBe("Amount (hours)");
    expect(fieldValue(null)).toBe("None");
    expect(fieldValue([])).toBe("None");
    expect(fieldValue(["a", "b"])).toBe("a, b");
    expect(fieldValue(true)).toBe("Yes");
    expect(fieldValue(16.5)).toBe("16.5");
    expect(fieldValue({ a: 1 })).toBe('{"a":1}');
  });
});

describe("times", () => {
  it("formats absolute times in UTC, with seconds", () => {
    expect(absoluteTime("2026-10-05T09:04:07Z")).toBe(
      "5 Oct 2026, 09:04:07 UTC",
    );
    expect(absoluteTime("nope")).toBe("nope");
  });

  it.each([
    ["2026-10-05T11:59:30Z", "just now"],
    ["2026-10-05T11:55:00Z", "5 min ago"],
    ["2026-10-05T09:00:00Z", "3 h ago"],
    ["2026-10-01T12:00:00Z", "4 d ago"],
    ["2026-08-01T12:00:00Z", "1 Aug 2026, 12:00:00 UTC"],
    ["2026-10-05T13:00:00Z", "5 Oct 2026, 13:00:00 UTC"],
  ])("%s is %s", (at, text) => {
    expect(relativeTime(at, NOW)).toBe(text);
  });
});

describe("URL state", () => {
  it("reads the filters from the URL, ignoring blank and overlong ones", () => {
    expect(
      parseTraceFilters({
        actor: "agent",
        subject: " ",
        event: ["a.b.c", "x"],
      }),
    ).toEqual({
      actor: "agent",
      event: "a.b.c",
    });
    expect(parseTraceFilters({ subject: "x".repeat(201) })).toEqual({});
    expect(parseTraceFilters(undefined)).toEqual({});
  });

  it("writes the filters and page back, leaving page 1 out", () => {
    expect(traceHref(OPP, {})).toBe(`/opportunities/${OPP}/trace`);
    expect(
      traceHref(
        OPP,
        { event: "estimates.assumption.accepted", actor: "user" },
        3,
      ),
    ).toBe(
      `/opportunities/${OPP}/trace?actor=user&event=estimates.assumption.accepted&page=3`,
    );
    expect(withTraceFilter({ actor: "agent" }, "actor", "")).toEqual({});
    expect(withTraceFilter({}, "subject", "gaps.gap")).toEqual({
      subject: "gaps.gap",
    });
  });

  it("counts pages", () => {
    expect(pageCount({ total: 0, page_size: 50 })).toBe(1);
    expect(pageCount({ total: 120, page_size: 50 })).toBe(3);
  });
});
