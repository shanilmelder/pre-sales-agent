import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Filters } from "@/app/opportunities/filters";
import type { OpportunityFacets } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const push = vi.hoisted(() => vi.fn());
const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace, prefetch: vi.fn(), back: vi.fn() }),
}));

import { FilterBar, RANGE_ERROR, SELECTED_OWNER } from "./filter-bar";

const A = { id: "00000000-0000-7000-8000-0000000000a1", name: "[OWNER A]" };
const B = { id: "00000000-0000-7000-8000-0000000000b2", name: "[OWNER B]" };
const FACETS: OpportunityFacets = { owners: [A, B], products: ["AutoStore", "Pick station"] };

function bar(filters: Filters = {}, facets: OpportunityFacets | null = FACETS) {
  return <FilterBar basePath="/opportunities" filters={filters} facets={facets} />;
}

function renderBar(filters: Filters = {}, facets: OpportunityFacets | null = FACETS) {
  return render(bar(filters, facets));
}

const select = (label: string) => screen.getByLabelText(label) as HTMLSelectElement;
const input = (label: string) => screen.getByLabelText(label) as HTMLInputElement;
/** The last URL the bar navigated to (always `replace`, without scrolling). */
function lastHref() {
  expect(replace.mock.lastCall?.[1]).toEqual({ scroll: false });
  return replace.mock.lastCall?.[0];
}
const typeDate = (label: string, value: string) =>
  fireEvent.change(input(label), { target: { value } });

const options = (label: string) =>
  within(screen.getByLabelText(label)).getAllByRole("option").map((o) => o.textContent);

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
});

