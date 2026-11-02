import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import type { RetentionOverview } from "@/lib/retention";
import { axeViolations } from "@/test/axe";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("@/app/opportunities/actions", () => ({
  loadOpportunity: vi.fn(),
  updateOpportunity: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/retention",
}));

import AdminRetentionPage from "@/app/admin/retention/page";
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
      permissions: permissionsFor(roles),
    },
  });
}

const OVERVIEW: RetentionOverview = {
  due: [
    {
      opportunity_id: "01a16ea4-dd68-7f04-8c34-a82544b2e521",
      outcome: "lost",
      rule: "lost_3y",
      retention_until: "2026-11-02",
    },
  ],
  recent: [],
};

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
});

describe("/admin/retention", () => {
  it("shows the Retention section to an administrator, read only", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockResolvedValue({ data: OVERVIEW, response: new Response(null, { status: 200 }) });
    const { container } = renderPage(await AdminRetentionPage());

    expect(apiGet).toHaveBeenCalledWith("/api/v1/admin/retention");
    expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeTruthy();
    const sections = screen.getByRole("navigation", { name: "Admin sections" });
    expect(
      within(sections).getByRole("link", { name: "Retention" }).getAttribute("aria-current"),
    ).toBe("page");
    const table = screen.getByRole("table", { name: "Due for purge" });
    expect(within(table).getByText("2 Nov 2026")).toBeTruthy();
    expect(screen.getByText("Nothing has been purged yet.")).toBeTruthy();
    expect(
      screen.getByText(
        "Purged automatically each day after the retention date. Nothing can be deleted from here.",
      ),
    ).toBeTruthy();
    const main = screen.getByRole("main");
    expect(within(main).queryByRole("button", { name: /delete|purge/i })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("tells a non-administrator they have no access, without calling the API", async () => {
    signedIn(["head_of_delivery"]);
    renderPage(await AdminRetentionPage());
    expect(screen.getByRole("heading", { name: "No access" })).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("shows the access message when the API answers 403", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockResolvedValue({ data: undefined, response: new Response(null, { status: 403 }) });
    renderPage(await AdminRetentionPage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
