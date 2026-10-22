import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Chip } from "./chip";

describe("Chip", () => {
  it("is the evidence chip: primary-text on surface with a border-strong outline", () => {
    render(<Chip>S2 · email-it-systems</Chip>);
    const cls = screen.getByText("S2 · email-it-systems").className;
    for (const token of [
      "text-primary-text",
      "bg-surface",
      "border-border-strong",
      "rounded-sm",
      "px-2",
      "py-0.5",
    ]) {
      expect(cls).toContain(token);
    }
  });

  it("has no axe violations", async () => {
    const { container } = render(<Chip>S2 · email-it-systems</Chip>);
    expect(await axeViolations(container)).toEqual([]);
  });
});
