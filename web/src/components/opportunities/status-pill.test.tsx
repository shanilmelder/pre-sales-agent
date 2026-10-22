import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type OpportunityStatus, STATUSES } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

import { StatusPill } from "./status-pill";

const EXPECTED: [OpportunityStatus, string, string][] = [
  ["intake", "Intake", "neutral"],
  ["gaps_open", "Gaps open", "gap"],
  ["assessing", "Assessing", "agent"],
  ["estimating", "Estimating", "neutral"],
  ["in_review", "In review", "neutral"],
  ["baselined", "Baselined", "resolved"],
  ["delivered", "Delivered", "neutral"],
  ["closed", "Closed", "neutral"],
];

describe("StatusPill", () => {
  it("covers every status", () => {
    expect(EXPECTED.map(([status]) => status).sort()).toEqual(Object.keys(STATUSES).sort());
  });

  it.each(EXPECTED)("%s: icon and label, the Pill tone for %s", async (status, label, tone) => {
    const { container } = render(<StatusPill status={status} />);
    const pill = screen.getByText(label);
    expect(pill.textContent).toBe(label);
    expect(pill.getAttribute("data-slot")).toBe("pill");
    expect(pill.getAttribute("data-tone")).toBe(tone);
    // Tint fill with the tone's text, no outline.
    const classes = pill.className.split(" ");
    expect(classes).toContain("rounded-full");
    expect(classes).toContain(`bg-${tone}-tint`);
    expect(classes).toContain(`text-${tone}`);
    expect(classes).not.toContain("border");
    const icon = pill.querySelector("svg")!;
    expect(icon.parentElement?.getAttribute("aria-hidden")).toBe("true");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("baselined uses the anchor icon", () => {
    render(<StatusPill status="baselined" />);
    expect(screen.getByText("Baselined").querySelector("svg")!.getAttribute("class")).toContain(
      "lucide-anchor",
    );
  });
});
