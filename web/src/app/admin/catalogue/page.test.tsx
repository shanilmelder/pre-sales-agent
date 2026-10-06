import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { entry } from "@/test/catalogue-fixtures";
import { axeViolations } from "@/test/axe";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("@/app/admin/catalogue/actions", () => ({
  loadEntry: vi.fn(),
  editEntry: vi.fn(),
  retireEntry: vi.fn(),
  reactivateEntry: vi.fn(),
  createEntry: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => ({
  loadOpportunity: vi.fn(),
  updateOpportunity: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/catalogue",
}));

import AdminCataloguePage from "@/app/admin/catalogue/page";
import { ShellProviders } from "@/components/shell/shell-context";

function renderPage(page: ReactElement) {
  return render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);
}

function signedIn(roles: Role[]) {
  getMe.mockResolvedValue({
    kind: "ok",
    me: {
      id: "00000000-0000-7000-8000-000000000000",
      name: "[ADMIN]",
      email: "admin@example.invalid",
      roles,
    },
  });
}

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
});

describe("/admin/catalogue", () => {
  it("lists the catalogue, retired entries included, for administrators", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockResolvedValue({
      data: { items: [entry(1, { name: "SAP IDoc" })] },
      response: new Response(null, { status: 200 }),
    });
    const { container } = renderPage(await AdminCataloguePage());

    expect(screen.getByRole("heading", { level: 1, name: "Catalogue" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Users & roles" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Catalogue" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("button", { name: "SAP IDoc" })).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/catalogue/entries", {
      params: { query: { include_retired: true } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("an empty catalogue shows the empty state", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockResolvedValue({
      data: { items: [] },
      response: new Response(null, { status: 200 }),
    });
    renderPage(await AdminCataloguePage());
    expect(
      screen.getByText("No catalogue entries yet. Press c to add an Integration Type or Work Package."),
    ).toBeTruthy();
  });

  it("other roles get no access and nothing is fetched", async () => {
    signedIn(["presales_engineer"]);
    renderPage(await AdminCataloguePage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("says so when the platform is unreachable", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockRejectedValue(new Error("down"));
    renderPage(await AdminCataloguePage());
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
  });
});
