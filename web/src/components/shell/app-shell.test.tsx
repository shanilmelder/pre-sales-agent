import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { permissionsFor } from "@/test/permissions";

import type { Me } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { SEQUENCE_TIMEOUT_MS, SHORTCUTS, type Shortcut } from "@/lib/shortcuts";
import { axeViolations } from "@/test/axe";

const push = vi.hoisted(() => vi.fn());
const pathname = vi.hoisted(() => ({ current: "/inbox" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => pathname.current,
}));

import { AppShell, PlaceholderPage } from "./app-shell";
import { READ_ONLY_MESSAGE } from "./read-only-notice";
import { ShellProviders, useWorkspaceTabKeys } from "./shell-context";

const TAB_HREFS = Array.from({ length: 9 }, (_, i) => `/tab-${i + 1}`);

/** Stands in for the Opportunity workspace's tab strip: registers `1`–`9`. */
function Workspace({ children }: { children?: ReactNode }) {
  useWorkspaceTabKeys(TAB_HREFS);
  return <>{children}</>;
}

function me(roles: Role[]): Me {
  return {
    id: "00000000-0000-7000-8000-000000000000",
    name: "[USER]",
    email: "user@example.invalid",
    roles,
    permissions: permissionsFor(roles),
  };
}

/** Base UI moves focus into a dialog (and through its focus guards) asynchronously. */
async function expectFocusIn(element: Element) {
  await waitFor(() => expect(element.contains(document.activeElement)).toBe(true));
}

function renderShell({
  roles = ["presales_engineer"] as Role[],
  singleKeyShortcuts = true,
  children = <PlaceholderPage title="Inbox" message="Nothing waiting for you." />,
}: { roles?: Role[]; singleKeyShortcuts?: boolean; children?: ReactNode } = {}) {
  const user = userEvent.setup();
  // The providers stand in for the root layout.
  const utils = render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <AppShell me={me(roles)}>{children}</AppShell>
    </ShellProviders>,
  );
  return { user, ...utils };
}

const palette = () => screen.queryByRole("dialog", { name: "Command palette" });
const cheatSheet = () => screen.queryByRole("dialog", { name: "Keyboard shortcuts" });
const rightPane = () => screen.queryByRole("complementary", { name: "Details" });
const sidebar = () => screen.getByRole("navigation", { name: "Primary" });

beforeEach(() => {
  push.mockReset();
  pathname.current = "/inbox";
});

afterEach(() => vi.restoreAllMocks());

