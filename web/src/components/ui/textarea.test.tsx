import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Textarea } from "./textarea";

describe("Textarea", () => {
  it("uses the surface-alt fill and border-strong outline", () => {
    render(<Textarea aria-label="Notes" />);
    const cls = screen.getByLabelText("Notes").className;
    expect(cls).toContain("bg-surface-alt");
    expect(cls).toContain("border-border-strong");
    expect(cls).not.toContain("dark:");
  });

  it("can be disabled", () => {
    render(<Textarea aria-label="Notes" disabled />);
    expect((screen.getByLabelText("Notes") as HTMLTextAreaElement).disabled).toBe(true);
  });

  it("has no axe violations", async () => {
    const { container } = render(<Textarea aria-label="Notes" />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
