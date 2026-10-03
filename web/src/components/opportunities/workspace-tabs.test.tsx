import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Me } from "@/lib/api/server";
import { axeViolations } from "@/test/axe";

const push = vi.hoisted(() => vi.fn());
const replace = vi.hoisted(() => vi.fn());
const segment = vi.hoisted(() => ({ current: null as string | null }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x",
  useSelectedLayoutSegment: () => segment.current,
}));

import { AppShell } from "../shell/app-shell";
import { ShellProviders } from "../shell/shell-context";
import { WorkspaceTabs } from "./workspace-tabs";

const ID = "00000000-0000-7000-8000-000000000001";
const SLUGS = [
  "overview",
  "sources",
  "requirements",
  "gaps",
  "assessments",
  "conflicts",
  "estimate",
  "trace",
  "actuals",
];
const LABELS = [
  "Overview",
  "Sources",
  "Requirements",
  "Gaps",
  "Assessments",
  "Conflicts",
  "Estimate",
  "Trace",
  "Actuals",
];

const ME: Me = {
  id: "00000000-0000-7000-8000-000000000000",
  name: "[USER]",
  email: "user@example.invalid",
  roles: ["presales_engineer"],
};

function tree(children: ReactNode = <p>Tab body</p>, singleKeyShortcuts = true) {
  return (
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <AppShell me={ME}>
        <WorkspaceTabs id={ID}>{children}</WorkspaceTabs>
      </AppShell>
    </ShellProviders>
  );
}

const tabs = () => within(screen.getByRole("tablist", { name: "Opportunity workspace" })).getAllByRole("tab");
const selected = () => tabs().filter((t) => t.getAttribute("aria-selected") === "true");

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  segment.current = null;
});

describe("WorkspaceTabs", () => {
  it("lists the nine tabs in order, each a link with its number and slug URL", () => {
    render(tree());
    const all = tabs();
    expect(all.map((t) => t.textContent)).toEqual(LABELS.map((label, i) => `${i + 1}${label}`));
    expect(all.map((t) => t.getAttribute("href"))).toEqual(
      SLUGS.map((slug) => `/opportunities/${ID}/${slug}`),
    );
    for (const tab of all) expect(tab.tagName).toBe("A");
  });

  it("/opportunities/{id} selects Overview with the primary underline; the panel is labelled by it", () => {
    render(tree());
    expect(selected()).toHaveLength(1);
    const overview = screen.getByRole("tab", { name: "Overview" });
    expect(overview.getAttribute("aria-selected")).toBe("true");
    expect(overview.className).toContain("border-b-2");
    expect(overview.className).toContain("border-primary");
    expect(screen.getByRole("tab", { name: "Gaps" }).className).toContain("border-transparent");
    const panel = screen.getByRole("tabpanel", { name: "Overview" });
    expect(within(panel).getByText("Tab body")).toBeTruthy();
  });

  it("a tab URL selects that tab", () => {
    segment.current = "gaps";
    render(tree());
    expect(selected().map((t) => t.textContent)).toEqual(["4Gaps"]);
  });

  it("no tab is hidden or disabled", () => {
    render(tree());
    for (const tab of tabs()) {
      expect(tab.getAttribute("aria-disabled")).toBeNull();
      expect(tab.hidden).toBe(false);
    }
  });

  it("pressing 1–9 follows each key; push keeps history so Back returns to the previous tab", async () => {
    const user = userEvent.setup();
    const { rerender } = render(tree());
    for (let n = 1; n <= 9; n++) {
      await user.keyboard(String(n));
      const href = `/opportunities/${ID}/${SLUGS[n - 1]}`;
      expect(push).toHaveBeenLastCalledWith(href);
      // The router lands on the tab's route.
      segment.current = SLUGS[n - 1]!;
      rerender(tree());
      expect(selected().map((t) => t.getAttribute("href"))).toEqual([href]);
    }
    expect(push).toHaveBeenCalledTimes(9);
    expect(replace).not.toHaveBeenCalled();
  });

  it("4 on Overview goes to Gaps", async () => {
    const user = userEvent.setup();
    render(tree());
    await user.keyboard("4");
    expect(push).toHaveBeenCalledWith(`/opportunities/${ID}/gaps`);
  });

  it("digits are ignored in a text field and with single-key shortcuts off", async () => {
    const user = userEvent.setup();
    const typing = render(tree(<input aria-label="Search people" />));
    await user.click(screen.getByRole("textbox", { name: "Search people" }));
    await user.keyboard("4");
    // Shortcuts on: each tab announces its key.
    expect(tabs().map((t) => t.getAttribute("aria-keyshortcuts"))).toEqual(
      SLUGS.map((_, i) => String(i + 1)),
    );
    typing.unmount();
    render(tree(undefined, false));
    await user.keyboard("4");
    expect(push).not.toHaveBeenCalled();
    // Shortcuts off: no key is announced.
    for (const tab of tabs()) expect(tab.getAttribute("aria-keyshortcuts")).toBeNull();
  });

  it("arrow keys, Home and End move focus along the strip (roving tabindex)", async () => {
    const user = userEvent.setup();
    render(tree());
    const all = tabs();
    expect(all.filter((t) => t.tabIndex === 0)).toEqual([all[0]]);
    all[0]!.focus();
    await user.keyboard("{ArrowRight}");
    expect(document.activeElement).toBe(all[1]);
    await user.keyboard("{ArrowLeft}{ArrowLeft}");
    expect(document.activeElement).toBe(all[8]);
    await user.keyboard("{Home}");
    expect(document.activeElement).toBe(all[0]);
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(all[8]);
  });

  it("has no WCAG 2.1 AA violations", async () => {
    segment.current = "estimate";
    const { container } = render(tree());
    expect(await axeViolations(container)).toEqual([]);
  });
});
