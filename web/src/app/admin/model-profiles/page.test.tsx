import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("@/app/admin/model-profiles/actions", () => ({
  loadProfiles: vi.fn(),
  createProfile: vi.fn(),
  retestProfile: vi.fn(),
  retireProfile: vi.fn(),
  addApprovedModel: vi.fn(),
  removeApprovedModel: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => ({
  loadOpportunity: vi.fn(),
  updateOpportunity: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/model-profiles",
}));

import AdminApprovedModelsPage from "@/app/admin/model-profiles/approved/page";
import AdminModelProfilesPage from "@/app/admin/model-profiles/page";
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

const ok = { data: { items: [] }, response: new Response(null, { status: 200 }) };
const failed = (status: number) => ({ data: undefined, response: new Response(null, { status }) });

function respond(profiles: unknown, approved: unknown) {
  apiGet.mockImplementation(async (path: string) =>
    path.endsWith("approved-models") ? approved : profiles,
  );
}

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("/admin/model-profiles", () => {
  it("lists the profiles for an administrator", async () => {
    signedIn(["platform_administrator"]);
    respond(ok, ok);
    renderPage(await AdminModelProfilesPage());
    expect(screen.getByRole("heading", { name: "Chat model profiles" })).toBeTruthy();
  });

  it("shows no access to anyone else, without calling the API", async () => {
    signedIn(["presales_engineer"]);
    renderPage(await AdminModelProfilesPage());
    expect(screen.getByRole("heading", { level: 1, name: "No access" })).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("shows no access on a 403", async () => {
    signedIn(["platform_administrator"]);
    respond(failed(403), ok);
    renderPage(await AdminModelProfilesPage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
  });

  it("shows the error when only the approved models fail", async () => {
    signedIn(["platform_administrator"]);
    respond(ok, failed(500));
    renderPage(await AdminModelProfilesPage());
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Chat model profiles" })).toBeNull();
  });
});

describe("/admin/model-profiles/approved", () => {
  it("lists the approved models and shows no access to anyone else", async () => {
    signedIn(["platform_administrator"]);
    respond(ok, ok);
    const { unmount } = renderPage(await AdminApprovedModelsPage());
    expect(screen.getByRole("heading", { name: "Approved models" })).toBeTruthy();
    unmount();

    signedIn(["presales_engineer"]);
    renderPage(await AdminApprovedModelsPage());
    expect(screen.getByRole("heading", { level: 1, name: "No access" })).toBeTruthy();
  });

  it("shows the error when the list fails", async () => {
    signedIn(["platform_administrator"]);
    respond(ok, failed(500));
    renderPage(await AdminApprovedModelsPage());
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
  });
});
