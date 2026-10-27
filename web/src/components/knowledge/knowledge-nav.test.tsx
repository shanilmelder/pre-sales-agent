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

  it("puts Graph first for the people who may open it", () => {
    render(<KnowledgeNav current="graph" showGraph />);
    const nav = screen.getByRole("navigation", { name: "Knowledge sections" });
    const links = Array.from(nav.querySelectorAll("a"));
    expect(links.map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["Graph", "/knowledge/graph"],
      ["Sources", "/knowledge"],
      ["Checklists", "/knowledge/checklists"],
      ["Coverage", "/knowledge/coverage"],
    ]);
    expect(links[0].getAttribute("aria-current")).toBe("page");
  });

  it("hides Graph unless asked", () => {
    render(<KnowledgeNav current="sources" showGraph={false} />);
    expect(screen.queryByRole("link", { name: "Graph" })).toBeNull();
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
    const { container } = render(<KnowledgeNav current="coverage" showGraph />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