describe("FilterBar", () => {
  it("has labelled status, owner, product and date controls fed by the facets", async () => {
    const { container } = renderBar();
    expect(screen.getByRole("group", { name: "Filters" })).toBeTruthy();
    expect(options("Status")).toEqual([
      "Any status",
      "Intake",
      "Gaps open",
      "Assessing",
      "Estimating",
      "In review",
      "Baselined",
      "Delivered",
      "Closed",
    ]);
    expect(options("Owner")).toEqual(["Any owner", "[OWNER A]", "[OWNER B]"]);
    expect(options("Product")).toEqual(["Any product", "AutoStore", "Pick station"]);
    expect(screen.getByLabelText("Target date from").getAttribute("type")).toBe("date");
    expect(screen.getByLabelText("Target date to").getAttribute("type")).toBe("date");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows the applied filters", () => {
    renderBar({ status: "intake", owner: B.id, product: "pick STATION", from: "2026-11-01" });
    expect((screen.getByLabelText("Status") as HTMLSelectElement).value).toBe("intake");
    expect((screen.getByLabelText("Owner") as HTMLSelectElement).value).toBe(B.id);
    // Matched to the facet's spelling, ignoring case.
    expect((screen.getByLabelText("Product") as HTMLSelectElement).value).toBe("Pick station");
    expect((screen.getByLabelText("Target date from") as HTMLInputElement).value).toBe(
      "2026-11-01",
    );
    expect(screen.getByLabelText("Target date to").getAttribute("min")).toBe("2026-11-01");
  });

  it("replaces the URL on each change, on page 1, keeping the other filters", async () => {
    const user = userEvent.setup();
    renderBar({ status: "intake" });

    await user.selectOptions(select("Owner"), "[OWNER A]");
    expect(lastHref()).toBe(`/opportunities?status=intake&owner=${A.id}`);

    await user.selectOptions(select("Product"), "Pick station");
    expect(lastHref()).toBe(`/opportunities?status=intake&owner=${A.id}&product=Pick+station`);

    typeDate("Target date to", "2026-11-30");
    expect(lastHref()).toBe(
      `/opportunities?status=intake&owner=${A.id}&product=Pick+station&to=2026-11-30`,
    );

    await user.selectOptions(select("Status"), "Any status");
    expect(lastHref()).toBe(`/opportunities?owner=${A.id}&product=Pick+station&to=2026-11-30`);
    for (const [href] of replace.mock.calls) expect(href).not.toContain("page=");
    expect(push).not.toHaveBeenCalled();
  });

  it("typing a year navigates once, when the date is complete", () => {
    renderBar();
    // What a date input reports while the year is typed digit by digit.
    for (const partial of ["0002-11-01", "0020-11-01", "0202-11-01"]) {
      typeDate("Target date from", partial);
      expect(input("Target date from").value).toBe(partial);
    }
    expect(replace).not.toHaveBeenCalled();
    typeDate("Target date from", "2026-11-01");
    expect(replace).toHaveBeenCalledTimes(1);
    expect(lastHref()).toBe("/opportunities?from=2026-11-01");
    fireEvent.blur(input("Target date from"));
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it("partial or invalid dates don't navigate; blur commits a valid one; clearing commits", () => {
    renderBar({ to: "2026-11-30" });
    typeDate("Target date from", "0202-11-01");
    typeDate("Target date from", "2026-02-30");
    expect(replace).not.toHaveBeenCalled();
    typeDate("Target date from", "0999-01-01");
    expect(replace).not.toHaveBeenCalled();
    fireEvent.blur(input("Target date from"));
    expect(lastHref()).toBe("/opportunities?from=0999-01-01&to=2026-11-30");
    typeDate("Target date to", "");
    expect(lastHref()).toBe("/opportunities?from=0999-01-01");
  });

  it("a From after To isn't applied: both fields say why, announced", async () => {
    const { container } = renderBar({ to: "2026-11-30" });
    typeDate("Target date from", "2026-12-01");
    expect(replace).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe(RANGE_ERROR);
    for (const label of ["Target date from", "Target date to"]) {
      expect(input(label).getAttribute("aria-invalid")).toBe("true");
      expect(input(label).getAttribute("aria-describedby")).toBe(alert.id);
    }
    expect(input("Target date from").value).toBe("2026-12-01");
    expect(await axeViolations(container)).toEqual([]);

    typeDate("Target date from", "2026-11-30");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(lastHref()).toBe("/opportunities?from=2026-11-30&to=2026-11-30");
  });

  it("Clear filters returns every control to Any and replaces the URL", async () => {
    const user = userEvent.setup();
    renderBar({ status: "intake", owner: A.id, product: "AutoStore", from: "2026-11-01" });
    await user.click(screen.getByRole("link", { name: "Clear filters" }));
    expect(lastHref()).toBe("/opportunities");
    expect(select("Status").value).toBe("");
    expect(select("Owner").value).toBe("");
    expect(select("Product").value).toBe("");
    expect(input("Target date from").value).toBe("");
    expect(input("Target date to").value).toBe("");
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
  });

  it("shows new filters when the URL changes", () => {
    const view = renderBar({ owner: A.id });
    view.rerender(bar({ owner: B.id, status: "closed", to: "2026-11-30" }));
    expect(select("Owner").value).toBe(B.id);
    expect(select("Status").value).toBe("closed");
    expect(input("Target date to").value).toBe("2026-11-30");
    view.rerender(bar({}));
    expect(select("Owner").value).toBe("");
    expect(select("Status").value).toBe("");
    expect(input("Target date to").value).toBe("");
  });

  it("keeps a pending selection when the parent rerenders with equal filters", async () => {
    const user = userEvent.setup();
    const view = renderBar({ status: "intake" });
    await user.selectOptions(select("Owner"), "[OWNER B]");
    view.rerender(bar({ status: "intake" })); // a new object, equal by value
    expect(select("Owner").value).toBe(B.id);
    expect(select("Status").value).toBe("intake");
  });

  it("Clear filters links to the unfiltered list, and is disabled with nothing to clear", () => {
    const { unmount } = renderBar({ owner: A.id, to: "2026-11-30" });
    expect(screen.getByRole("link", { name: "Clear filters" }).getAttribute("href")).toBe(
      "/opportunities",
    );
    unmount();
    renderBar();
    const button = screen.getByRole("button", { name: "Clear filters" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("keeps a filter from a shared URL that isn't among the facets, and works without facets", () => {
    const unknown = "00000000-0000-7000-8000-0000000000ff";
    renderBar({ owner: unknown, product: "Legacy" }, null);
    expect(options("Owner")).toEqual(["Any owner", SELECTED_OWNER]);
    expect((screen.getByLabelText("Owner") as HTMLSelectElement).value).toBe(unknown);
    expect(options("Product")).toEqual(["Any product", "Legacy"]);
  });

  it("the controls are reachable with Tab in order", async () => {
    const user = userEvent.setup();
    renderBar({ owner: A.id });
    const order = ["Status", "Owner", "Product", "Target date from", "Target date to"];
    for (const label of order) {
      await user.tab();
      expect(document.activeElement).toBe(screen.getByLabelText(label));
    }
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Clear filters" }));
  });
});
