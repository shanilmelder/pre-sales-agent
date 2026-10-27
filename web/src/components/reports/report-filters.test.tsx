import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { parseReportParams } from "@/lib/reports";
import { axeViolations } from "@/test/axe";
import { report } from "@/test/report-fixtures";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace, prefetch: vi.fn(), back: vi.fn() }),
}));

import { ReportFilters } from "./report-filters";

const WP = "0190c000-0000-7000-8000-000000000001";

function renderFilters(search: Record<string, string> = {}) {
  return render(<ReportFilters params={parseReportParams(search)} options={report().options} />);
}

const select = (label: string) => screen.getByLabelText(label) as HTMLSelectElement;
const options = (label: string) =>
  within(select(label))
    .getAllByRole("option")
    .map((o) => o.textContent);
function lastHref() {
  expect(replace.mock.lastCall?.[1]).toEqual({ scroll: false });
  return replace.mock.lastCall?.[0];
}

beforeEach(() => replace.mockReset());

describe("ReportFilters", () => {
  it("lists the groupings and the report's options", async () => {
    const { container } = renderFilters();
    expect(options("Group by")).toEqual([
      "Integration Type",
      "Opportunity",
      "Product",
      "Work Package",
      "Cause",
    ]);
    expect(select("Group by").value).toBe("integration_type");
    expect(options("Product")).toEqual(["All products", "Payments", "Logistics"]);
    expect(options("Work Package")).toEqual(["All Work Packages", "Discovery"]);
    expect(options("Cause")).toEqual(["All causes", "Integration complexity", "Scope change"]);
    expect(screen.getByRole("switch", { name: "Include milestones" }).getAttribute("aria-checked")).toBe(
      "false",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("keeps the grouping in the URL with the filters already applied", async () => {
    const u = userEvent.setup();
    renderFilters({ product: "Payments", closed_from: "2026-01-01" });
    await u.selectOptions(select("Group by"), "cause");
    expect(lastHref()).toBe("/reports?group_by=cause&product=Payments&closed_from=2026-01-01");
    // The default grouping is left out of the URL.
    await u.selectOptions(select("Group by"), "integration_type");
    expect(lastHref()).toBe("/reports?product=Payments&closed_from=2026-01-01");
  });

  it("each filter writes its parameter, and choosing 'All' removes it", async () => {
    const u = userEvent.setup();
    const view = renderFilters({ group_by: "product" });
    await u.selectOptions(select("Product"), "Logistics");
    expect(lastHref()).toBe("/reports?group_by=product&product=Logistics");
    await u.selectOptions(select("Work Package"), WP);
    expect(lastHref()).toBe(`/reports?group_by=product&work_package_id=${WP}`);
    await u.selectOptions(select("Cause"), "scope_change");
    expect(lastHref()).toBe("/reports?group_by=product&cause=scope_change");
    view.unmount();

    renderFilters({ cause: "scope_change" });
    await u.selectOptions(select("Cause"), "");
    expect(lastHref()).toBe("/reports");
  });

  it("filters by closed date and toggles milestones", async () => {
    const u = userEvent.setup();
    renderFilters({ closed_to: "2026-06-30" });
    const from = screen.getByLabelText("Closed from") as HTMLInputElement;
    expect(from.max).toBe("2026-06-30");
    fireEvent.change(from, { target: { value: "2026-01-01" } });
    expect(lastHref()).toBe("/reports?closed_from=2026-01-01&closed_to=2026-06-30");
    fireEvent.change(screen.getByLabelText("Closed to"), { target: { value: "" } });
    expect(lastHref()).toBe("/reports");

    await u.click(screen.getByRole("switch", { name: "Include milestones" }));
    expect(lastHref()).toBe("/reports?closed_to=2026-06-30&include_milestones=true");
  });

  it("keeps a URL's product and Work Package selectable when no row carries them now", () => {
    renderFilters({ product: "payments", work_package_id: "0190c000-0000-7000-8000-0000000000ff" });
    // Products match without case.
    expect(select("Product").value).toBe("Payments");
    expect(options("Work Package")).toEqual([
      "All Work Packages",
      "Discovery",
      "Selected Work Package",
    ]);
    expect(select("Work Package").value).toBe("0190c000-0000-7000-8000-0000000000ff");
  });
});
