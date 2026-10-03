import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type OpportunityStatus, STATUSES } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

import { StatusPill } from "./status-pill";

const EXPECTED: [OpportunityStatus, string, string][] = [
  ["intake", "Intake", "text-muted-foreground"],
  ["gaps_open", "Gaps open", "text-gap"],
  ["assessing", "Assessing", "text-agent"],
  ["estimating", "Estimating", "text-muted-foreground"],
  ["in_review", "In review", "text-muted-foreground"],
  ["baselined", "Baselined", "text-resolved"],
  ["delivered", "Delivered", "text-muted-foreground"],
  ["closed", "Closed", "text-muted-foreground"],
];

describe("StatusPill", () => {
  it("covers every status", () => {
    expect(EXPECTED.map(([status]) => status).sort()).toEqual(Object.keys(STATUSES).sort());
  });

  it.each(EXPECTED)("%s: icon and label, the icon in %s", async (status, label, tone) => {
    const { container } = render(<StatusPill status={status} />);
    const pill = screen.getByText(label);
    expect(pill.textContent).toBe(label);
    // 20px, fully rounded, neutral outline, label in the foreground colour.
    for (const cls of ["h-5", "rounded-full", "border-border", "text-foreground"]) {
      expect(pill.className.split(" ")).toContain(cls);
    }
    const icon = pill.querySelector("svg")!;
    expect(icon.getAttribute("aria-hidden")).toBe("true");
    expect(icon.getAttribute("class")).toContain(tone);
    // Only the icon is tinted.
    expect(pill.className).not.toMatch(/text-(gap|agent|resolved)/);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("baselined uses the anchor icon", () => {
    render(<StatusPill status="baselined" />);
    expect(screen.getByText("Baselined").querySelector("svg")!.getAttribute("class")).toContain(
      "lucide-anchor",
    );
  });
});
