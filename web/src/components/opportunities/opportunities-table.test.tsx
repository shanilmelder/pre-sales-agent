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
    expect(row("[CUSTOMER 1]")).toBeTruthy();
  });

  it("shows customer, status (icon and label), owner and target date in 32px rows", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Customer",
      "Status",
      "Owner",
      "Target proposal date",
    ]);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(rows[1].className).toContain("h-row");
    expect(rows[1].textContent).toContain("Intake");
    expect(rows[1].querySelector("svg[aria-hidden='true']")).toBeTruthy();
    expect(rows[1].textContent).toContain("[OWNER 1]");
    expect(rows[1].textContent).toContain("1 Nov 2026");
    expect(row("[CUSTOMER 1]").getAttribute("href")).toBe(`/opportunities/${ITEMS[0].id}`);
  });

  it("empty: the create sentence for creators, a plain one for everyone else", async () => {
    vi.useFakeTimers();
    const creator = renderTable({ items: [] });
    await pastSkeleton();
    expect(screen.getByText("No Opportunities yet. Press c to create one.")).toBeTruthy();
    creator.unmount();
    renderTable({ items: [], canCreate: false });
    await pastSkeleton();
    expect(screen.getByText("No Opportunities yet.")).toBeTruthy();
    expect(screen.queryByText(/Press c/)).toBeNull();
  });

  it("j/k and the arrow keys move between rows; the list is one Tab stop", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    vi.useRealTimers();
    const user = userEvent.setup();
    await user.tab();
    expect(document.activeElement).toBe(row("[CUSTOMER 1]"));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("[CUSTOMER 2]"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("[CUSTOMER 3]"));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("[CUSTOMER 3]"));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row("[CUSTOMER 2]"));
    await user.tab();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "After" }));
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(row("[CUSTOMER 2]"));
  });

  it("Enter on a row follows its link to the Opportunity", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    vi.useRealTimers();
    const user = userEvent.setup();
    const clicked = vi.fn((event: MouseEvent) => event.preventDefault());
    row("[CUSTOMER 2]").addEventListener("click", clicked);
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
    expect(document.activeElement).toBe(row("[CUSTOMER 1]"));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("[CUSTOMER 2]"));
  });

  it("has no WCAG 2.1 AA violations, loading or loaded", async () => {
    const { container } = renderTable();
    expect(await axeViolations(container)).toEqual([]);
    expect(await screen.findAllByRole("link")).toHaveLength(3);
    expect(await axeViolations(container)).toEqual([]);
  });
});
