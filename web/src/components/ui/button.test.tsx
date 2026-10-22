import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";

import { Button } from "./button";

describe("Button", () => {
  it("renders the primary button at 38px with body-strong type", () => {
    render(<Button>Save</Button>);
    const cls = screen.getByRole("button", { name: "Save" }).className;
    expect(cls).toContain("h-[38px]");
    expect(cls).toContain("px-4");
    expect(cls).toContain("bg-primary");
    expect(cls).toContain("text-body-strong");
    expect(cls).toContain("text-primary-foreground");
    expect(cls).toContain("rounded-md");
  });

  it("renders the outline variant as the 32px secondary button", () => {
    render(<Button variant="outline">Cancel</Button>);
    const cls = screen.getByRole("button", { name: "Cancel" }).className;
    expect(cls).toContain("h-8");
    expect(cls).toContain("px-3");
    expect(cls).toContain("text-control");
    expect(cls).toContain("text-foreground");
    expect(cls).toContain("bg-surface");
    expect(cls).toContain("border-border-strong");
    expect(cls).not.toContain("h-[38px]");
  });

  it("is dimmed, aria-disabled and does not fire clicks when disabled", async () => {
    const onClick = vi.fn();
    render(
      <Button disabled onClick={onClick}>
        Submit
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Submit" });
    expect(button.getAttribute("aria-disabled")).toBe("true");
    expect(button.className).toContain("disabled:opacity-40");
    expect(button.className).toContain("disabled:cursor-not-allowed");
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("resets hover feedback on disabled ghost and link buttons", () => {
    render(
      <div>
        <Button variant="ghost" disabled>Ghost</Button>
        <Button variant="link" disabled>Link</Button>
      </div>,
    );
    expect(screen.getByRole("button", { name: "Ghost" }).className).toContain("disabled:hover:bg-transparent");
    expect(screen.getByRole("button", { name: "Link" }).className).toContain("disabled:hover:no-underline");
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <div>
        <Button>Save</Button>
        <Button variant="outline">Cancel</Button>
        <Button disabled>Submit</Button>
      </div>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
