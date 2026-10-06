import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Me, MeResult } from "@/lib/api/server";
import { axeViolations } from "@/test/axe";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
vi.mock("@/lib/api/server", () => ({ getMe }));
vi.mock("@/lib/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/preferences")>()),
  getPreferences: async () => ({
    theme: "system",
    density: "comfortable",
    singleKeyShortcuts: true,
  }),
}));
vi.mock("@/app/settings/actions", () => ({ savePreferences: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/settings",
}));

import SettingsPage from "@/app/settings/page";
import { ShellProviders } from "@/components/shell/shell-context";

import { AccessGate, hasAccess } from "./access-gate";

const NO_ACCESS =
  "You're signed in, but you don't have access yet. Ask an administrator to assign a role.";

function me(roles: string[]): Me {
  return {
    id: "00000000-0000-7000-8000-000000000000",
    name: "[USER]",
    email: "user@example.invalid",
    roles,
    permissions: [],
  } as Me;
}

describe("hasAccess", () => {
  it("is true for a signed-in user with a role", () => {
    expect(hasAccess({ kind: "ok", me: me(["presales_engineer"]) })).toBe(true);
  });

  it("is false for a signed-in user with no roles", () => {
    expect(hasAccess({ kind: "ok", me: me([]) })).toBe(false);
  });

  it("is false when signed out or the platform is unavailable", () => {
    expect(hasAccess({ kind: "signed-out" })).toBe(false);
    expect(hasAccess({ kind: "unavailable" })).toBe(false);
  });
});

describe("AccessGate", () => {
  it.each<[string, MeResult, RegExp]>([
    ["signed out", { kind: "signed-out" }, /Your session has ended/],
    ["unavailable", { kind: "unavailable" }, /not reachable right now/],
    ["no roles", { kind: "ok", me: me([]) }, /don't have access yet/],
  ])("%s: shows its message with no WCAG 2.1 AA violations", async (_label, result, text) => {
    const { container } = render(<AccessGate result={result} />);
    expect(screen.getByText(text)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("signed out links to sign-in", () => {
    render(<AccessGate result={{ kind: "signed-out" }} />);
    expect(screen.getByRole("link", { name: "Sign in again" }).getAttribute("href")).toBe(
      "/auth/login",
    );
  });
});

describe("/settings page", () => {
  beforeEach(() => getMe.mockReset());

  it("shows a user with no roles only the no-access message", async () => {
    getMe.mockResolvedValue({ kind: "ok", me: me([]) });
    render(<ShellProviders singleKeyShortcuts>{await SettingsPage()}</ShellProviders>);
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Settings" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Theme" })).toBeNull();
    expect(screen.queryByRole("switch")).toBeNull();
  });

  it("shows the settings form to a user with a role", async () => {
    getMe.mockResolvedValue({ kind: "ok", me: me(["presales_engineer"]) });
    const { container } = render(<ShellProviders singleKeyShortcuts>{await SettingsPage()}</ShellProviders>);
    expect(screen.getByRole("heading", { name: "Settings" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Theme" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });
});
