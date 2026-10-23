import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";

const savePreferences = vi.hoisted(() => vi.fn());
vi.mock("@/app/settings/actions", () => ({ savePreferences }));

import { LiveRegionProvider } from "./live-region";
import { ShellProvider, useShell } from "./shell-context";
import { ShortcutHint } from "./shortcut-hint";

function Probe() {
  const { singleKeyShortcuts, firstRun } = useShell();
  return <p data-testid="probe">{`${singleKeyShortcuts}|${firstRun}`}</p>;
}

function setup(firstRun: boolean) {
  const user = userEvent.setup();
  const utils = render(
    <LiveRegionProvider>
      <ShellProvider singleKeyShortcuts={false} firstRun={firstRun}>
        <ShortcutHint />
        <Probe />
      </ShellProvider>
    </LiveRegionProvider>,
  );
  return { user, ...utils };
}

const hint = () => screen.queryByTestId("shortcut-hint");

beforeEach(() => {
  savePreferences.mockReset();
  savePreferences.mockResolvedValue({ ok: true });
});

describe("ShortcutHint", () => {
  it("shows on a first visit with Turn on and Dismiss", () => {
    setup(true);
    expect(hint()).toBeTruthy();
    expect(screen.getByRole("button", { name: "Turn on" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeTruthy();
    expect(screen.getByTestId("probe").textContent).toBe("false|true");
  });

  it("is absent once a preference is saved", () => {
    setup(false);
    expect(hint()).toBeNull();
  });

  it("Turn on saves shortcuts On and hides the hint", async () => {
    const { user } = setup(true);
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() => expect(hint()).toBeNull());
    expect(savePreferences).toHaveBeenCalledWith({
      theme: "system",
      density: "comfortable",
      singleKeyShortcuts: true,
    });
  });

  it("Dismiss saves the current defaults (Off) and hides the hint", async () => {
    const { user } = setup(true);
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(hint()).toBeNull());
    expect(savePreferences).toHaveBeenCalledWith({
      theme: "system",
      density: "comfortable",
      singleKeyShortcuts: false,
    });
  });

  it.each([
    ["ok: false", () => savePreferences.mockResolvedValue({ ok: false })],
    ["a rejected action", () => savePreferences.mockRejectedValue(new Error("network"))],
  ])("on %s: the hint stays and the failure is announced", async (_label, fail) => {
    fail();
    const { user } = setup(true);
    await user.click(screen.getByRole("button", { name: "Turn on" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toMatch(/could not be saved/),
    );
    expect(hint()).toBeTruthy();
  });

  it("has no WCAG 2.1 AA violations", async () => {
    const { container } = setup(true);
    expect(await axeViolations(container)).toEqual([]);
  });
});
