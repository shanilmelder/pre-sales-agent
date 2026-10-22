import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

function Example() {
  return (
    <TooltipProvider delay={0}>
      <Tooltip>
        <TooltipTrigger render={<button type="button" />}>Info</TooltipTrigger>
        <TooltipContent>Explains the term</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

describe("Tooltip", () => {
  it("shows its content when the trigger is hovered", async () => {
    render(<Example />);
    expect(screen.queryByText("Explains the term")).toBeNull();
    await userEvent.hover(screen.getByRole("button", { name: "Info" }));
    const tip = await screen.findByText("Explains the term");
    expect(tip.className).toContain("bg-popover");
    expect(tip.className).toContain("shadow-card");
  });

  it("has no axe violations", async () => {
    const { container } = render(<Example />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
