import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { KnowledgeCoverage } from "@/lib/coverage";
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
  usePathname: () => "/knowledge/coverage",
}));

import KnowledgeCoveragePage from "@/app/knowledge/coverage/page";
import { ShellProviders } from "@/components/shell/shell-context";

const REST = "00000000-0000-7000-8000-000000000011";
const COVERAGE: KnowledgeCoverage = {
  integration_types: [{ id: REST, code: "REST", name: "REST API" }],
  rows: [
    {
      product: "HubSpot",
      cells: [{ integration_type_id: REST, sources: 1, stale: 0, checklists: 1, status: "ready" }],
    },
  ],
  industries: [{ industry: "Retail", checklists: 1, names: ["PCI baseline"] }],
  stale_months: 12,
};

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

function answers(status: number, data?: KnowledgeCoverage) {
  apiGet.mockResolvedValue({ data, response: new Response(null, { status }) });
}

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
});

describe("/knowledge/coverage", () => {
  it("shows the matrix and the industry list under the Coverage sub-tab", async () => {
    signedIn(["sales_representative"]);
    answers(200, COVERAGE);
    const { container } = renderPage(await KnowledgeCoveragePage());

    expect(apiGet).toHaveBeenCalledWith("/api/v1/knowledge/coverage", {});
    expect(screen.getByRole("heading", { level: 1, name: "Knowledge" })).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Knowledge sections" });
    expect(nav.querySelector('[aria-current="page"]')?.textContent).toBe("Coverage");
    expect(await screen.findByRole("gridcell", { name: /^HubSpot REST API Ready/ })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Industry Checklists" })).toBeTruthy();
    expect(screen.getByText("Retail")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says when the platform is not reachable", async () => {
    signedIn(["platform_administrator"]);
    answers(500);
    renderPage(await KnowledgeCoveragePage());
    expect(screen.getByText("The platform is not reachable right now. Try again in a moment.")).toBeTruthy();
  });

  it("says so on a 403", async () => {
    signedIn(["platform_administrator"]);
    answers(403);
    renderPage(await KnowledgeCoveragePage());
    expect(screen.getByText("You do not have access to Knowledge coverage.")).toBeTruthy();
  });
});
