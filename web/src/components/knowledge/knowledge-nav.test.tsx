import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { KnowledgeNav } from "./knowledge-nav";

describe("KnowledgeNav", () => {
  it("reads Sources, Checklists, Coverage, in that order", () => {
    render(<KnowledgeNav current="sources" />);
    const nav = screen.getByRole("navigation", { name: "Knowledge sections" });
    const links = Array.from(nav.querySelectorAll("a"));
    expect(links.map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["Sources", "/knowledge"],
      ["Checklists", "/knowledge/checklists"],
      ["Coverage", "/knowledge/coverage"],
    ]);
  });

  it.each(["sources", "checklists", "coverage"] as const)("marks only %s as current", (tab) => {
    render(<KnowledgeNav current={tab} />);
    const current = screen
      .getAllByRole("link")
      .filter((l) => l.getAttribute("aria-current") === "page");
    expect(current.map((l) => l.textContent?.toLowerCase())).toEqual([tab]);
    expect(current[0].className).toContain("bg-surface");
  });

  it("has no axe violations", async () => {
    const { container } = render(<KnowledgeNav current="coverage" />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
