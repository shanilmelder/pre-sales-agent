import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import { GRAPH_DENIED, type KnowledgeGraph } from "@/lib/knowledge-graph";
import type { Role } from "@/lib/navigation";
import { axeViolations } from "@/test/axe";
import { graphFixture } from "@/test/knowledge-fixtures";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const apiGet = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({
  getMe,
  createServerApiClient: async () => ({ GET: apiGet }),
}));
vi.mock("@/app/knowledge/actions", () => ({ markReviewed: vi.fn() }));
vi.mock("@/app/opportunities/actions", () => ({
  loadOpportunity: vi.fn(),
  updateOpportunity: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/knowledge/graph",
}));

import KnowledgeGraphPage from "@/app/knowledge/graph/page";
import { ShellProviders } from "@/components/shell/shell-context";

function renderPage(page: ReactElement) {
  return render(<ShellProviders singleKeyShortcuts>{page}</ShellProviders>);
}

function signedIn(roles: Role[]) {
  getMe.mockResolvedValue({
    kind: "ok",
    me: {
      id: "00000000-0000-7000-8000-000000000000",
      name: "[USER]",
      email: "user@example.invalid",
      roles,
      permissions: permissionsFor(roles),
    },
  });
}

function answers(status: number, data?: KnowledgeGraph) {
  apiGet.mockResolvedValue({ data, response: new Response(null, { status }) });
}

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
});

describe("/knowledge/graph", () => {
  it("shows the graph under the Graph sub-tab, first in the nav", async () => {
    signedIn(["engineering_reviewer"]);
    answers(200, graphFixture());
    const { container } = renderPage(await KnowledgeGraphPage());

    expect(apiGet).toHaveBeenCalledWith("/api/v1/knowledge/graph", {});
    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Knowledge sections" });
    const links = Array.from(nav.querySelectorAll("a"));
    expect(links[0].textContent).toBe("Graph");
    expect(links[0].getAttribute("aria-current")).toBe("page");
    expect(await screen.findByRole("button", { name: "SAP EWM, Product, Ready" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says so on a 403", async () => {
    signedIn(["platform_administrator"]);
    answers(403);
    renderPage(await KnowledgeGraphPage());
    expect(screen.getByRole("alert").textContent).toBe(GRAPH_DENIED);
  });

  it("denies a user who can't edit Checklists without asking the API, and hides the tab", async () => {
    signedIn(["sales_representative"]);
    renderPage(await KnowledgeGraphPage());
    expect(apiGet).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toBe(GRAPH_DENIED);
    expect(screen.queryByRole("link", { name: "Graph" })).toBeNull();
  });

  it("says when the platform is not reachable", async () => {
    signedIn(["security_reviewer"]);
    answers(500);
    renderPage(await KnowledgeGraphPage());
    expect(
      screen.getByText("The platform is not reachable right now. Try again in a moment."),
    ).toBeTruthy();
  });
});
