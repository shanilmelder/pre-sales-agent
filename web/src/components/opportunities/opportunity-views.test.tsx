import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { OpportunityViews } from "./opportunity-views";

const DUE = "/opportunities?from=2026-10-23&to=2026-11-06";

describe("OpportunityViews", () => {
  it("links All, Mine and Due in 14 days", () => {
    render(<OpportunityViews current="all" dueHref={DUE} />);
    const nav = screen.getByRole("navigation", { name: "Views" });
    expect(nav).toBeTruthy();
    expect(screen.getByRole("link", { name: "All" }).getAttribute("href")).toBe("/opportunities");
    expect(screen.getByRole("link", { name: "Mine" }).getAttribute("href")).toBe(
      "/opportunities?view=mine",
    );
    expect(screen.getByRole("link", { name: "Due in 14 days" }).getAttribute("href")).toBe(DUE);
  });

  it.each([
    ["all", "All"],
    ["mine", "Mine"],
    ["due", "Due in 14 days"],
  ] as const)("marks only %s as current", (current, label) => {
    render(<OpportunityViews current={current} dueHref={DUE} />);
    const marked = screen.getAllByRole("link").filter((l) => l.getAttribute("aria-current") === "page");
    expect(marked.map((l) => l.textContent)).toEqual([label]);
  });

  it("has no axe violations", async () => {
    const { container } = render(<OpportunityViews current="mine" dueHref={DUE} />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
