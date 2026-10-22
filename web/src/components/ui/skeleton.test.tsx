import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { axeViolations } from "@/test/axe";

import { Skeleton } from "./skeleton";

describe("Skeleton", () => {
  it("is a static neutral block without animation", () => {
    const { container } = render(<Skeleton className="h-4 w-24" />);
    const el = container.querySelector("[data-slot=skeleton]");
    expect(el?.className).toContain("bg-neutral-tint");
    expect(el?.className).not.toMatch(/animate-|shimmer|pulse/);
    expect(el?.getAttribute("aria-hidden")).toBe("true");
  });

  it("has no axe violations", async () => {
    const { container } = render(<Skeleton className="h-4 w-24" />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
