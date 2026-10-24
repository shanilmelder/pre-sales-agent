import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ToolDenial, ToolDenialPage } from "@/lib/admin";
import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { configVersion, registryAgent } from "@/test/agent-fixtures";
import { axeViolations } from "@/test/axe";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
const redirect = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("@/app/opportunities/actions", () => ({
  loadOpportunity: vi.fn(),
  updateOpportunity: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  redirect,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/admin/agents/denials",
}));

import AdminToolDenialsPage from "@/app/admin/agents/denials/page";
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

const OPP = "01a16ea4-dd68-7f04-8c34-a82544b2e521";

function denial(n: number, over: Partial<ToolDenial> = {}): ToolDenial {
  return {
    id: `01a16eb0-0000-7000-8000-00000000000${n}`,
    created_at: `2026-10-24T16:0${n}:00Z`,
    agent_id: "pm_agent",
    semver: "0.1.0",
    config_version_id: "10000000-0000-7000-8000-000000000001",
    tool: "intake.requirement.list",
    reason: "tool_not_permitted",
    opportunity_id: OPP,
    run_id: `01a16ec0-0000-7000-8000-00000000000${n}`,
    task_id: null,
    threshold_exceeded: false,
    ...over,
  };
}

const AGENTS = [
  registryAgent(1, "PM Agent", configVersion(1)),
  registryAgent(2, "Security Agent", configVersion(1, {}, "security_agent")),
];

function respond(page: Partial<ToolDenialPage>, status = 200) {
  apiGet.mockImplementation(async (path: string) => {
    if (path === "/api/v1/registry/agents") {
      return { data: { items: AGENTS }, response: new Response(null, { status: 200 }) };
    }
    if (status !== 200) return { data: undefined, response: new Response(null, { status }) };
    return {
      data: { items: [], page: 1, page_size: 50, total: 0, ...page },
      response: new Response(null, { status: 200 }),
    };
  });
}

const page = (params: Record<string, string> = {}) =>
  AdminToolDenialsPage({ searchParams: Promise.resolve(params) });

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
  redirect.mockReset();
});

describe("/admin/agents/denials", () => {
  it("lists the denials with the Agents toggle on Denied tool calls", async () => {
    signedIn(["platform_administrator"]);
    respond({ items: [denial(2, { threshold_exceeded: true }), denial(1)], total: 2 });
    const { container } = renderPage(await page());

    expect(apiGet).toHaveBeenCalledWith("/api/v1/registry/tool-denials", {
      params: { query: { page: 1, page_size: 50 } },
    });
    const sections = screen.getByRole("navigation", { name: "Admin sections" });
    expect(within(sections).getByRole("link", { name: "Agents" }).getAttribute("aria-current")).toBe(
      "page",
    );
    const views = screen.getByRole("navigation", { name: "Agents views" });
    expect(within(views).getByRole("link", { name: "Registry" }).getAttribute("href")).toBe(
      "/admin/agents",
    );
    expect(
      within(views).getByRole("link", { name: "Denied tool calls" }).getAttribute("aria-current"),
    ).toBe("page");
    const table = screen.getByRole("table", { name: "Denied tool calls" });
    expect(within(table).getAllByRole("rowheader")).toHaveLength(2);
    expect(within(table).getAllByText("Threshold exceeded")).toHaveLength(1);
    expect(screen.getByText("1–2 of 2")).toBeTruthy();
    const agent = screen.getByLabelText("Agent");
    expect(within(agent).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Any agent",
      "pm_agent",
      "security_agent",
    ]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("passes the URL filters and page to the API; invalid ones are dropped", async () => {
    signedIn(["platform_administrator"]);
    respond({ items: [denial(1)], page: 2, page_size: 50, total: 51 });
    renderPage(await page({ agent_id: "pm_agent", from: "2026-10-01", to: "nope", page: "2" }));
    expect(apiGet).toHaveBeenCalledWith("/api/v1/registry/tool-denials", {
      params: { query: { agent_id: "pm_agent", from: "2026-10-01", page: 2, page_size: 50 } },
    });
    expect((screen.getByLabelText("Agent") as HTMLSelectElement).value).toBe("pm_agent");
    expect(screen.getByRole("link", { name: "Previous" }).getAttribute("href")).toBe(
      "/admin/agents/denials?agent_id=pm_agent&from=2026-10-01",
    );
    expect(screen.queryByRole("link", { name: "Next" })).toBeNull();
  });

  it("past the last page, redirects to the last one with the filters", async () => {
    signedIn(["platform_administrator"]);
    respond({ items: [], page: 5, page_size: 50, total: 51 });
    await page({ page: "5", agent_id: "pm_agent" });
    expect(redirect).toHaveBeenCalledWith("/admin/agents/denials?agent_id=pm_agent&page=2");
  });

  it("shows the empty state", async () => {
    signedIn(["platform_administrator"]);
    respond({});
    const { container } = renderPage(await page());
    expect(screen.getByText("No denied tool calls.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says no denials match when filters are applied", async () => {
    signedIn(["platform_administrator"]);
    respond({});
    renderPage(await page({ agent_id: "pm_agent" }));
    expect(screen.getByText("No denied tool calls match these filters.")).toBeTruthy();
  });

  it("other roles get no access and nothing is fetched", async () => {
    signedIn(["presales_engineer"]);
    const { container } = renderPage(await page());
    expect(screen.getByRole("heading", { level: 1, name: "No access" })).toBeTruthy();
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a 403 from the API shows no access", async () => {
    signedIn(["platform_administrator"]);
    respond({}, 403);
    renderPage(await page());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says so when the platform is unreachable", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockRejectedValue(new Error("down"));
    renderPage(await page());
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
  });
});