describe("AppShell layout", () => {
  it("has one Primary nav, one main and one polite live region", () => {
    const { container } = renderShell();
    expect(screen.getAllByRole("navigation", { name: "Primary" })).toHaveLength(1);
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(document.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
    expect(container.querySelectorAll("nav")).toHaveLength(1);
  });

  it("lists the nav items in order and hides Admin from non-admins", () => {
    renderShell({ roles: ["pm_reviewer"] });
    const links = within(sidebar())
      .getAllByRole("link")
      .map((a) => a.textContent);
    expect(links).toEqual([
      "Inbox",
      "My Opportunities",
      "All Opportunities",
      "Knowledge",
      "Reports",
    ]);
  });

  it("shows Admin to platform administrators", () => {
    renderShell({ roles: ["platform_administrator"] });
    expect(within(sidebar()).getByRole("link", { name: "Admin" }).getAttribute("href")).toBe(
      "/admin",
    );
  });

  it("marks the current page and keeps the avatar menu in the sidebar", () => {
    renderShell();
    expect(
      within(sidebar()).getByRole("link", { name: "Inbox" }).getAttribute("aria-current"),
    ).toBe("page");
    expect(
      within(sidebar()).getByRole("button", { name: "Account menu for [USER]" }),
    ).toBeTruthy();
  });

  it("uses the responsive tier classes", () => {
    renderShell();
    // 1024-1279: icons only; 1280+: 220px with labels.
    expect(sidebar().className).toContain("w-12");
    expect(sidebar().className).toContain("min-[1280px]:w-sidebar");
    expect(within(sidebar()).getByText("Inbox").className).toContain(
      "min-[1280px]:not-sr-only",
    );
  });

  it("below 1024px shows the read-only notice, and navigation still works", async () => {
    const { user } = renderShell();
    const notice = screen.getByText(READ_ONLY_MESSAGE);
    expect(notice.className).toContain("min-[1024px]:hidden");
    expect(READ_ONLY_MESSAGE).toBe(
      "The workbench needs a wider screen. You can view Opportunities here, but editing is disabled.",
    );
    expect(within(sidebar()).getAllByRole("link").length).toBeGreaterThan(0);
    await user.keyboard("gr");
    expect(push).toHaveBeenCalledWith("/reports");
  });

  it("has no WCAG 2.1 AA violations (including the read-only notice)", async () => {
    const { container } = renderShell();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("right pane", () => {
  it("] toggles it; it overlays below 1440px and docks at 1440px", async () => {
    const { user } = renderShell();
    expect(rightPane()).toBeNull();
    await user.keyboard("]");
    const pane = rightPane()!;
    expect(pane).toBeTruthy();
    expect(pane.className).toContain("absolute");
    expect(pane.className).toContain("min-[1440px]:static");
    await user.keyboard("]");
    expect(rightPane()).toBeNull();
  });

  it("has visible controls to open and close it", async () => {
    const { user } = renderShell();
    await user.click(screen.getByRole("button", { name: "Right pane" }));
    expect(rightPane()).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Close right pane" }));
    expect(rightPane()).toBeNull();
  });

  it("announces opening through the live region", async () => {
    const { user } = renderShell();
    await user.keyboard("]");
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Right pane opened"),
    );
  });

  it("open: no WCAG 2.1 AA violations", async () => {
    const { user, container } = renderShell();
    await user.keyboard("]");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tab order runs sidebar, then main, then right pane", async () => {
    const { user } = renderShell({ children: <a href="/x">Main link</a> });
    await user.keyboard("]");
    (document.activeElement as HTMLElement | null)?.blur();
    const nav = sidebar();
    const main = screen.getByRole("main");
    const pane = rightPane()!;
    const regions: string[] = [];
    for (let i = 0; i < 30; i++) {
      await user.tab();
      const el = document.activeElement;
      if (!el || el === document.body) break;
      const region = nav.contains(el)
        ? "sidebar"
        : main.contains(el)
          ? "main"
          : pane.contains(el)
            ? "pane"
            : "other";
      if (regions.at(-1) !== region) regions.push(region);
      if (region === "pane") break;
    }
    expect(regions).toEqual(["sidebar", "main", "pane"]);
  });
});

describe("sidebar collapse", () => {
  it("[ and the visible control collapse and expand it", async () => {
    const { user } = renderShell();
    expect(sidebar().getAttribute("data-collapsed")).toBe("false");
    await user.keyboard("[[");
    expect(sidebar().getAttribute("data-collapsed")).toBe("true");
    expect(sidebar().className).not.toContain("min-[1280px]:w-sidebar");
    await user.click(within(sidebar()).getByRole("button", { name: "Collapse sidebar" }));
    expect(sidebar().getAttribute("data-collapsed")).toBe("false");
  });
});

describe("command palette", () => {
  it("Ctrl+K, type 'know', Enter: navigates to Knowledge and closes", async () => {
    const { user } = renderShell();
    await user.keyboard("{Control>}k{/Control}");
    expect(palette()).toBeTruthy();
    await user.keyboard("know");
    await user.keyboard("{Enter}");
    expect(push).toHaveBeenCalledWith("/knowledge");
    expect(palette()).toBeNull();
  });

  it("Cmd+K opens it too", async () => {
    const { user } = renderShell();
    await user.keyboard("{Meta>}k{/Meta}");
    expect(palette()).toBeTruthy();
  });

  it("lists navigation and Settings; Admin only for admins", async () => {
    const options = () =>
      within(palette()!)
        .getAllByRole("option")
        .map((o) => o.textContent);
    const { user, unmount } = renderShell({ roles: ["pm_reviewer"] });
    await user.keyboard("{Control>}k{/Control}");
    expect(options()).toEqual([
      "Inbox",
      "My Opportunities",
      "All Opportunities",
      "Knowledge",
      "Reports",
      "Settings",
    ]);
    unmount();
    const admin = renderShell({ roles: ["platform_administrator"] });
    await admin.user.keyboard("{Control>}k{/Control}");
    expect(options()).toContain("Admin");
  });

  it("fuzzy-filters as you type", async () => {
    const { user } = renderShell();
    await user.keyboard("{Control>}k{/Control}");
    await user.keyboard("myop");
    const options = within(palette()!)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options[0]).toBe("My Opportunities");
    expect(options).not.toContain("Inbox");
  });

  it("runs Settings", async () => {
    const { user } = renderShell();
    await user.keyboard("{Control>}k{/Control}");
    await user.keyboard("settings{Enter}");
    expect(push).toHaveBeenCalledWith("/settings");
  });

  it("opens from the sidebar control, traps focus and returns it on close", async () => {
    const { user } = renderShell();
    const trigger = within(sidebar()).getByRole("button", { name: /Search or run a command/ });
    await user.click(trigger);
    const dialog = palette()!;
    await expectFocusIn(dialog);
    for (let i = 0; i < 5; i++) {
      await user.tab();
      await expectFocusIn(dialog);
    }
    await user.keyboard("{Escape}");
    expect(palette()).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("open: no WCAG 2.1 AA violations", async () => {
    const { user } = renderShell();
    await user.keyboard("{Control>}k{/Control}");
    expect(await axeViolations(document.body)).toEqual([]);
  });
});

describe("cheat sheet", () => {
  it("? opens it; it lists every shortcut from the shared definition", async () => {
    const { user } = renderShell();
    await user.keyboard("?");
    const sheet = cheatSheet()!;
    expect(sheet).toBeTruthy();
    const terms = within(sheet)
      .getAllByRole("term")
      .map((t) => t.textContent);
    expect(terms).toEqual(SHORTCUTS.map((s) => s.description));
  });

  it("opens from the visible control, traps focus and returns it on close", async () => {
    const { user } = renderShell();
    const trigger = within(sidebar()).getByRole("button", { name: /Keyboard shortcuts/ });
    await user.click(trigger);
    const dialog = cheatSheet()!;
    await expectFocusIn(dialog);
    for (let i = 0; i < 3; i++) {
      await user.tab();
      await expectFocusIn(dialog);
    }
    await user.keyboard("{Escape}");
    expect(cheatSheet()).toBeNull();
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  it("open: no WCAG 2.1 AA violations", async () => {
    const { user } = renderShell();
    await user.keyboard("?");
    expect(await axeViolations(document.body)).toEqual([]);
  });
});

describe("g navigation", () => {
  it.each([
    ["i", "/inbox"],
    ["m", "/my-opportunities"],
    ["a", "/opportunities"],
    ["k", "/knowledge"],
    ["r", "/reports"],
  ])("g then %s goes to %s", async (key, href) => {
    const { user } = renderShell();
    await user.keyboard(`g${key}`);
    expect(push).toHaveBeenCalledWith(href);
  });

  it("another key cancels the sequence", async () => {
    const { user } = renderShell();
    await user.keyboard("gxr");
    expect(push).not.toHaveBeenCalled();
  });

  it("more than 1s between keys cancels the sequence", async () => {
    const { user } = renderShell();
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    await user.keyboard("g");
    now += SEQUENCE_TIMEOUT_MS + 1;
    await user.keyboard("r");
    expect(push).not.toHaveBeenCalled();
    await user.keyboard("g");
    now += SEQUENCE_TIMEOUT_MS - 1;
    await user.keyboard("r");
    expect(push).toHaveBeenCalledWith("/reports");
  });
});

describe("input guard", () => {
  it.each([
    ["input", <input key="i" aria-label="Field" />],
    ["textarea", <textarea key="t" aria-label="Field" />],
    [
      "select",
      <select key="s" aria-label="Field">
        <option>One</option>
      </select>,
    ],
    ["contenteditable", <div key="c" aria-label="Field" role="textbox" contentEditable />],
  ])("ignores g r, ?, ], [ and Ctrl+K inside a %s", async (_label, field) => {
    const { user } = renderShell({ children: field });
    screen.getByLabelText("Field").focus();
    await user.keyboard("gr?][[{Control>}k{/Control}");
    expect(push).not.toHaveBeenCalled();
    expect(cheatSheet()).toBeNull();
    expect(palette()).toBeNull();
    expect(rightPane()).toBeNull();
    expect(sidebar().getAttribute("data-collapsed")).toBe("false");
  });
});

describe("single-key shortcuts off", () => {
  it("ignores ?, g r, ] and [; Ctrl+K and Esc still work", async () => {
    const { user } = renderShell({ singleKeyShortcuts: false });
    await user.keyboard("?gr][[");
    expect(cheatSheet()).toBeNull();
    expect(push).not.toHaveBeenCalled();
    expect(rightPane()).toBeNull();
    expect(sidebar().getAttribute("data-collapsed")).toBe("false");
    await user.keyboard("{Control>}k{/Control}");
    expect(palette()).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(palette()).toBeNull();
  });

  it("the visible controls still work, and Esc closes the right pane", async () => {
    const { user } = renderShell({ singleKeyShortcuts: false });
    await user.click(screen.getByRole("button", { name: "Right pane" }));
    expect(rightPane()).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(rightPane()).toBeNull();
  });
});

describe("Esc layering", () => {
  it("closes the palette first, then the right pane", async () => {
    const { user } = renderShell();
    await user.keyboard("]");
    await user.keyboard("{Control>}k{/Control}");
    expect(palette()).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(palette()).toBeNull();
    expect(rightPane()).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(rightPane()).toBeNull();
  });

  it("closes the cheat sheet before the right pane", async () => {
    const { user } = renderShell();
    await user.keyboard("]?");
    await user.keyboard("{Escape}");
    expect(cheatSheet()).toBeNull();
    expect(rightPane()).toBeTruthy();
  });

  it("single keys are inert while a dialog is open", async () => {
    const { user } = renderShell();
    await user.keyboard("?");
    await user.keyboard("gr]");
    expect(push).not.toHaveBeenCalled();
    expect(rightPane()).toBeNull();
  });
});

describe("every shortcut in the shared definition is implemented", () => {
  async function press(user: ReturnType<typeof userEvent.setup>, shortcut: Shortcut) {
    if (shortcut.match.kind === "sequence") {
      await user.keyboard(shortcut.match.keys.join(""));
    } else if (shortcut.match.kind === "digit") {
      await user.keyboard("4");
    } else if (shortcut.match.mod) {
      await user.keyboard(`{Control>}${shortcut.match.key}{/Control}`);
    } else if (shortcut.match.key === "Escape") {
      await user.keyboard("{Escape}");
    } else {
      // user-event reads [ and { as key descriptors; doubling types them literally.
      await user.keyboard(shortcut.match.key.replace(/[[{]/g, (c) => c + c));
    }
  }

  it.each(SHORTCUTS.map((s) => [s.id, s] as const))("%s", async (id, shortcut) => {
    const { user } = renderShell(
      shortcut.match.kind === "digit" ? { children: <Workspace /> } : {},
    );
    if (id === "close-layer") await user.keyboard("]");
    await act(async () => press(user, shortcut));
    if (shortcut.match.kind === "sequence") {
      expect(push).toHaveBeenCalledTimes(1);
      return;
    }
    switch (id) {
      case "open-palette":
        expect(palette()).toBeTruthy();
        break;
      case "open-cheat-sheet":
        expect(cheatSheet()).toBeTruthy();
        break;
      case "toggle-right-pane":
        expect(rightPane()).toBeTruthy();
        break;
      case "toggle-sidebar":
        expect(sidebar().getAttribute("data-collapsed")).toBe("true");
        break;
      case "close-layer":
        expect(rightPane()).toBeNull();
        break;
      case "create-opportunity":
        expect(push).toHaveBeenCalledWith("/opportunities/new");
        break;
      case "switch-workspace-tab":
        expect(push).toHaveBeenCalledWith("/tab-4");
        break;
      default:
        throw new Error(`No check for shortcut ${id}`);
    }
  });
});

describe("c creates an Opportunity (presales engineers only)", () => {
  it("c opens New Opportunity for a presales engineer", async () => {
    const { user } = renderShell({ roles: ["presales_engineer"] });
    await user.keyboard("c");
    expect(push).toHaveBeenCalledWith("/opportunities/new");
  });

  it("c does nothing for other roles, and the cheat sheet leaves it out", async () => {
    const { user } = renderShell({ roles: ["head_of_delivery", "platform_administrator"] });
    await user.keyboard("c");
    expect(push).not.toHaveBeenCalled();
    await user.keyboard("?");
    const terms = within(cheatSheet()!)
      .getAllByRole("term")
      .map((t) => t.textContent);
    expect(terms).not.toContain("Create an Opportunity");
    expect(terms).toHaveLength(SHORTCUTS.length - 1);
  });

  it("c is off with single-key shortcuts off, and inert while typing", async () => {
    const off = renderShell({ singleKeyShortcuts: false });
    await off.user.keyboard("c");
    expect(push).not.toHaveBeenCalled();
    off.unmount();
    const { user } = renderShell({
      children: <input aria-label="Field" />,
    });
    await user.click(screen.getByRole("textbox", { name: "Field" }));
    await user.keyboard("c");
    expect(push).not.toHaveBeenCalled();
  });

  it("the palette offers New Opportunity to presales engineers only", async () => {
    const pse = renderShell({ roles: ["presales_engineer"] });
    await pse.user.keyboard("{Control>}k{/Control}");
    await pse.user.click(within(palette()!).getByRole("option", { name: "New Opportunity" }));
    expect(push).toHaveBeenCalledWith("/opportunities/new");
    pse.unmount();
    const other = renderShell({ roles: ["head_of_delivery"] });
    await other.user.keyboard("{Control>}k{/Control}");
    expect(within(palette()!).queryByRole("option", { name: "New Opportunity" })).toBeNull();
  });
});

describe("state lives in the layout providers", () => {
  it("sidebar and right-pane state survive navigating to a different page", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ShellProviders singleKeyShortcuts>
        <AppShell key="inbox" me={me(["pm_reviewer"])}>
          <PlaceholderPage title="Inbox" />
        </AppShell>
      </ShellProviders>,
    );
    await user.keyboard("[[]");
    pathname.current = "/reports";
    // A different key remounts the shell, as a new page would.
    rerender(
      <ShellProviders singleKeyShortcuts>
        <AppShell key="reports" me={me(["pm_reviewer"])}>
          <PlaceholderPage title="Reports" />
        </AppShell>
      </ShellProviders>,
    );
    expect(screen.getByRole("heading", { name: "Reports" })).toBeTruthy();
    expect(sidebar().getAttribute("data-collapsed")).toBe("true");
    expect(rightPane()).toBeTruthy();
    expect(document.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
  });
});

describe("key matching", () => {
  function keydown(init: KeyboardEventInit, target: Element = document.body) {
    fireEvent.keyDown(target, init);
  }

  it("AltGr (Ctrl+Alt) still types [ and ]", () => {
    renderShell();
    keydown({ key: "]", ctrlKey: true, altKey: true });
    expect(rightPane()).toBeTruthy();
    keydown({ key: "[", ctrlKey: true, altKey: true });
    expect(sidebar().getAttribute("data-collapsed")).toBe("true");
  });

  it("AltGr reported through getModifierState counts as no modifier", () => {
    renderShell();
    const event = new KeyboardEvent("keydown", { key: "]", altKey: true, bubbles: true });
    Object.defineProperty(event, "getModifierState", {
      value: (key: string) => key === "AltGraph",
    });
    act(() => {
      document.body.dispatchEvent(event);
    });
    expect(rightPane()).toBeTruthy();
  });

  it("ignores auto-repeat, except for Esc", () => {
    renderShell();
    keydown({ key: "]", repeat: true });
    expect(rightPane()).toBeNull();
    keydown({ key: "]" });
    expect(rightPane()).toBeTruthy();
    keydown({ key: "Escape", repeat: true });
    expect(rightPane()).toBeNull();
  });

  it("Ctrl+Shift+K does not open the palette", async () => {
    const { user } = renderShell();
    await user.keyboard("{Control>}{Shift>}k{/Shift}{/Control}");
    expect(palette()).toBeNull();
  });

  it("g sequences ignore letter case", async () => {
    const { user } = renderShell();
    await user.keyboard("{Shift>}gr{/Shift}");
    expect(push).toHaveBeenCalledWith("/reports");
  });

  it.each(["radio", "checkbox", "button", "range"])(
    "shortcuts work while a %s input has focus",
    async (type) => {
      const { user } = renderShell({ children: <input type={type} aria-label="Field" /> });
      screen.getByLabelText("Field").focus();
      await user.keyboard("gr");
      expect(push).toHaveBeenCalledWith("/reports");
    },
  );

  it("single keys are ignored inside an open menu, and a pending g is dropped", async () => {
    const { user } = renderShell();
    await user.keyboard("g");
    await user.click(within(sidebar()).getByRole("button", { name: "Account menu for [USER]" }));
    const menu = await screen.findByRole("menu");
    await expectFocusIn(menu);
    await user.keyboard("r");
    await user.keyboard("]");
    expect(push).not.toHaveBeenCalled();
    expect(rightPane()).toBeNull();
  });
});

describe("right pane focus", () => {
  it("returns focus to the toggle when closed with its close button", async () => {
    const { user } = renderShell();
    await user.keyboard("]");
    await user.click(screen.getByRole("button", { name: "Close right pane" }));
    expect(rightPane()).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Right pane" }));
  });

  it("returns focus to the toggle when closed with Esc from inside it", async () => {
    const { user } = renderShell();
    await user.keyboard("]");
    screen.getByRole("button", { name: "Close right pane" }).focus();
    await user.keyboard("{Escape}");
    expect(rightPane()).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Right pane" }));
  });
});

describe("more layering", () => {
  it("Ctrl+K again, with focus in the palette's search field, closes it", async () => {
    const { user } = renderShell();
    await user.keyboard("{Control>}k{/Control}");
    const input = within(palette()!).getByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));
    await user.keyboard("{Control>}k{/Control}");
    expect(palette()).toBeNull();
  });

  it("the palette has a visible close control", async () => {
    const { user } = renderShell();
    await user.keyboard("{Control>}k{/Control}");
    await user.click(within(palette()!).getByRole("button", { name: "Close" }));
    expect(palette()).toBeNull();
  });

  it("the palette's title is not in the DOM while it is closed", () => {
    renderShell();
    expect(screen.queryByText("Command palette")).toBeNull();
    expect(screen.queryByText(/Search for a page or command/)).toBeNull();
  });

  it("Esc in a text field leaves the right pane open", async () => {
    const { user } = renderShell({ children: <input aria-label="Field" /> });
    await user.keyboard("]");
    screen.getByLabelText("Field").focus();
    await user.keyboard("{Escape}");
    expect(rightPane()).toBeTruthy();
  });

  it("Esc in the open account menu closes the menu and leaves the right pane open", async () => {
    const { user } = renderShell();
    await user.keyboard("]");
    await user.click(within(sidebar()).getByRole("button", { name: "Account menu for [USER]" }));
    const menu = await screen.findByRole("menu");
    await expectFocusIn(menu);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(rightPane()).toBeTruthy();
  });
});

describe("1–9 switch workspace tabs", () => {
  it("each digit goes to its tab while a workspace is mounted", async () => {
    const { user } = renderShell({ children: <Workspace /> });
    for (let n = 1; n <= 9; n++) {
      await user.keyboard(String(n));
      expect(push).toHaveBeenLastCalledWith(`/tab-${n}`);
    }
    expect(push).toHaveBeenCalledTimes(9);
  });

  it("the digit of the tab already open adds no history entry", async () => {
    pathname.current = "/tab-4";
    const { user } = renderShell({ children: <Workspace /> });
    await user.keyboard("4");
    expect(push).not.toHaveBeenCalled();
    await user.keyboard("5");
    expect(push).toHaveBeenCalledWith("/tab-5");
  });

  it("digits do nothing outside a workspace, and 0 does nothing anywhere", async () => {
    const outside = renderShell();
    await outside.user.keyboard("14");
    expect(push).not.toHaveBeenCalled();
    outside.unmount();
    const { user } = renderShell({ children: <Workspace /> });
    await user.keyboard("0");
    expect(push).not.toHaveBeenCalled();
  });

  it("unmounting the workspace unregisters the keys", async () => {
    const { user, rerender } = renderShell({ children: <Workspace /> });
    rerender(
      <ShellProviders singleKeyShortcuts>
        <AppShell me={me(["presales_engineer"])}>
          <p>Elsewhere</p>
        </AppShell>
      </ShellProviders>,
    );
    await user.keyboard("4");
    expect(push).not.toHaveBeenCalled();
  });

  it("ignored with single-key shortcuts off", async () => {
    const { user } = renderShell({ singleKeyShortcuts: false, children: <Workspace /> });
    await user.keyboard("4");
    expect(push).not.toHaveBeenCalled();
  });

  it("ignored while typing in a text field", async () => {
    const { user } = renderShell({
      children: (
        <Workspace>
          <input aria-label="Search people" />
        </Workspace>
      ),
    });
    await user.click(screen.getByRole("textbox", { name: "Search people" }));
    await user.keyboard("4");
    expect(push).not.toHaveBeenCalled();
  });

  it("ignored with the palette or cheat sheet open", async () => {
    const { user } = renderShell({ children: <Workspace /> });
    await user.keyboard("{Control>}k{/Control}");
    expect(palette()).toBeTruthy();
    await user.keyboard("4");
    await user.keyboard("{Escape}");
    await user.keyboard("?");
    await user.keyboard("4");
    expect(push).not.toHaveBeenCalled();
  });

  it("ignored with Ctrl, Alt or ⌘ held", async () => {
    const { user } = renderShell({ children: <Workspace /> });
    await user.keyboard("{Control>}4{/Control}{Alt>}4{/Alt}{Meta>}4{/Meta}");
    expect(push).not.toHaveBeenCalled();
  });

  it("ignored inside an open menu", async () => {
    const { user } = renderShell({ children: <Workspace /> });
    await user.click(within(sidebar()).getByRole("button", { name: "Account menu for [USER]" }));
    const menu = await screen.findByRole("menu");
    await expectFocusIn(menu);
    await user.keyboard("4");
    expect(push).not.toHaveBeenCalled();
  });

  it("the cheat sheet lists Switch workspace tab with 1–9", async () => {
    const { user } = renderShell();
    await user.keyboard("?");
    const term = within(cheatSheet()!).getByText("Switch workspace tab");
    expect(term.nextElementSibling?.textContent).toBe("1–9");
  });
});

describe("cheat sheet Mod key", () => {
  const original = Object.getOwnPropertyDescriptor(navigator, "platform");
  afterEach(() => {
    if (original) Object.defineProperty(navigator, "platform", original);
    else delete (navigator as { platform?: string }).platform;
  });

  const modKey = () =>
    within(cheatSheet()!)
      .getByText("Open the command palette")
      .nextElementSibling?.querySelector("kbd")?.textContent;

  it("shows Ctrl under jsdom", async () => {
    const { user } = renderShell();
    await user.keyboard("?");
    expect(modKey()).toBe("Ctrl");
  });

  it("shows ⌘ on a Mac", async () => {
    Object.defineProperty(navigator, "platform", { value: "MacIntel", configurable: true });
    const { user } = renderShell();
    await user.keyboard("?");
    expect(modKey()).toBe("⌘");
  });
});
