import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AdminUser } from "@/app/admin/users/actions";
import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { axeViolations } from "@/test/axe";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
const changeRole = vi.hoisted(() => vi.fn());
vi.mock("@/app/admin/users/actions", () => ({ changeRole, loadUser: vi.fn() }));
const redirect = vi.hoisted(() =>
  vi.fn((href: string) => {
    throw new Error(`NEXT_REDIRECT ${href}`);
  }),
);
vi.mock("next/navigation", () => ({
  redirect,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/users",
}));

import AdminUsersPage from "@/app/admin/users/page";
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

const TARGET: AdminUser = {
  id: "00000000-0000-7000-8000-000000000001",
  name: "[TARGET]",
  email: "target@example.invalid",
  roles: ["commercial"],
  row_version: 2,
  last_changed_by: null,
};

function listed(items: AdminUser[], total = items.length, page = 1) {
  apiGet.mockResolvedValue({
    data: { items, page, page_size: 50, total },
    response: new Response(null, { status: 200 }),
  });
}

const searchParams = (page?: string) => Promise.resolve(page ? { page } : {});

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
  changeRole.mockReset();
  redirect.mockClear();
});

describe("/admin/users", () => {
  it("lists users inside the shell for administrators", async () => {
    signedIn(["platform_administrator"]);
    listed([TARGET]);
    const { container } = renderPage(await AdminUsersPage({ searchParams: searchParams() }));

    expect(screen.getByRole("heading", { level: 1, name: "Users & roles" })).toBeTruthy();
    expect(screen.getByRole("navigation", { name: "Primary" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Admin" }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("button", { name: "[TARGET]" })).toBeTruthy();
    expect(screen.getByText("1–1 of 1")).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/v1/admin/users", {
      params: { query: { page: 1, page_size: 50 } },
    });
    expect(await axeViolations(container)).toEqual([]);
  });

  it("asks the API for the requested page and links to its neighbours", async () => {
    signedIn(["platform_administrator"]);
    const fifty = Array.from({ length: 50 }, (_, i) => ({
      ...TARGET,
      id: `00000000-0000-7000-8000-${String(i).padStart(12, "0")}`,
    }));
    listed(fifty, 120, 2);
    renderPage(await AdminUsersPage({ searchParams: searchParams("2") }));
    expect(apiGet).toHaveBeenCalledWith("/api/v1/admin/users", {
      params: { query: { page: 2, page_size: 50 } },
    });
    expect(screen.getByText("51–100 of 120")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Previous" }).getAttribute("href")).toBe(
      "/admin/users?page=1",
    );
    expect(screen.getByRole("link", { name: "Next" }).getAttribute("href")).toBe(
      "/admin/users?page=3",
    );
  });

  it("a page past the last one redirects to the last page", async () => {
    signedIn(["platform_administrator"]);
    listed([], 120, 9);
    await expect(AdminUsersPage({ searchParams: searchParams("9") })).rejects.toThrow(
      "NEXT_REDIRECT /admin/users?page=3",
    );
  });

  it("an empty platform shows the empty state and no range", async () => {
    signedIn(["platform_administrator"]);
    listed([], 0);
    renderPage(await AdminUsersPage({ searchParams: searchParams() }));
    expect(screen.getByText("No users yet.")).toBeTruthy();
    expect(screen.queryByText(/ of /)).toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });

  it("opens the inspector in the right pane and saves a toggle", async () => {
    signedIn(["platform_administrator"]);
    listed([TARGET]);
    changeRole.mockResolvedValue({
      kind: "ok",
      user: { ...TARGET, roles: ["commercial", "pm_reviewer"], row_version: 3 },
    });
    const user = userEvent.setup();
    const { container } = renderPage(await AdminUsersPage({ searchParams: searchParams() }));

    await user.click(screen.getByRole("button", { name: "[TARGET]" }));
    const pane = await screen.findByRole("complementary", { name: "Details" });
    expect(within(pane).queryByText("Nothing selected.")).toBeNull();
    expect(within(pane).getAllByRole("switch")).toHaveLength(9);

    await user.click(within(pane).getByRole("switch", { name: "PM reviewer" }));
    expect(changeRole).toHaveBeenCalledWith({
      userId: TARGET.id,
      role: "pm_reviewer",
      assigned: true,
      rowVersion: 2,
    });
    // The list row reflects the stored user.
    await waitFor(() => expect(screen.getByText("Commercial, PM reviewer")).toBeTruthy());
    expect(await axeViolations(container)).toEqual([]);
  });

  it("non-admins see the access message and the API is never called", async () => {
    signedIn(["presales_engineer"]);
    const { container } = renderPage(await AdminUsersPage({ searchParams: searchParams() }));
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Users & roles" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    expect(apiGet).not.toHaveBeenCalled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("an API 403 shows the access message instead of the list", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockResolvedValue({ data: undefined, response: new Response(null, { status: 403 }) });
    renderPage(await AdminUsersPage({ searchParams: searchParams() }));
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("users with no roles see only the no-access message", async () => {
    signedIn([]);
    renderPage(await AdminUsersPage({ searchParams: searchParams() }));
    expect(screen.getByText(/don't have access yet/)).toBeTruthy();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(apiGet).not.toHaveBeenCalled();
  });
});
