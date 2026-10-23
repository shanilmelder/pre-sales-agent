import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { SegmentedNav } from "./segmented-nav";

const ITEMS = [
  { href: "/a", label: "Alpha" },
  { href: "/b", label: "Beta" },
] as const;

describe("SegmentedNav", () => {
  it("is a labelled nav that marks the current link, bold and raised", async () => {
    const { container } = render(<SegmentedNav label="Sections" items={ITEMS} current="/b" />);
    expect(screen.getByRole("navigation", { name: "Sections" })).toBeTruthy();
    const beta = screen.getByRole("link", { name: "Beta" });
    const alpha = screen.getByRole("link", { name: "Alpha" });
    expect(beta.getAttribute("aria-current")).toBe("page");
    expect(alpha.getAttribute("aria-current")).toBeNull();
    expect(beta.className).toContain("text-body-strong");
    expect(beta.className).toContain("bg-surface");
    expect(alpha.className).not.toContain("bg-surface");
    expect(alpha.getAttribute("href")).toBe("/a");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("works with a single item", () => {
    render(<SegmentedNav label="One" items={[ITEMS[0]]} current="/a" />);
    expect(screen.getByRole("link", { name: "Alpha" }).getAttribute("aria-current")).toBe("page");
  });
});
