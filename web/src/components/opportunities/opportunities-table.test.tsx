import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OpportunitySummary } from "@/lib/opportunities";
import { axeViolations } from "@/test/axe";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
}));

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
    open_gaps: 3,
    open_conflicts: 2,
    blocker_count: 0,
    estimate: { version: 3, status: "draft", total_hours: 278, is_baseline: false },
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
      <OpportunitiesTable items={items} caption="Opportunities" canCreate={canCreate} />
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

beforeEach(() => {
  push.mockReset();
});

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

  it("shows title and customer, status, owner, date, open items and Estimate", async () => {
    vi.useFakeTimers();
    const { container } = renderTable();
    await pastSkeleton();
    expect(container.querySelector('[data-testid="opportunities-card"] table')).toBeTruthy();
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Opportunity",
      "Status",
      "Owner",
      "Proposal date",
      "Open items",
      "Estimate",
    ]);
    expect(screen.getAllByRole("columnheader")[5].className).toContain("text-right");
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(4);
    const cells = rows[1].querySelectorAll("td");
    expect(cells[0].textContent).toBe("[TITLE 1][CUSTOMER 1]");
    expect(cells[1].textContent).toContain("Intake");
    expect(cells[1].querySelector("svg[aria-hidden='true']")).toBeTruthy();
    // The initials avatar (hidden from assistive tech), then the name.
    expect(cells[2].querySelector("[aria-hidden='true']")?.textContent).toBe("[1");
    expect(cells[2].textContent).toBe("[1[OWNER 1]");
    expect(cells[3].textContent).toBe("1 Nov 2026");
    expect(cells[4].textContent).toBe("3 gaps · 2 conflicts");
    expect(cells[5].textContent).toBe("278.0 hDraft v3");
    expect(row("[TITLE 1]").getAttribute("href")).toBe(`/opportunities/${ITEMS[0].id}`);
  });

  it("open items: singular for one, toned only above zero", async () => {
    vi.useFakeTimers();
    renderTable({
      items: [
        { ...item(1), open_gaps: 1, open_conflicts: 0 },
        { ...item(2), open_gaps: 0, open_conflicts: 1 },
      ],
    });
    await pastSkeleton();
    const [, first, second] = screen.getAllByRole("row");
    expect(first.querySelectorAll("td")[4].textContent).toBe("1 gap · 0 conflicts");
    expect(screen.getByText("1 gap").className).toContain("text-gap");
    expect(screen.getByText("0 conflicts").className).toContain("text-text-secondary");
    expect(second.querySelectorAll("td")[4].textContent).toBe("0 gaps · 1 conflict");
    expect(screen.getByText("0 gaps").className).toContain("text-text-secondary");
    expect(screen.getByText("1 conflict").className).toContain("text-blocker");
  });

  it("open items: submission blockers as 'N to submit', blocker toned (Story 8.6)", async () => {
    vi.useFakeTimers();
    renderTable({ items: [{ ...item(1), blocker_count: 6 }, item(2)] });
    await pastSkeleton();
    const [, first, second] = screen.getAllByRole("row");
    expect(first.querySelectorAll("td")[4].textContent).toBe("3 gaps · 2 conflicts · 6 to submit");
    expect(screen.getByText("6 to submit").className).toContain("text-blocker");
    expect(second.querySelectorAll("td")[4].textContent).toBe("3 gaps · 2 conflicts");
  });

  it("Estimate: one decimal with thousands separators; a dash with no draft", async () => {
    vi.useFakeTimers();
    renderTable({
      items: [
        {
          ...item(1),
          estimate: { version: 2, status: "submitted", total_hours: 6644, is_baseline: false },
        },
        { ...item(2), estimate: null },
        {
          ...item(3),
          estimate: { version: 3, status: "in_review", total_hours: 120, is_baseline: false },
        },
        {
          ...item(4),
          estimate: { version: 4, status: "approved", total_hours: 842, is_baseline: true },
        },
      ],
    });
    await pastSkeleton();
    const [, first, second, third, fourth] = screen.getAllByRole("row");
    expect(first.querySelectorAll("td")[5].textContent).toBe("6,644.0 hSubmitted v2");
    expect(second.querySelectorAll("td")[5].textContent).toBe("—No estimate");
    // Story 9.1.
    expect(third.querySelectorAll("td")[5].textContent).toBe("120.0 hIn review v3");
    // Story 9.7: the Baseline, with the anchor.
    const cell = fourth!.querySelectorAll("td")[5]!;
    expect(cell.textContent).toBe("842.0 hBaseline v4");
    expect(cell.querySelector("[data-baseline] svg")).not.toBeNull();
  });

  it("a row click opens the Opportunity; link and modified clicks don't", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    const owner = screen.getByText("[OWNER 2]");
    fireEvent.click(owner);
    expect(push).toHaveBeenCalledWith(`/opportunities/${ITEMS[1].id}`);
    push.mockReset();
    fireEvent.click(owner, { ctrlKey: true });
    fireEvent.click(owner, { metaKey: true });
    fireEvent.click(owner, { shiftKey: true });
    fireEvent.click(owner, { button: 1 });
    fireEvent.click(owner, { altKey: true });
    const link = row("[TITLE 2]");
    link.addEventListener("click", (event) => event.preventDefault());
    fireEvent.click(link);
    expect(push).not.toHaveBeenCalled();
    // Rows add no Tab stops: the title link stays the only one.
    const focusable = document.querySelectorAll("tbody [tabindex='0']");
    expect(Array.from(focusable)).toEqual([row("[TITLE 1]")]);
  });

  it("ending a drag-select of a row's text doesn't open the Opportunity", async () => {
    vi.useFakeTimers();
    renderTable();
    await pastSkeleton();
    const customer = screen.getByText("[CUSTOMER 2]");
    const range = document.createRange();
    range.selectNodeContents(customer);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.click(customer);
    expect(push).not.toHaveBeenCalled();
    window.getSelection()?.removeAllRanges();
    fireEvent.click(customer);
    expect(push).toHaveBeenCalledWith(`/opportunities/${ITEMS[1].id}`);
  });

  it("empty: a card with New Opportunity for creators, none for everyone else", async () => {
    vi.useFakeTimers();
    const creator = renderTable({ items: [] });
    await pastSkeleton();
    const title = screen.getByText("No Opportunities yet");
    expect(title.closest('[data-testid="opportunities-card"]')).toBeTruthy();
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

  it("skeleton rows have six cells, inside the card", () => {
    vi.useFakeTimers();
    const { container } = renderTable();
    expect(container.querySelector("[data-skeleton-row]")?.querySelectorAll("td")).toHaveLength(6);
    const card = container.querySelector('[data-testid="opportunities-card"]');
    expect(card?.querySelector("[data-skeleton-row]")).toBeTruthy();
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
    const text = screen.getByText(/No Opportunities match these filters/);
    expect(text.closest('[data-testid="opportunities-card"]')).toBeTruthy();
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
