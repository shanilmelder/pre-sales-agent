import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

/** A filter chip, by its label (it may also show the applied value: "Status: Intake"). */
const chip = (label: string) =>
  screen.getByRole("button", { name: new RegExp(`^${label}(: .*)?$`) });

/** Opens a chip's popover; its labelled control(s) are inside. */
async function open(label: string) {
  fireEvent.click(chip(label));
  await screen.findByRole("dialog", { name: `${label} filter` });
}

beforeEach(() => {
  push.mockReset();
  replace.mockReset();
  // Chips leave out the year inside the current UTC year: pin "today".
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-23T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("FilterBar", () => {
  it("shows a dashed chip per filter; each opens its labelled control(s)", async () => {
    const { container } = renderBar();
    const group = screen.getByRole("group", { name: "Filters" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Status",
      "Owner",
      "Product",
      "Proposal date",
    ]);
    expect(chip("Status").className).toContain("border-dashed");
    expect(screen.queryByLabelText("Status")).toBeNull();
    expect(screen.queryByRole("link", { name: "Clear filters" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);

    await open("Status");
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
    expect(await axeViolations(document.body)).toEqual([]);
    await open("Owner");
    expect(options("Owner")).toEqual(["Any owner", "[OWNER A]", "[OWNER B]"]);
    await open("Product");
    expect(options("Product")).toEqual(["Any product", "AutoStore", "Pick station"]);
    await open("Proposal date");
    expect(screen.getByLabelText("Target date from").getAttribute("type")).toBe("date");
    expect(screen.getByLabelText("Target date to").getAttribute("type")).toBe("date");
  });

  it("an applied filter shows its value on a solid chip, and inside its popover", async () => {
    renderBar({
      status: "intake",
      owner: B.id,
      product: "pick STATION",
      from: "2026-11-01",
      to: "2026-11-15",
    });
    expect(chip("Status").textContent).toBe("Status: Intake");
    expect(chip("Status").className).toContain("bg-primary-tint");
    expect(chip("Status").className).not.toContain("border-dashed");
    expect(chip("Owner").textContent).toBe("Owner: [OWNER B]");
    // Matched to the facet's spelling, ignoring case.
    expect(chip("Product").textContent).toBe("Product: Pick station");
    expect(chip("Proposal date").textContent).toBe("Proposal date: 1 Nov – 15 Nov");

    await open("Status");
    expect(select("Status").value).toBe("intake");
    await open("Owner");
    expect(select("Owner").value).toBe(B.id);
    await open("Product");
    expect(select("Product").value).toBe("Pick station");
    await open("Proposal date");
    expect(input("Target date from").value).toBe("2026-11-01");
    expect(input("Target date to").getAttribute("min")).toBe("2026-11-01");
  });

  it("a one-sided date range reads from or until", () => {
    const view = renderBar({ from: "2026-11-01" });
    expect(chip("Proposal date").textContent).toBe("Proposal date: from 1 Nov");
    view.rerender(bar({ to: "2026-11-15" }));
    expect(chip("Proposal date").textContent).toBe("Proposal date: until 15 Nov");
  });

  it("picking Status Intake replaces the URL and the chip reads it", async () => {
    const user = userEvent.setup();
    renderBar();
    await user.click(chip("Status"));
    await user.selectOptions(select("Status"), "Intake");
    expect(lastHref()).toBe("/opportunities?status=intake");
    expect(chip("Status").textContent).toBe("Status: Intake");
    // One pick completes the filter: the popover closes.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("Status, Owner and Product close after a pick; Proposal date stays open", async () => {
    const user = userEvent.setup();
    renderBar();
    for (const [label, option] of [
      ["Owner", "[OWNER A]"],
      ["Product", "AutoStore"],
    ] as const) {
      await user.click(chip(label));
      await user.selectOptions(select(label), option);
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    }
    await user.click(chip("Proposal date"));
    typeDate("Target date from", "2026-11-01");
    expect(screen.getByRole("dialog", { name: "Proposal date filter" })).toBeTruthy();
    expect(input("Target date to")).toBeTruthy();
  });

  it("the date chip shows years across years or outside the current one", () => {
    const view = renderBar({ from: "2026-12-20", to: "2027-01-10" });
    expect(chip("Proposal date").textContent).toBe("Proposal date: 20 Dec 2026 – 10 Jan 2027");
    view.rerender(bar({ from: "2027-02-01", to: "2027-02-15" }));
    expect(chip("Proposal date").textContent).toBe("Proposal date: 1 Feb 2027 – 15 Feb 2027");
    view.rerender(bar({ to: "2025-12-01" }));
    expect(chip("Proposal date").textContent).toBe("Proposal date: until 1 Dec 2025");
    view.rerender(bar({ from: "2026-11-01", to: "2026-11-15" }));
    expect(chip("Proposal date").textContent).toBe("Proposal date: 1 Nov – 15 Nov");
  });

  it("replaces the URL on each change, on page 1, keeping the other filters", async () => {
    const user = userEvent.setup();
    renderBar({ status: "intake" });

    await user.click(chip("Owner"));
    await user.selectOptions(select("Owner"), "[OWNER A]");
    expect(lastHref()).toBe(`/opportunities?status=intake&owner=${A.id}`);

    await user.click(chip("Product"));
    await user.selectOptions(select("Product"), "Pick station");
    expect(lastHref()).toBe(`/opportunities?status=intake&owner=${A.id}&product=Pick+station`);

    await user.click(chip("Proposal date"));
    typeDate("Target date to", "2026-11-30");
    expect(lastHref()).toBe(
      `/opportunities?status=intake&owner=${A.id}&product=Pick+station&to=2026-11-30`,
    );

    await user.click(chip("Status"));
    await user.selectOptions(select("Status"), "Any status");
    expect(lastHref()).toBe(`/opportunities?owner=${A.id}&product=Pick+station&to=2026-11-30`);
    for (const [href] of replace.mock.calls) expect(href).not.toContain("page=");
    expect(push).not.toHaveBeenCalled();
  });

  it("typing a year navigates once, when the date is complete", async () => {
    renderBar();
    await open("Proposal date");
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

  it("partial or invalid dates don't navigate; blur or a cleared field commits", async () => {
    renderBar({ to: "2026-11-30" });
    await open("Proposal date");
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
    renderBar({ to: "2026-11-30" });
    await open("Proposal date");
    typeDate("Target date from", "2026-12-01");
    expect(replace).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe(RANGE_ERROR);
    for (const label of ["Target date from", "Target date to"]) {
      expect(input(label).getAttribute("aria-invalid")).toBe("true");
      expect(input(label).getAttribute("aria-describedby")).toBe(alert.id);
    }
    expect(input("Target date from").value).toBe("2026-12-01");
    expect(await axeViolations(document.body)).toEqual([]);

    typeDate("Target date from", "2026-11-30");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(lastHref()).toBe("/opportunities?from=2026-11-30&to=2026-11-30");
  });

  it("Clear filters returns every chip and control to Any and replaces the URL", async () => {
    const user = userEvent.setup();
    renderBar({ status: "intake", owner: A.id, product: "AutoStore", from: "2026-11-01" });
    await user.click(screen.getByRole("link", { name: "Clear filters" }));
    expect(lastHref()).toBe("/opportunities");
    for (const label of ["Status", "Owner", "Product", "Proposal date"]) {
      expect(chip(label).textContent).toBe(label);
    }
    expect(screen.queryByRole("link", { name: "Clear filters" })).toBeNull();
    await open("Status");
    expect(select("Status").value).toBe("");
    await open("Proposal date");
    expect(input("Target date from").value).toBe("");
    expect(input("Target date to").value).toBe("");
  });

  it("shows new filters when the URL changes", () => {
    const view = renderBar({ owner: A.id });
    view.rerender(bar({ owner: B.id, status: "closed", to: "2026-11-30" }));
    expect(chip("Owner").textContent).toBe("Owner: [OWNER B]");
    expect(chip("Status").textContent).toBe("Status: Closed");
    expect(chip("Proposal date").textContent).toBe("Proposal date: until 30 Nov");
    view.rerender(bar({}));
    expect(chip("Owner").textContent).toBe("Owner");
    expect(chip("Status").textContent).toBe("Status");
    expect(chip("Proposal date").textContent).toBe("Proposal date");
  });

  it("keeps a pending selection when the parent rerenders with equal filters", async () => {
    const user = userEvent.setup();
    const view = renderBar({ status: "intake" });
    await user.click(chip("Owner"));
    await user.selectOptions(select("Owner"), "[OWNER B]");
    view.rerender(bar({ status: "intake" })); // a new object, equal by value
    expect(chip("Owner").textContent).toBe("Owner: [OWNER B]");
    expect(chip("Status").textContent).toBe("Status: Intake");
  });

  it("Clear filters is a link to the unfiltered list, shown only with a filter applied", () => {
    const { unmount } = renderBar({ owner: A.id, to: "2026-11-30" });
    expect(screen.getByRole("link", { name: "Clear filters" }).getAttribute("href")).toBe(
      "/opportunities",
    );
    unmount();
    renderBar();
    expect(screen.queryByRole("link", { name: "Clear filters" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });

  it("keeps a shared URL's filter missing from the facets; works without facets", async () => {
    const unknown = "00000000-0000-7000-8000-0000000000ff";
    renderBar({ owner: unknown, product: "Legacy" }, null);
    expect(chip("Owner").textContent).toBe(`Owner: ${SELECTED_OWNER}`);
    await open("Owner");
    expect(options("Owner")).toEqual(["Any owner", SELECTED_OWNER]);
    expect(select("Owner").value).toBe(unknown);
    await open("Product");
    expect(options("Product")).toEqual(["Any product", "Legacy"]);
  });

  it("chips and Clear filters are Tab stops in order; Enter opens a chip", async () => {
    const user = userEvent.setup();
    renderBar({ owner: A.id });
    for (const label of ["Status", "Owner", "Product", "Proposal date"]) {
      await user.tab();
      expect(document.activeElement).toBe(chip(label));
    }
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("link", { name: "Clear filters" }));
    await user.tab({ shift: true });
    await user.keyboard("{Enter}");
    expect(await screen.findByLabelText("Target date from")).toBeTruthy();
  });
});
