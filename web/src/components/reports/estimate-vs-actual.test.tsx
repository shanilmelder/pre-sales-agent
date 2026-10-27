import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  CALIBRATION_TITLE,
  EMPTY_BODY,
  EMPTY_TITLE,
  NO_MATCH,
  parseReportParams,
  type EstimateVsActualReport,
  type ReportParams,
} from "@/lib/reports";
import { axeViolations } from "@/test/axe";
import { ALPHA_ID, group, report, variance } from "@/test/report-fixtures";

vi.mock("server-only", () => ({}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

import { EstimateVsActual } from "./estimate-vs-actual";

function renderReport(
  data: EstimateVsActualReport = report(),
  params: ReportParams = parseReportParams({}),
) {
  return render(
    <TooltipProvider>
      <EstimateVsActual report={data} params={params} />
    </TooltipProvider>,
  );
}

const table = () => screen.getByRole("table", { name: "Estimate versus actual by Integration Type" });
const groupLabels = () =>
  Array.from(table().querySelectorAll("[data-group]")).map((row) => row.getAttribute("data-group"));

describe("EstimateVsActual", () => {
  it("shows the three KPIs, the grouped table and the calibration strip", async () => {
    const { container } = renderReport();
    const kpis = screen.getByRole("region", { name: "Estimate accuracy" });
    expect(within(kpis).getByText("Closed Opportunities")).toBeTruthy();
    expect(within(kpis).getByText("Actuals recorded on 2 Opportunities")).toBeTruthy();
    expect(within(kpis).getByText("300 h estimated, 300 h actual")).toBeTruthy();
    expect(within(kpis).getByText("2 Conditions, 1 Contingencies")).toBeTruthy();

    expect(screen.getByText("2 closed Opportunities · hours")).toBeTruthy();
    const rows = within(table()).getAllByRole("row");
    expect(rows).toHaveLength(3);
    const rest = within(rows[1]!).getAllByRole("cell");
    expect(rest.map((c) => c.textContent)).toEqual([
      "Show the Opportunities in REST APIREST API1 Opportunity · 1 failed Assumption",
      "100.0",
      "120.0",
      "+20% over",
      "Integration complexity",
    ]);
    // Over +10 % is red, and its bar starts at the centre.
    expect(rows[1]!.querySelector("[data-tone]")?.getAttribute("data-tone")).toBe("over");
    const fill = within(rows[1]!).getByTestId("variance-fill");
    expect(fill.style.left).toBe("50%");
    expect(fill.style.width).toBe("12%");
    // No main cause: a dash, not a link.
    expect(within(rows[2]!).getAllByRole("cell")[4]!.textContent).toBe("—");

    const note = screen.getByRole("note");
    expect(note.textContent).toContain(CALIBRATION_TITLE);
    expect(note.textContent).toContain("Suggestions need at least 5 closed Opportunities");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("links a group's main cause to the report filtered by it, keeping the other parameters", () => {
    renderReport(report(), parseReportParams({ group_by: "product", include_milestones: "true" }));
    const link = screen.getByRole("link", { name: "Integration complexity: show only this cause" });
    expect(link.getAttribute("href")).toBe(
      "/reports?group_by=product&cause=integration_complexity&include_milestones=true",
    );
  });

  it("expands a group to its Opportunities with the version and the Baseline marker", async () => {
    const u = userEvent.setup();
    const { container } = renderReport();
    const toggle = screen.getByRole("button", { name: "Show the Opportunities in REST API" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("link", { name: "Acme payments" })).toBeNull();

    await u.click(toggle);
    const hide = screen.getByRole("button", { name: "Hide the Opportunities in REST API" });
    expect(hide.getAttribute("aria-expanded")).toBe("true");
    const panel = document.getElementById(hide.getAttribute("aria-controls")!);
    expect(panel?.getAttribute("data-opportunity")).toBe(ALPHA_ID);
    const title = within(panel!).getByRole("link", { name: "Acme payments" });
    expect(title.getAttribute("href")).toBe(`/opportunities/${ALPHA_ID}/overview`);
    expect(within(panel!).getByText("v3")).toBeTruthy();
    expect(within(panel!).getByText("Baseline")).toBeTruthy();
    expect(
      within(panel!)
        .getByRole("link", { name: "Integration complexity: open the Actuals of Acme payments" })
        .getAttribute("href"),
    ).toBe(`/opportunities/${ALPHA_ID}/actuals`);
    expect(await axeViolations(container)).toEqual([]);

    // Not the Baseline: the version only.
    await u.click(screen.getByRole("button", { name: "Show the Opportunities in SFTP" }));
    const bravo = table().querySelector('[data-opportunity="0190a000-0000-7000-8000-000000000002"]');
    expect(within(bravo as HTMLElement).getByText("v1")).toBeTruthy();
    expect(within(bravo as HTMLElement).queryByText("Baseline")).toBeNull();

    await u.click(hide);
    expect(screen.queryByRole("link", { name: "Acme payments" })).toBeNull();
  });

  it("sorts by a header: descending, ascending, then the server's order", async () => {
    const u = userEvent.setup();
    renderReport(
      report({
        groups: [
          group({ key: "a", label: "Alpha", estimate_hours: 10, variance: variance(5, 1) }),
          group({ key: "b", label: "bravo", estimate_hours: 30, variance: variance(-20, -6) }),
          group({ key: "c", label: "Charlie", estimate_hours: 20, variance: variance(40, 8) }),
        ],
      }),
    );
    const header = (name: string) => screen.getByRole("columnheader", { name: new RegExp(name) });
    const sortBy = (name: string) => within(header(name)).getByRole("button");

    expect(groupLabels()).toEqual(["a", "b", "c"]);
    await u.click(sortBy("Variance"));
    expect(header("Variance").getAttribute("aria-sort")).toBe("descending");
    expect(groupLabels()).toEqual(["c", "a", "b"]);
    await u.click(sortBy("Variance"));
    expect(header("Variance").getAttribute("aria-sort")).toBe("ascending");
    expect(groupLabels()).toEqual(["b", "a", "c"]);
    await u.click(sortBy("Variance"));
    expect(header("Variance").getAttribute("aria-sort")).toBe("none");
    expect(groupLabels()).toEqual(["a", "b", "c"]);

    await u.click(sortBy("Estimate h"));
    expect(groupLabels()).toEqual(["b", "c", "a"]);
    expect(header("Variance").getAttribute("aria-sort")).toBe("none");
    // Names start ascending, ignoring case.
    await u.click(sortBy("Integration Type"));
    expect(header("Integration Type").getAttribute("aria-sort")).toBe("ascending");
    expect(groupLabels()).toEqual(["a", "b", "c"]);
  });

  it("titles the table after the grouping", () => {
    renderReport(report({ group_by: "cause" }), parseReportParams({ group_by: "cause" }));
    expect(screen.getByRole("table", { name: "Estimate versus actual by Cause" })).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: /^Cause/ })).toBeTruthy();
  });

  it("Export is disabled and says why", () => {
    renderReport();
    const exportButton = screen.getByRole("button", { name: /^Export/ });
    expect(exportButton.getAttribute("aria-disabled")).toBe("true");
    expect(exportButton.textContent).toContain("Export arrives in a later release");
  });

  it("no Actuals at all: the empty state only", async () => {
    const { container } = renderReport(report({ has_actuals: false, kpis: null, groups: [] }));
    expect(screen.getByText(EMPTY_TITLE)).toBeTruthy();
    expect(screen.getByText(EMPTY_BODY)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("group", { name: "Report filters" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("filters match nothing: the toolbar stays, with a message instead of KPIs and table", async () => {
    const { container } = renderReport(
      report({ kpis: null, groups: [] }),
      parseReportParams({ cause: "scope_change" }),
    );
    expect(screen.getByRole("group", { name: "Report filters" })).toBeTruthy();
    expect(screen.getByText(NO_MATCH)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByRole("region", { name: "Estimate accuracy" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });
});
