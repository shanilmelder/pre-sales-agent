import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { NOT_AVAILABLE_YET } from "@/lib/reports";
import { axeViolations } from "@/test/axe";
import { permissionsFor } from "@/test/permissions";
import { report } from "@/test/report-fixtures";

vi.mock("server-only", () => ({}));
const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
const GET = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({ getMe, createServerApiClient: async () => ({ GET }) }));
vi.mock("@/lib/preferences", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/preferences")>()),
  getPreferences: async () => ({ theme: "system", density: "comfortable", singleKeyShortcuts: true }),
}));
vi.mock("@/app/settings/actions", () => ({ savePreferences: vi.fn() }));
vi.mock("@/app/inbox/actions", () => ({
  getInboxUnreadCount: async () => ({ kind: "ok", unread: 0 }),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/reports",
}));

import CostPage from "@/app/reports/cost/page";
import { NO_ACCESS } from "@/app/reports/frame";
import ReportsPage from "@/app/reports/page";
import PipelinePage from "@/app/reports/pipeline/page";
import { ShellProviders } from "@/components/shell/shell-context";
import { TooltipProvider } from "@/components/ui/tooltip";

function renderPage(page: ReactElement) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <TooltipProvider>{page}</TooltipProvider>
    </ShellProviders>,
  );
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

const ok = (data = report()) => ({ data, response: new Response(null, { status: 200 }) });

beforeEach(() => {
  getMe.mockReset();
  GET.mockReset();
  GET.mockResolvedValue(ok());
});

describe("/reports", () => {
  it("the Head of Delivery sees Estimate vs actual with the KPIs and the grouped table", async () => {
    signedIn(["head_of_delivery"]);
    const { container } = renderPage(await ReportsPage({}));
    expect(screen.getByRole("heading", { level: 1, name: "Reports" })).toBeTruthy();
    const tabs = screen.getByRole("navigation", { name: "Report sections" });
    expect(tabs.querySelector('[aria-current="page"]')?.textContent).toBe("Estimate vs actual");
    expect(screen.getByRole("region", { name: "Estimate accuracy" })).toBeTruthy();
    expect(screen.getByRole("table", { name: "Estimate versus actual by Integration Type" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Reports" }).getAttribute("aria-current")).toBe("page");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("asks the API for the URL's grouping and filters, dropping invalid ones", async () => {
    signedIn(["head_of_delivery"]);
    GET.mockResolvedValue(ok(report({ group_by: "cause" })));
    renderPage(
      await ReportsPage({
        searchParams: Promise.resolve({
          group_by: "cause",
          product: "Payments",
          cause: "weather",
          include_milestones: "true",
        }),
      }),
    );
    expect(GET).toHaveBeenCalledWith("/api/v1/reports/estimate-vs-actual", {
      params: {
        query: {
          group_by: "cause",
          product: "Payments",
          work_package_id: undefined,
          cause: undefined,
          closed_from: undefined,
          closed_to: undefined,
          include_milestones: true,
        },
      },
    });
    // The toolbar shows what the URL holds, so a reload keeps it.
    expect((screen.getByLabelText("Group by") as HTMLSelectElement).value).toBe("cause");
    expect(screen.getByRole("table", { name: "Estimate versus actual by Cause" })).toBeTruthy();
  });

  it.each<[string, Role[]]>([
    ["presales engineer", ["presales_engineer"]],
    ["PM reviewer", ["pm_reviewer"]],
  ])("a %s sees No access, without calling the API or a Reports nav item", async (_name, roles) => {
    signedIn(roles);
    const { container } = renderPage(await ReportsPage({}));
    expect(screen.getByRole("heading", { level: 1, name: "No access" })).toBeTruthy();
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Reports" })).toBeNull();
    expect(GET).not.toHaveBeenCalled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the API's 403 shows No access too", async () => {
    signedIn(["head_of_delivery"]);
    GET.mockResolvedValue({ data: undefined, response: new Response(null, { status: 403 }) });
    renderPage(await ReportsPage({}));
    expect(screen.getByRole("heading", { level: 1, name: "No access" })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("an API failure keeps the frame and says the platform is not reachable", async () => {
    signedIn(["head_of_delivery"]);
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    GET.mockResolvedValue({ data: undefined, response: new Response(null, { status: 500 }) });
    renderPage(await ReportsPage({}));
    expect(screen.getByRole("heading", { level: 1, name: "Reports" })).toBeTruthy();
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
    expect(error).toHaveBeenCalledWith("GET estimate-vs-actual report failed: status=500");
    error.mockRestore();
  });
});

describe.each([
  ["/reports/pipeline", PipelinePage, "Pipeline"],
  ["/reports/cost", CostPage, "Cost and usage"],
])("%s", (_path, Page, tab) => {
  it("shows its sub-tab and 'Not available yet.'", async () => {
    signedIn(["head_of_delivery"]);
    const { container } = renderPage(await Page());
    const tabs = screen.getByRole("navigation", { name: "Report sections" });
    expect(tabs.querySelector('[aria-current="page"]')?.textContent).toBe(tab);
    expect(screen.getByText(NOT_AVAILABLE_YET)).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("No access without the permission", async () => {
    signedIn(["presales_engineer"]);
    renderPage(await Page());
    expect(screen.getByText(NO_ACCESS)).toBeTruthy();
    expect(screen.queryByText(NOT_AVAILABLE_YET)).toBeNull();
  });
});
