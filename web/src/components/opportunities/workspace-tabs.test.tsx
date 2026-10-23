import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  permissions: ["identity.user.search", "opportunities.opportunity.create"],
};

function tree(
  children: ReactNode = <p>Tab body</p>,
  singleKeyShortcuts = true,
  counts: Record<string, number> = {},
) {
  return (
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <AppShell me={ME}>
        <WorkspaceTabs id={ID} counts={counts}>
          {children}
        </WorkspaceTabs>
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

  it("the Conflicts tab shows its open count after the label, none at 0", async () => {
    const { container, rerender } = render(tree(undefined, true, { conflicts: 3 }));
    const conflicts = screen.getByRole("tab", { name: "Conflicts, 3 open" });
    expect(within(conflicts).getByTestId("tab-count-conflicts").textContent).toBe("3, 3 open");
    expect(await axeViolations(container)).toEqual([]);
    rerender(tree(undefined, true, { conflicts: 0 }));
    expect(screen.getByRole("tab", { name: "Conflicts" })).toBeTruthy();
    expect(screen.queryByTestId("tab-count-conflicts")).toBeNull();
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

describe("the live Gaps badge (Story 4.7)", () => {
  class FakeSource {
    static last: FakeSource | null = null;
    readonly listeners = new Map<string, (() => void)[]>();
    constructor(readonly url: string) {
      FakeSource.last = this;
    }
    addEventListener(type: string, listener: () => void) {
      this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
    }
    close() {}
    emit(type: string) {
      for (const listener of this.listeners.get(type) ?? []) listener();
    }
  }

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("follows gaps.changed frames with the open Gap count", async () => {
    vi.stubGlobal("EventSource", FakeSource);
    const loadGapCount = vi.fn(async () => 2);
    render(
      <ShellProviders singleKeyShortcuts>
        <AppShell me={ME}>
          <WorkspaceTabs id={ID} counts={{ gaps: 3 }} loadGapCount={loadGapCount}>
            <p>Tab body</p>
          </WorkspaceTabs>
        </AppShell>
      </ShellProviders>,
    );
    expect(screen.getByTestId("tab-count-gaps").textContent).toBe("3, 3 open");

    await act(async () => FakeSource.last!.emit("gaps.changed"));

    expect(loadGapCount).toHaveBeenCalledWith(ID);
    expect(screen.getByTestId("tab-count-gaps").textContent).toBe("2, 2 open");
    expect(FakeSource.last!.url).toBe(`/api/opportunities/${ID}/events`);
  });

  it("follows conflicts.changed frames with the open Conflict count (Story 6.2)", async () => {
    vi.stubGlobal("EventSource", FakeSource);
    const loadGapCount = vi.fn(async () => 3);
    const loadConflictCount = vi.fn(async () => 1);
    render(
      <ShellProviders singleKeyShortcuts>
        <AppShell me={ME}>
          <WorkspaceTabs
            id={ID}
            counts={{ gaps: 3 }}
            loadGapCount={loadGapCount}
            loadConflictCount={loadConflictCount}
          >
            <p>Tab body</p>
          </WorkspaceTabs>
        </AppShell>
      </ShellProviders>,
    );
    expect(screen.queryByTestId("tab-count-conflicts")).toBeNull();

    await act(async () => FakeSource.last!.emit("conflicts.changed"));

    expect(loadConflictCount).toHaveBeenCalledWith(ID);
    expect(loadGapCount).not.toHaveBeenCalled();
    expect(screen.getByTestId("tab-count-conflicts").textContent).toBe("1, 1 open");
    expect(screen.getByTestId("tab-count-gaps").textContent).toBe("3, 3 open");
  });
});

describe("the connection status bar (Story 2.3)", () => {
  class FakeSource {
    static last: FakeSource | null = null;
    readonly listeners = new Map<string, ((event?: unknown) => void)[]>();
    readyState = 0;
    constructor(readonly url: string) {
      FakeSource.last = this;
    }
    addEventListener(type: string, listener: (event?: unknown) => void) {
      this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
    }
    close() {
      this.readyState = 2;
    }
    emit(type: string) {
      if (type === "open") this.readyState = 1;
      for (const listener of this.listeners.get(type) ?? []) listener({ type });
    }
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("EventSource", FakeSource);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function body() {
    return (
      <>
        <button type="button">Save changes</button>
        <input aria-label="Filter" />
        <a href="https://example.invalid/elsewhere">Elsewhere</a>
      </>
    );
  }

  it("reads Reconnecting… from the first drop, then Offline — edits disabled at 60 s, and clears on reconnect", async () => {
    const { container } = render(tree(body()));
    const bar = screen.getByTestId("connection-status");
    expect(bar.getAttribute("role")).toBe("status");
    expect(bar.getAttribute("aria-live")).toBe("polite");
    expect(bar.textContent).toBe(""); // connecting: no bar

    await act(async () => FakeSource.last!.emit("open"));
    expect(bar.textContent).toBe("");

    FakeSource.last!.readyState = 0; // the browser retries by itself
    await act(async () => FakeSource.last!.emit("error"));
    expect(bar.textContent).toBe("Reconnecting…");
    expect(screen.getByRole("button", { name: "Save changes" }).matches(":disabled")).toBe(false);

    await act(async () => vi.advanceTimersByTime(60_000));
    expect(bar.textContent).toBe(""); // the Offline strip owns the text now
    const strip = screen.getByTestId("offline-strip");
    expect(strip.getAttribute("aria-live")).toBe("polite");
    expect(strip.textContent).toContain("Offline — edits disabled");
    // The tab panel's controls go inert; links and the tabs still work.
    expect(screen.getByRole("button", { name: "Save changes" }).matches(":disabled")).toBe(true);
    expect(screen.getByRole("textbox", { name: "Filter" }).matches(":disabled")).toBe(true);
    expect(screen.getByRole("group", { name: "Edits disabled while offline" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Elsewhere" }).getAttribute("href")).toBe(
      "https://example.invalid/elsewhere",
    );
    for (const tab of tabs()) expect(tab.getAttribute("aria-disabled")).toBeNull();
    vi.useRealTimers();
    expect(await axeViolations(container)).toEqual([]);
    vi.useFakeTimers();

    await act(async () => FakeSource.last!.emit("open"));
    expect(bar.textContent).toBe("");
    expect(screen.getByTestId("offline-strip").textContent).toBe("");
    expect(screen.getByRole("button", { name: "Save changes" }).matches(":disabled")).toBe(false);
  });

  it("Retry in the strip reopens the stream at once and the strip goes when it opens", async () => {
    render(tree(body()));
    await act(async () => FakeSource.last!.emit("open"));
    FakeSource.last!.readyState = 0;
    await act(async () => FakeSource.last!.emit("error"));
    await act(async () => vi.advanceTimersByTime(60_000));
    const before = FakeSource.last!;
    const strip = screen.getByTestId("offline-strip");

    await act(async () => within(strip).getByRole("button", { name: "Retry" }).click());
    expect(FakeSource.last).not.toBe(before);
    expect(before.readyState).toBe(2);
    expect(document.activeElement).toBe(screen.getByRole("main"));
    expect(strip.textContent).toContain("Offline"); // still down until it opens

    await act(async () => FakeSource.last!.emit("open"));
    expect(strip.textContent).toBe("");
  });

  it("the strip goes when the workspace unmounts", async () => {
    const view = render(tree(body()));
    await act(async () => FakeSource.last!.emit("open"));
    FakeSource.last!.readyState = 0;
    await act(async () => FakeSource.last!.emit("error"));
    await act(async () => vi.advanceTimersByTime(60_000));
    expect(screen.getByTestId("offline-strip").textContent).toContain("Offline");
    view.rerender(
      <ShellProviders singleKeyShortcuts>
        <AppShell me={ME}>
          <p>Elsewhere page</p>
        </AppShell>
      </ShellProviders>,
    );
    expect(screen.getByTestId("offline-strip").textContent).toBe("");
  });
});

describe("read-only below 1024px (Story 17.2c)", () => {
  let matches = false;
  const listeners = new Set<() => void>();

  beforeEach(() => {
    matches = false;
    listeners.clear();
    vi.stubGlobal("matchMedia", (query: string) => ({
      get matches() {
        return matches;
      },
      media: query,
      addEventListener: (_: string, l: () => void) => listeners.add(l),
      removeEventListener: (_: string, l: () => void) => listeners.delete(l),
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const body = () => (
    <>
      <button type="button">Save</button>
      <input aria-label="Filter" />
    </>
  );

  it("disables the workspace controls when narrow and enables them when wide again", async () => {
    matches = true;
    const { container } = render(tree(body()));
    expect(screen.getByRole("button", { name: "Save" }).matches(":disabled")).toBe(true);
    expect(screen.getByRole("textbox", { name: "Filter" }).matches(":disabled")).toBe(true);
    expect(screen.getByTestId("read-only-notice")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Edits disabled on a narrow screen" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    matches = false;
    await act(async () => listeners.forEach((l) => l()));
    expect(screen.getByRole("button", { name: "Save" }).matches(":disabled")).toBe(false);
  });

  it("leaves the controls enabled at 1024px and wider", () => {
    render(tree(body()));
    expect(screen.getByRole("button", { name: "Save" }).matches(":disabled")).toBe(false);
  });
});
