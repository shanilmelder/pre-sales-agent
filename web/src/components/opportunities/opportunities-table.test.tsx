import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OpportunitySummary } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

import { ShellProviders } from "../shell/shell-context";
import { OpportunitiesTable } from "./opportunities-table";

function item(n: number): OpportunitySummary {
  return {
    id: `00000000-0000-7000-8000-00000000000${n}`,
    title: `[TITLE ${n}]`,
    customer_name: `[CUSTOMER ${n}]`,
    status: "intake",
    owner: { id: "00000000-0000-7000-8000-0000000000aa", name: `[OWNER ${n}]` },
    target_proposal_date: "2026-11-0" + n,
    created_at: "2026-10-04T10:00:00Z",
  };
}

const ITEMS = [item(1), item(2), item(3)];

function renderTable({
  items = ITEMS,
  canCreate = true,
  singleKeyShortcuts = true,
}: { items?: OpportunitySummary[]; canCreate?: boolean; singleKeyShortcuts?: boolean } = {}) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <OpportunitiesTable items={items} caption="My Opportunities" canCreate={canCreate} />
      <button type="button">After</button>
    </ShellProviders>,
  );
}

/** Lets the first-load skeleton time out. */
async function pastSkeleton() {
  await act(async () => {
    vi.advanceTimersByTime(150);
  });
}

const row = (name: string) => screen.getByRole("link", { name });

afterEach(() => {
  vi.useRealTimers();
});

describe("OpportunitiesTable", () => {
  it("shows skeleton rows for at least 150 ms on first load", async () => {
    vi.useFakeTimers();
    const { container } = renderTable();
    expect(container.querySelectorAll("[data-skeleton-row]").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link")).toBeNull();
    await act(async () => {
      vi.advanceTimersByTime(149);
    });
    expect(container.querySelectorAll("[data-skeleton-row]").length).toBeGreaterThan(0);
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(container.querySelectorAll("[data-skeleton-row]")).toHaveLength(0);
    expect(row("[TITLE 1]")).toBeTruthy();
  });

  it("shows title with customer, status (icon and label), owner and proposal date in padded rows", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Opportunity",
      "Status",
      "Owner",
      "Proposal date",
    ]);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(rows[1].className).toContain("min-h-row");
    expect(rows[1].textContent).toContain("[CUSTOMER 1]");
    expect(rows[1].textContent).toContain("Intake");
    expect(rows[1].querySelector("svg[aria-hidden='true']")).toBeTruthy();
    expect(rows[1].textContent).toContain("[OWNER 1]");
    expect(rows[1].textContent).toContain("1 Nov 2026");
    expect(row("[TITLE 1]").getAttribute("href")).toBe(`/opportunities/${ITEMS[0].id}`);
  });

  it("empty: a card with New Opportunity for creators, none for everyone else", async () => {
    vi.useFakeTimers();
    const creator = renderTable({ items: [] });
    await pastSkeleton();
    expect(screen.getByText("No Opportunities yet")).toBeTruthy();
    expect(
      screen.getByText(
        "Create an Opportunity from a customer email, transcript or RFP. The first file becomes its first Source.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "New Opportunity" }).getAttribute("href")).toBe(
      "/opportunities/new",
    );
    creator.unmount();
    renderTable({ items: [], canCreate: false });
    await pastSkeleton();
    expect(screen.getByText("No Opportunities yet")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "New Opportunity" })).toBeNull();
  });

  it("skeleton rows have four cells", () => {
    vi.useFakeTimers();
    const { container } = renderTable();
    expect(container.querySelector("[data-skeleton-row]")?.querySelectorAll("td")).toHaveLength(4);
    expect(container.querySelector("table")?.getAttribute("aria-busy")).toBe("true");
  });

  it("filtered empty keeps its sentence and Clear filters", async () => {
    vi.useFakeTimers();
    render(
      <ShellProviders singleKeyShortcuts>
        <OpportunitiesTable items={[]} caption="All" canCreate clearFiltersHref="/opportunities" />
      </ShellProviders>,
    );
    await pastSkeleton();
    expect(screen.getByText(/No Opportunities match these filters/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Clear filters" }).getAttribute("href")).toBe(
      "/opportunities",
    );
  });

  it("empty card has no axe violations", async () => {
    const { container } = renderTable({ items: [] });
    expect(await axeViolations(container)).toEqual([]);
    expect(await screen.findByText("No Opportunities yet")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("j/k and the arrow keys move between rows; the list is one Tab stop", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    vi.useRealTimers();
    const user = userEvent.setup();
    await user.tab();
    expect(document.activeElement).toBe(row("[TITLE 1]"));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("[TITLE 2]"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("[TITLE 3]"));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("[TITLE 3]"));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row("[TITLE 2]"));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "After" }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(row("[TITLE 2]"));
  });

  it("Enter on a row follows its link to the Opportunity", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    vi.useRealTimers();
    const user = userEvent.setup();
    const clicked = vi.fn((event: MouseEvent) => event.preventDefault());
    row("[TITLE 2]").addEventListener("click", clicked);
    await user.tab();
    await user.keyboard("j{Enter}");
    expect(clicked).toHaveBeenCalledTimes(1);
  });

  it("j/k are off with single-key shortcuts off; arrows still work", async () => {
    vi.useFakeTimers();
    renderTable({ singleKeyShortcuts: false });
    await pastSkeleton();
    vi.useRealTimers();
    const user = userEvent.setup();
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("[TITLE 1]"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("[TITLE 2]"));
  });

  it("has no WCAG 2.1 AA violations, loading or loaded", async () => {
    const { container } = renderTable();
    expect(await axeViolations(container)).toEqual([]);
    expect(await screen.findAllByRole("link")).toHaveLength(3);
    expect(await axeViolations(container)).toEqual([]);
  });
});
