import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { VersionListItem } from "@/lib/estimates";
import { axeViolations } from "@/test/axe";
import { comparison, LINEAGE_OPP } from "@/test/lineage-fixtures";

import { ShellProviders } from "../shell/shell-context";
import { ComparePane, DiffToggle } from "./diff-toggle";

const item = (version: number, status: VersionListItem["status"], isBaseline = false): VersionListItem => ({
  id: `00000000-0000-7000-8000-00000000000${version}`,
  version,
  status,
  is_baseline: isBaseline,
  created_by_name: "Owner Person",
  created_at: "2026-10-20T09:00:00Z",
  reason: null,
});
const TARGETS = [item(2, "approved", true), item(1, "superseded")];

function renderToggle(on: boolean, singleKeyShortcuts = true) {
  const onToggle = vi.fn();
  const onChoose = vi.fn();
  const view = render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <DiffToggle on={on} against={2} targets={TARGETS} onToggle={onToggle} onChoose={onChoose} />
    </ShellProviders>,
  );
  return { ...view, onToggle, onChoose };
}

describe("DiffToggle", () => {
  it("reads Diff vs v{n} with aria-pressed, in the mockup's off and on styles", async () => {
    const { container, rerender, onToggle, onChoose } = renderToggle(false);
    const toggle = screen.getByRole("button", { name: "Diff vs v2" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(toggle.className).toContain("border-border-strong");
    expect(toggle.className).toContain("bg-surface");
    expect(toggle.className).toContain("text-[13px]");
    expect(toggle.className).toContain("font-medium");
    expect(toggle.querySelector("svg")?.getAttribute("class")).toContain("size-3.5");
    expect(await axeViolations(container)).toEqual([]);

    rerender(
      <ShellProviders singleKeyShortcuts>
        <DiffToggle on against={2} targets={TARGETS} onToggle={onToggle} onChoose={onChoose} />
      </ShellProviders>,
    );
    const pressed = screen.getByRole("button", { name: "Diff vs v2" });
    expect(pressed.getAttribute("aria-pressed")).toBe("true");
    expect(pressed.className).toContain("bg-primary-tint");
    expect(pressed.className).toContain("text-primary-text");
    expect(pressed.className).toContain("border-primary");
  });

  it("a click or d toggles it; d does nothing while typing or with shortcuts off", async () => {
    const user = userEvent.setup();
    const { onToggle, unmount } = renderToggle(false);
    await user.click(screen.getByRole("button", { name: "Diff vs v2" }));
    await user.keyboard("d");
    expect(onToggle).toHaveBeenCalledTimes(2);
    unmount();

    const off = renderToggle(false, false);
    await user.keyboard("d");
    expect(off.onToggle).not.toHaveBeenCalled();
  });

  it("the chevron menu lists every other version, the Baseline first with its anchor", async () => {
    const user = userEvent.setup();
    const { container, onChoose } = renderToggle(true);

    await user.click(screen.getByRole("button", { name: "Compare with another version" }));

    const menu = screen.getByRole("menu", { name: "Compare with" });
    const items = within(menu).getAllByRole("menuitemradio");
    expect(items.map((i) => i.textContent)).toEqual(["v2Baseline", "v1Superseded"]);
    expect(items[0]!.getAttribute("aria-checked")).toBe("true");
    expect(items[0]!.querySelector("[data-state-pill='baseline'] svg")).not.toBeNull();
    expect(document.activeElement).toBe(items[0]);
    expect(await axeViolations(container)).toEqual([]);

    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(items[1]);
    // `d` inside the menu doesn't toggle.
    await user.keyboard("{Enter}");

    expect(onChoose).toHaveBeenCalledWith(1);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("Escape closes the menu and returns focus to the chevron", async () => {
    const user = userEvent.setup();
    renderToggle(true);
    const chevron = screen.getByRole("button", { name: "Compare with another version" });
    await user.click(chevron);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(chevron);
  });
});

describe("ComparePane", () => {
  it("Compared with v{n}: Assumption and Risk changes with −/+ rows, and Why it changed", async () => {
    const { container } = render(
      <ComparePane opportunityId={LINEAGE_OPP} against={2} comparison={comparison()} />,
    );

    expect(screen.getByRole("heading", { level: 3, name: "Compared with v2" })).toBeTruthy();
    expect(await screen.findByText("Total 43.5 h → 41.0 h (−2.5 h)")).toBeTruthy();
    const assumptions = container.querySelector("[data-item-diffs='Assumptions']") as HTMLElement;
    const markers = Array.from(assumptions.querySelectorAll("[data-diff-marker]"));
    expect(markers.map((m) => m.getAttribute("data-diff-marker"))).toEqual(["−", "+"]);
    expect(markers[0]!.className).toContain("bg-diff-tint");
    expect(markers[1]!.textContent).toContain("Condition · [NEW WORDING]");
    const risks = container.querySelector("[data-item-diffs='Risks']") as HTMLElement;
    expect(risks.querySelectorAll("[data-diff-marker='+']").length).toBe(1);

    const why = container.querySelector("[data-why]") as HTMLElement;
    expect(within(why).getByRole("heading", { name: "Why it changed" })).toBeTruthy();
    const events = Array.from(why.querySelectorAll("[data-why-event]"));
    expect(events.map((e) => e.getAttribute("data-why-event"))).toEqual([
      "estimates.estimate_line.edited",
      "estimates.estimate_version.created",
    ]);
    expect(events[0]!.textContent).toContain("Estimate line edited");
    expect(events[0]!.textContent).toContain("Owner Person");
    expect(events[0]!.textContent).toContain("[WHY REASON]");
    expect(within(events[0] as HTMLElement).getByRole("link").getAttribute("href")).toBe(
      `/opportunities/${LINEAGE_OPP}/estimate`,
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when it could not be loaded", () => {
    render(<ComparePane opportunityId={LINEAGE_OPP} against={2} comparison="failed" />);
    expect(screen.getByText("The comparison could not be loaded.")).toBeTruthy();
  });
});
