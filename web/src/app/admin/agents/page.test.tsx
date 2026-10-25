import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { RegistryAgent } from "@/lib/admin";
import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
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
  usePathname: () => "/admin/agents",
}));

import AdminAgentsPage from "@/app/admin/agents/page";
import { ShellProviders } from "@/components/shell/shell-context";

function renderPage(page: ReactElement) {
  return render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);
}

function signedIn(roles: Role[], permissions = permissionsFor(roles)) {
  getMe.mockResolvedValue({
    kind: "ok",
    me: {
      id: "00000000-0000-7000-8000-000000000000",
      name: "[ADMIN]",
      email: "admin@example.invalid",
      roles,
      permissions,
    },
  });
}

function agent(
  n: number,
  name: string,
  status: RegistryAgent["status"],
  toolPermissions: string[] = [],
): RegistryAgent {
  const id = `00000000-0000-7000-8000-00000000000${n}`;
  return {
    id,
    agent_id: name.toLowerCase().replace(/ /g, "_"),
    name,
    status,
    row_version: 1,
    created_at: "2026-10-01T09:00:00Z",
    current_config: {
      id: `10000000-0000-7000-8000-00000000000${n}`,
      agent_id: id,
      version: 3,
      semver: `1.${n}.0`,
      model_profile: "reasoning-large",
      model_digest: "unpinned",
      prompt_version: 1,
      input_schema_version: 1,
      output_schema_version: 1,
      contract_version: "1",
      tool_permissions: toolPermissions,
      budgets: {},
      created_by_id: null,
      created_by_name: null,
      reason: null,
      restored_from_version: null,
      created_at: "2026-10-01T09:00:00Z",
    },
  };
}

function respond(items: RegistryAgent[]) {
  apiGet.mockResolvedValue({ data: { items }, response: new Response(null, { status: 200 }) });
}

const rowOf = (name: string) =>
  screen.getByRole("rowheader", { name }).closest('[role="row"]') as HTMLElement;

const toneOf = (el: HTMLElement) =>
  el.closest('[data-slot="pill"]')?.getAttribute("data-tone") ?? null;

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
});

describe("/admin/agents", () => {
  it("lists every Agent with version, model, status and tool permissions", async () => {
    signedIn(["platform_administrator"]);
    respond([
      agent(1, "Intake Agent", "active", ["read_sources", "write_requirements"]),
      agent(2, "Red Team Agent", "disabled"),
      agent(3, "PM Agent", "eval_only", ["read_requirements"]),
    ]);
    const { container } = renderPage(await AdminAgentsPage());

    expect(apiGet).toHaveBeenCalledWith("/api/v1/registry/agents");
    expect(screen.getByRole("heading", { level: 1, name: "Admin" })).toBeTruthy();
    const sections = screen.getByRole("navigation", { name: "Admin sections" });
    expect(within(sections).getByRole("link", { name: "Agents" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(within(sections).getByRole("link", { name: "Evals" }).getAttribute("aria-current")).toBe(
      null,
    );
    // Story 7.4: the Registry | Denied tool calls toggle.
    const views = screen.getByRole("navigation", { name: "Agents views" });
    expect(within(views).getByRole("link", { name: "Registry" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(
      within(views).getByRole("link", { name: "Denied tool calls" }).getAttribute("href"),
    ).toBe("/admin/agents/denials");

    const table = screen.getByRole("table", { name: "Agents" });
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Agent",
      "Version",
      "Model",
      "Status",
      "Tool permissions",
    ]);
    const intake = rowOf("Intake Agent");
    expect(within(intake).getByText("1.1.0")).toBeTruthy();
    expect(within(intake).getByText("reasoning-large")).toBeTruthy();
    expect(within(intake).getByText("read_sources, write_requirements")).toBeTruthy();
    expect(toneOf(within(intake).getByText("Enabled"))).toBe("resolved");

    const pm = rowOf("PM Agent");
    expect(toneOf(within(pm).getByText("Eval only"))).toBe("neutral");
    expect(within(pm).getByText("read_requirements")).toBeTruthy();

    expect(
      screen.getByText(
        "No agent can send customer communication or approve. Disabled agents receive no tasks.",
      ),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a disabled Agent has a neutral Disabled pill with an icon, and None for no tools", async () => {
    signedIn(["platform_administrator"]);
    respond([agent(2, "Red Team Agent", "disabled")]);
    renderPage(await AdminAgentsPage());
    const row = rowOf("Red Team Agent");
    const label = within(row).getByText("Disabled");
    expect(toneOf(label)).toBe("neutral");
    expect(label.closest('[data-slot="pill"]')?.querySelector("svg")).toBeTruthy();
    expect(within(row).getByText("None")).toBeTruthy();
  });

  it("no Agents shows the empty text", async () => {
    signedIn(["platform_administrator"]);
    respond([]);
    renderPage(await AdminAgentsPage());
    expect(screen.getByText("No agents registered yet.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("without identity.user.list there is no access and nothing is fetched", async () => {
    signedIn(["platform_administrator"], []);
    const { container } = renderPage(await AdminAgentsPage());
    expect(screen.getByRole("heading", { level: 1, name: "No access" })).toBeTruthy();
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("other roles get no access", async () => {
    signedIn(["presales_engineer"]);
    renderPage(await AdminAgentsPage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("a 403 from the API shows no access", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockResolvedValue({ data: undefined, response: new Response(null, { status: 403 }) });
    renderPage(await AdminAgentsPage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says so when the platform is unreachable", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockRejectedValue(new Error("down"));
    renderPage(await AdminAgentsPage());
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
  });
});
