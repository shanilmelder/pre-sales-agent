import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Avatar, AvatarFallback } from "./avatar";

describe("Avatar", () => {
  it("renders a human as a circle with initials", () => {
    render(
      <Avatar>
        <AvatarFallback>AB</AvatarFallback>
      </Avatar>,
    );
    expect(screen.getByText("AB")).toBeTruthy();
    const root = document.querySelector("[data-slot=avatar]");
    expect(root?.className).toContain("rounded-full");
    expect(root?.getAttribute("data-kind")).toBe("human");
  });

  it("renders an agent as a 6px-radius square", () => {
    render(
      <Avatar kind="agent">
        <AvatarFallback>EN</AvatarFallback>
      </Avatar>,
    );
    const root = document.querySelector("[data-slot=avatar]");
    expect(root?.className).toContain("rounded-sm");
    expect(root?.className).not.toContain("rounded-full");
    expect(root?.className).toContain("bg-agent-tint");
  });

  it("has no axe violations", async () => {
    const { container } = render(
      <Avatar kind="agent">
        <AvatarFallback>EN</AvatarFallback>
      </Avatar>,
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
