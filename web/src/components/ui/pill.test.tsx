import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Pill } from "./pill";

describe("Pill", () => {
  it("is full radius with the label type and 2px 10px 2px 8px padding", () => {
    render(<Pill>Draft</Pill>);
    const cls = screen.getByText("Draft").className;
    expect(cls).toContain("rounded-full");
    expect(cls).toContain("text-label");
    expect(cls).toContain("text-neutral");
    expect(cls).toContain("py-0.5");
    expect(cls).toContain("pr-2.5");
    expect(cls).toContain("pl-2");
  });

  it("fills the gap tone with its tint and text colour and no outline", () => {
    render(<Pill tone="gap">Waiting for you</Pill>);
    const cls = screen.getByText("Waiting for you").className;
    expect(cls).toContain("bg-gap-tint");
    expect(cls).toContain("text-gap");
    expect(cls).not.toMatch(/\bborder|\bring|outline/);
  });

  it("supports every tone", () => {
    for (const tone of ["neutral", "resolved", "agent", "blocker", "gap"] as const) {
      const { unmount } = render(<Pill tone={tone}>{tone}</Pill>);
      expect(screen.getByText(tone).className).toContain(`bg-${tone}-tint`);
      unmount();
    }
  });

  it("renders an optional decorative icon beside the label", () => {
    render(<Pill tone="resolved" icon={<svg data-testid="icon" />}>Approved</Pill>);
    expect(screen.getByTestId("icon").parentElement?.getAttribute("aria-hidden")).toBe("true");
  });

  it("renders the neutral tint for a null tone", () => {
    render(<Pill tone={null}>Nothing</Pill>);
    const cls = screen.getByText("Nothing").className;
    expect(cls).toContain("bg-neutral-tint");
    expect(cls).toContain("text-neutral");
  });

  it("has no axe violations", async () => {
    const { container } = render(<Pill tone="blocker">Open Conflict</Pill>);
    expect(await axeViolations(container)).toEqual([]);
  });
});
