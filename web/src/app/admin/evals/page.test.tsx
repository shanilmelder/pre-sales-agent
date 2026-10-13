import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import type { Role } from "@/lib/navigation";
import { axeViolations } from "@/test/axe";
import { evalResult } from "@/test/eval-fixtures";
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
  usePathname: () => "/admin/evals",
}));

import AdminEvalsPage from "@/app/admin/evals/page";
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

const LATEST = evalResult(
  2,
  { extraction_recall: 92, gap_recall: 84, irrelevant_gaps: 12 },
  { passed: false, accepted: false },
);
LATEST.bars = LATEST.bars.map((bar) =>
  bar.metric === "gap_recall" ? { ...bar, status: "fail", delta: -7, regressed: true } : bar,
);
const PREVIOUS = evalResult(1, { extraction_recall: 92, gap_recall: 91, irrelevant_gaps: 12 });

function respond(items: unknown[]) {
  apiGet.mockResolvedValue({ data: { items }, response: new Response(null, { status: 200 }) });
}

beforeEach(() => {
  getMe.mockReset();
  apiGet.mockReset();
});

describe("/admin/evals", () => {
  it("shows the latest result's bars, per Agent values, the diff and the history", async () => {
    signedIn(["platform_administrator"]);
    respond([LATEST, PREVIOUS]);
    const { container } = renderPage(await AdminEvalsPage());

    expect(screen.getByRole("heading", { level: 1, name: "Evals" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Evals" }).getAttribute("aria-current")).toBe("page");
    expect(apiGet).toHaveBeenCalledWith("/api/v1/registry/evals");

    const bars = screen.getByRole("table", { name: "Release bars" });
    const gapRow = within(bars).getByRole("row", { name: /Gap recall/ });
    expect(within(gapRow).getByText("84.0%")).toBeTruthy();
    expect(within(gapRow).getByText("≥ 80%")).toBeTruthy();
    expect(within(gapRow).getByText("−7.0")).toBeTruthy();
    expect(within(gapRow).getByText("Fail")).toBeTruthy(); // icon plus label
    const evidenceRow = within(bars).getByRole("row", { name: /Evidence support/ });
    expect(within(evidenceRow).getByText("Not measured")).toBeTruthy();

    const agents = screen.getByRole("table", { name: "Results per Agent" });
    expect(within(agents).getByRole("rowheader", { name: "Intake Agent" })).toBeTruthy();

    const diff = screen.getByRole("table", { name: "Change from the previous result" });
    const changed = within(diff).getByRole("row", { name: /Gap recall/ });
    expect(changed.className).toContain("bg-diff-tint");
    expect(within(changed).getByText("−7.0")).toBeTruthy();

    const history = screen.getByRole("list", { name: "Evaluation history" });
    expect(within(history).getAllByRole("button")).toHaveLength(2);
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("selecting an older result shows it, with nothing before it to compare", async () => {
    signedIn(["platform_administrator"]);
    respond([LATEST, PREVIOUS]);
    renderPage(await AdminEvalsPage());

    const history = screen.getByRole("list", { name: "Evaluation history" });
    await userEvent.click(within(history).getAllByRole("button")[1]);
    expect(screen.getByRole("heading", { name: "Selected result" })).toBeTruthy();
    expect(
      screen.getByText("This is the first result: there is nothing to compare it with."),
    ).toBeTruthy();
    expect(screen.getAllByText("Passed · accepted").length).toBeGreaterThan(0);
  });

  it("an empty history says how to create a result", async () => {
    signedIn(["platform_administrator"]);
    respond([]);
    renderPage(await AdminEvalsPage());
    expect(screen.getByText(/No evaluation results yet/)).toBeTruthy();
  });

  it("other roles get no access and nothing is fetched", async () => {
    signedIn(["presales_engineer"]);
    renderPage(await AdminEvalsPage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("a 403 from the API shows no access", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockResolvedValue({ data: undefined, response: new Response(null, { status: 403 }) });
    renderPage(await AdminEvalsPage());
    expect(screen.getByText("You don't have access to this page")).toBeTruthy();
  });

  it("says so when the platform is unreachable", async () => {
    signedIn(["platform_administrator"]);
    apiGet.mockRejectedValue(new Error("down"));
    renderPage(await AdminEvalsPage());
    expect(screen.getByText(/not reachable right now/)).toBeTruthy();
  });
});
