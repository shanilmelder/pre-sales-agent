import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, MeResult } from "@/lib/api/server";
import { EMPTY_STATE as NO_KNOWLEDGE_SOURCES } from "@/lib/knowledge-sources";
import type { Role } from "@/lib/navigation";
import { axeViolations } from "@/test/axe";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const api = vi.hoisted(() => ({
  GET: vi.fn(async () => ({ data: { items: [] }, response: new Response(null, { status: 200 }) })),
}));
vi.mock("@/lib/api/server", () => ({ getMe, createServerApiClient: async () => api }));
// The Knowledge page lists Sources through its own server actions.
vi.mock("@/app/knowledge/actions", () => ({
  loadSources: async () => ({ kind: "ok", sources: [], staleMonths: 12 }),
}));
vi.mock("@/app/opportunities/actions", () => ({ loadSources: vi.fn(), retryParse: vi.fn() }));
vi.mock("@/lib/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/preferences")>()),
  getPreferences: async () => ({
    theme: "system",
    density: "comfortable",
    singleKeyShortcuts: true,
  }),
}));
vi.mock("@/app/settings/actions", () => ({ savePreferences: vi.fn() }));

const redirect = vi.hoisted(() =>
  vi.fn((href: string) => {
    throw new Error(`NEXT_REDIRECT ${href}`);
  }),
);
vi.mock("next/navigation", () => ({
  redirect,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/",
}));

import AdminPage from "@/app/admin/page";
import InboxPage from "@/app/inbox/page";
import KnowledgePage from "@/app/knowledge/page";
import NotFound from "@/app/not-found";
import Home from "@/app/page";
import ReportsPage from "@/app/reports/page";
import SettingsPage from "@/app/settings/page";
import { ShellProviders } from "@/components/shell/shell-context";

/** Pages render under the root layout's providers (shell state and live region). */
function renderPage(page: ReactElement) {
  return render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);
}

const NO_ACCESS =
  "You're signed in, but you don't have access yet. Ask an administrator to assign a role.";

function me(roles: Role[]): Me {
  return {
    id: "00000000-0000-7000-8000-000000000000",
    name: "[USER]",
    email: "user@example.invalid",
    roles,
  };
}

function signedIn(roles: Role[]) {
  getMe.mockResolvedValue({ kind: "ok", me: me(roles) });
}

const SHELL_PAGES: [string, () => Promise<ReactElement>, string, string][] = [
  ["/inbox", InboxPage, "Inbox", "Nothing waiting for you."],
  ["/knowledge", KnowledgePage, "Knowledge", NO_KNOWLEDGE_SOURCES],
  ["/reports", ReportsPage, "Reports", "Not available yet."],
  ["/settings", SettingsPage, "Settings", "Saved in this browser."],
];

beforeEach(() => {
  getMe.mockReset();
  redirect.mockClear();
});

describe("/ landing", () => {
  it("sends presales engineers to My Opportunities", async () => {
    signedIn(["presales_engineer", "pm_reviewer"]);
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /my-opportunities");
  });

  it("sends everyone else to Inbox", async () => {
    signedIn(["pm_reviewer"]);
    await expect(Home()).rejects.toThrow("NEXT_REDIRECT /inbox");
  });

  it("shows a user with no roles only the no-access message", async () => {
    signedIn([]);
    renderPage(await Home());
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe.each(SHELL_PAGES)("%s", (_path, Page, title, text) => {
  it("renders inside the shell with its title and text", async () => {
    signedIn(["platform_administrator"]);
    const { container } = renderPage(await Page());
    expect(screen.getAllByRole("navigation", { name: "Primary" })).toHaveLength(1);
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(document.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: title })).toBeTruthy();
    expect(screen.getByText(text)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("no roles: only the no-access message and avatar menu, no shell", async () => {
    signedIn([]);
    renderPage(await Page());
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Account menu for [USER]" })).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("heading", { name: title })).toBeNull();
  });

  it("signed out and unavailable render without the shell", async () => {
    getMe.mockResolvedValue({ kind: "signed-out" });
    const signedOut = renderPage(await Page());
    expect(screen.getByText(/Your session has ended/)).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
    signedOut.unmount();
    getMe.mockResolvedValue({ kind: "unavailable" });
    renderPage(await Page());
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});

describe("/admin", () => {
  it("non-admins see the access message inside the shell, and no Admin nav item", async () => {
    signedIn(["presales_engineer"]);
    const { container } = renderPage(await AdminPage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Admin" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("sends admins to Users & roles", async () => {
    signedIn(["platform_administrator"]);
    await expect(AdminPage()).rejects.toThrow("NEXT_REDIRECT /admin/users");
  });

  it("no roles: only the no-access message, no redirect", async () => {
    signedIn([]);
    renderPage(await AdminPage());
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(redirect).not.toHaveBeenCalled();
  });
});

describe("unknown page", () => {
  it("shows 'This page does not exist.' inside the shell", async () => {
    signedIn(["pm_reviewer"]);
    const { container } = renderPage(await NotFound());
    expect(screen.getByText("This page does not exist.")).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("no roles: only the no-access message", async () => {
    signedIn([]);
    renderPage(await NotFound());
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(screen.queryByText("This page does not exist.")).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
