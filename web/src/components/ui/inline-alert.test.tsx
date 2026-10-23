import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";

import { InlineAlert } from "./inline-alert";

describe("InlineAlert", () => {
  it("is an alert with Reload and, when given, View diff", async () => {
    const onReload = vi.fn();
    const onViewDiff = vi.fn();
    const { container } = render(
      <InlineAlert lead="Someone changed it." onReload={onReload} onViewDiff={onViewDiff}>
        <p>detail</p>
      </InlineAlert>,
    );
    expect(screen.getByRole("alert").textContent).toContain("Someone changed it.");
    expect(screen.getByText("detail")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Reload" }));
    await userEvent.click(screen.getByRole("button", { name: "View diff" }));
    expect(onReload).toHaveBeenCalledOnce();
    expect(onViewDiff).toHaveBeenCalledOnce();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("forwards reloadRef to the Reload button", () => {
    const reloadRef = { current: null as HTMLButtonElement | null };
    render(<InlineAlert lead="x" onReload={() => {}} reloadRef={reloadRef} />);
    expect(reloadRef.current).toBe(screen.getByRole("button", { name: "Reload" }));
  });

  it("omits View diff without a handler", () => {
    render(<InlineAlert lead="x" onReload={() => {}} />);
    expect(screen.queryByRole("button", { name: "View diff" })).toBeNull();
    expect(screen.getByRole("alert").className).toContain("bg-blocker-tint");
  });
});
