import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";

import { Switch } from "./switch";

describe("Switch", () => {
  it("is a 44x26 full-radius switch with a 20px white knob", () => {
    render(<Switch aria-label="Single-key shortcuts" />);
    const sw = screen.getByRole("switch", { name: "Single-key shortcuts" });
    expect(sw.className).toContain("w-11");
    expect(sw.className).toContain("h-[26px]");
    expect(sw.className).toContain("rounded-full");
    expect(sw.className).toContain("bg-border-strong");
    expect(sw.className).toContain("data-checked:bg-primary");
    const thumb = document.querySelector("[data-slot=switch-thumb]");
    expect(thumb?.className).toContain("size-5");
    expect(thumb?.className).toContain("bg-white");
  });

  it("flips aria-checked and the On/Off text on click and on Space", async () => {
    const onCheckedChange = vi.fn();
    render(<Switch aria-label="Shortcuts" onCheckedChange={onCheckedChange} />);
    const sw = screen.getByRole("switch", { name: "Shortcuts" });
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText("Off")).toBeTruthy();

    await userEvent.click(sw);
    expect(sw.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("On")).toBeTruthy();

    sw.focus();
    await userEvent.keyboard(" ");
    expect(sw.getAttribute("aria-checked")).toBe("false");
    expect(screen.getByText("Off")).toBeTruthy();
    expect(onCheckedChange).toHaveBeenCalledTimes(2);
  });

  it("follows a controlled value", () => {
    render(<Switch aria-label="Shortcuts" checked onCheckedChange={() => {}} />);
    expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("On")).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = render(<Switch aria-label="Shortcuts" />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
