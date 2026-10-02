import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Preferences } from "@/lib/preferences";
import { axeViolations } from "@/test/axe";

const savePreferences = vi.hoisted(() => vi.fn());
vi.mock("@/app/settings/actions", () => ({ savePreferences }));

import { SettingsForm } from "./settings-form";

const DEFAULTS: Preferences = { theme: "system", density: "comfortable", singleKeyShortcuts: true };

beforeEach(() => {
  savePreferences.mockReset();
  savePreferences.mockResolvedValue({ ok: true });
});

describe("SettingsForm", () => {
  it("shows the stored preferences with visible labels", () => {
    render(<SettingsForm initial={{ theme: "dark", density: "compact", singleKeyShortcuts: false }} />);

    expect(screen.getByRole("group", { name: "Theme" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Density" })).toBeTruthy();
    expect((screen.getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: /Compact/ }) as HTMLInputElement).checked).toBe(true);
    const shortcuts = screen.getByRole("switch", { name: "Single-key shortcuts" });
    expect((shortcuts as HTMLInputElement).checked).toBe(false);
    expect(screen.getByText("Off")).toBeTruthy();
  });

  it("defaults: System, Comfortable, shortcuts On", () => {
    render(<SettingsForm initial={DEFAULTS} />);
    expect((screen.getByRole("radio", { name: "System" }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: /Comfortable/ }) as HTMLInputElement).checked).toBe(
      true,
    );
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("On")).toBeTruthy();
  });

  it("is fully keyboard operable and saves every change", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={DEFAULTS} />);

    // Theme: Tab into the group, arrows move and select.
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: "System" }));
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Light" }));
    await waitFor(() =>
      expect(savePreferences).toHaveBeenLastCalledWith({ ...DEFAULTS, theme: "light" }),
    );

    // Density: next tab stop is the checked radio of the next group.
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("radio", { name: /Comfortable/ }));
    await user.keyboard("{ArrowRight}");
    await waitFor(() =>
      expect(savePreferences).toHaveBeenLastCalledWith({
        theme: "light",
        density: "compact",
        singleKeyShortcuts: true,
      }),
    );

    // Shortcuts: Space toggles the switch.
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("switch", { name: "Single-key shortcuts" }));
    await user.keyboard(" ");
    await waitFor(() =>
      expect(savePreferences).toHaveBeenLastCalledWith({
        theme: "light",
        density: "compact",
        singleKeyShortcuts: false,
      }),
    );
    expect(screen.getByText("Off")).toBeTruthy();
  });

  it("can go back to System", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={{ ...DEFAULTS, theme: "light" }} />);
    await user.click(screen.getByRole("radio", { name: "System" }));
    await waitFor(() => expect(savePreferences).toHaveBeenLastCalledWith(DEFAULTS));
  });

  it.each([
    ["ok: false", () => savePreferences.mockResolvedValue({ ok: false })],
    ["a rejected action", () => savePreferences.mockRejectedValue(new Error("network"))],
  ])("on %s: announces the failure and reverts to the last saved choice", async (_label, fail) => {
    const user = userEvent.setup();
    render(<SettingsForm initial={DEFAULTS} />);

    // A successful save moves the "last saved" point to Light.
    await user.click(screen.getByRole("radio", { name: "Light" }));
    await waitFor(() => expect(savePreferences).toHaveBeenCalledTimes(1));

    fail();
    await user.click(screen.getByRole("radio", { name: "Dark" }));
    expect(await screen.findByText(/could not be saved/)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toMatch(/could not be saved/);
    await waitFor(() =>
      expect((screen.getByRole("radio", { name: "Light" }) as HTMLInputElement).checked).toBe(true),
    );
    expect((screen.getByRole("radio", { name: "Dark" }) as HTMLInputElement).checked).toBe(false);
  });

  it("clicking the switch track toggles it", async () => {
    const user = userEvent.setup();
    render(<SettingsForm initial={DEFAULTS} />);
    await user.click(screen.getByRole("switch", { name: "Single-key shortcuts" }));
    await waitFor(() =>
      expect(savePreferences).toHaveBeenLastCalledWith({ ...DEFAULTS, singleKeyShortcuts: false }),
    );
  });

  it("has no WCAG 2.1 AA violations", async () => {
    const { container } = render(<SettingsForm initial={DEFAULTS} />);
    expect(await axeViolations(container)).toEqual([]);
  });
});
