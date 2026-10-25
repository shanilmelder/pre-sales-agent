import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { InboxItem, InboxPage } from "@/lib/inbox";
import { axeViolations } from "@/test/axe";

const actions = vi.hoisted(() => ({
  getInbox: vi.fn(),
  getInboxUnreadCount: vi.fn(),
  markInboxItemRead: vi.fn(),
  markAllInboxRead: vi.fn(),
}));
vi.mock("@/app/inbox/actions", () => actions);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/inbox",
}));

import { ShellProviders } from "@/components/shell/shell-context";
import { resetInboxUnread, useInboxUnread } from "@/lib/use-inbox-count";

import { InboxView } from "./inbox-view";

const OPP = "00000000-0000-7000-8000-0000000000aa";

function item(n: number, overrides: Partial<InboxItem> = {}): InboxItem {
  const id = `00000000-0000-7000-8000-00000000000${n}`;
  return {
    id,
    kind: "review_requested",
    group: "reviews",
    summary: `Review: Estimate v${n} — [OPPORTUNITY]`,
    opportunity_id: OPP,
    opportunity_title: "[OPPORTUNITY]",
    subject_type: "reviews.review_request",
    subject_id: `10000000-0000-7000-8000-00000000000${n}`,
    subject_version: 1,
    subject_status: "pending",
    subject_status_label: "Pending",
    subject_open: true,
    sender: "[SENDER]",
    href: `/opportunities/${OPP}/estimate?review=10000000-0000-7000-8000-00000000000${n}`,
    read: false,
    created_at: "2026-10-21T10:02:00Z",
    ...overrides,
  };
}

const ITEMS: InboxItem[] = [
  item(1),
  item(2, {
    kind: "run_waiting",
    group: "waiting",
    summary: "Decision needed: Security Agent is not active — [OPPORTUNITY]",
    subject_type: "workflows.decision",
    subject_status: "open",
    subject_status_label: "Waiting",
    sender: null,
    href: `/opportunities/${OPP}/assessments`,
  }),
  item(3, {
    kind: "review_cancelled",
    group: "updates",
    summary: "Review cancelled: Estimate v3 — [OPPORTUNITY]",
    subject_status: "cancelled",
    subject_status_label: "Cancelled",
    subject_open: false,
    href: null,
    read: true,
  }),
];

function page(items: InboxItem[] = ITEMS, overrides: Partial<InboxPage> = {}): InboxPage {
  return {
    items,
    page: 1,
    page_size: 25,
    total: items.length,
    unread: items.filter((i) => !i.read).length,
    ...overrides,
  };
}

/** Shows the shared count, as the sidebar would. */
function Badge() {
  const unread = useInboxUnread();
  return <output data-testid="count">{unread ?? "none"}</output>;
}

function renderView(
  initial: InboxPage | null = page(),
  singleKeyShortcuts = true,
  pageNumber = initial?.page ?? 1,
) {
  const user = userEvent.setup();
  const utils = render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <Badge />
      <InboxView initial={initial} pageNumber={pageNumber} />
    </ShellProviders>,
  );
  return { user, ...utils };
}

const row = (summary: string) =>
  within(screen.getByRole("region", { name: "Inbox items" }))
    .getByText(summary, { exact: false })
    .closest("button") as HTMLButtonElement;
const detail = () => screen.getByRole("region", { name: "Inbox item" });

beforeEach(() => {
  resetInboxUnread();
  for (const fn of Object.values(actions)) fn.mockReset();
  actions.getInbox.mockResolvedValue({ kind: "ok", page: page() });
  actions.getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 2 });
  actions.markInboxItemRead.mockImplementation(async (id: string) => ({
    kind: "ok",
    item: { ...ITEMS.find((i) => i.id === id)!, read: true },
  }));
  actions.markAllInboxRead.mockResolvedValue({ kind: "ok", unread: 0 });
});

describe("InboxView", () => {
  it("shows skeleton rows first, then the grouped list with no violations", async () => {
    const { container } = renderView();
    expect(screen.getByRole("region", { name: "Inbox items (loading)" })).toBeTruthy();
    const list = await screen.findByRole("region", { name: "Inbox items" });
    expect(screen.getByRole("heading", { level: 1, name: "Inbox" })).toBeTruthy();
    expect(screen.getByText("Review requests and notifications.")).toBeTruthy();
    expect(
      within(list)
        .getAllByRole("heading", { level: 2 })
        .map((h) => h.textContent),
    ).toEqual(["Review Requests", "Waiting for your input", "Updates"]);
    expect(within(list).queryByText("Challenges")).toBeNull();
    expect(container.querySelector(".grid")?.className).toContain(
      "grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("renders each row's dot, weight, meta and kind label", async () => {
    renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    const review = row("Review: Estimate v1");
    expect(within(review).getByText("From [SENDER] · 21 Oct 2026, 10:02")).toBeTruthy();
    expect(within(review).getByText("Review").className).toContain("text-primary-text");
    expect(within(review).getByTestId("unread-dot").className).toContain("bg-primary");
    expect(within(review).getByText("Unread:")).toBeTruthy();
    const waiting = row("Decision needed");
    expect(within(waiting).getByText("[OPPORTUNITY] · 21 Oct 2026, 10:02")).toBeTruthy();
    expect(within(waiting).getByText("Update").className).toContain("text-text-secondary");
    expect(within(waiting).getByTestId("unread-dot").className).toContain("bg-border-strong");
    const read = row("Review cancelled");
    expect(within(read).getByTestId("unread-dot").className).toContain("bg-transparent");
    expect(within(read).queryByText("Unread:")).toBeNull();
  });

  it("selecting a row shows its detail, marks it read and drops the shared count", async () => {
    const { user } = renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("2"));
    expect(within(detail()).getByText("Select an item to see it here.")).toBeTruthy();
    actions.getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 1 });

    await user.click(row("Review: Estimate v1"));

    expect(row("Review: Estimate v1").getAttribute("aria-current")).toBe("true");
    expect(row("Review: Estimate v1").className).toContain("bg-primary-tint");
    expect(actions.markInboxItemRead).toHaveBeenCalledWith(ITEMS[0]!.id);
    expect(within(detail()).getByText("Review · From [SENDER] · 21 Oct 2026, 10:02")).toBeTruthy();
    expect(
      within(detail()).getByRole("heading", { name: "Review: Estimate v1 — [OPPORTUNITY]" }),
    ).toBeTruthy();
    expect(within(detail()).getByRole("link", { name: "Open" }).getAttribute("href")).toBe(
      ITEMS[0]!.href,
    );
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("1"));
    expect(within(row("Review: Estimate v1")).getByTestId("unread-dot").className).toContain(
      "bg-transparent",
    );
  });

  it("a closed subject shows its status pill (icon and text) and no Open", async () => {
    const { user, container } = renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    await user.click(row("Review cancelled"));
    const pill = within(detail()).getByTestId("inbox-status");
    expect(pill.textContent).toBe("Cancelled");
    expect(pill.querySelector("svg")).toBeTruthy();
    expect(within(detail()).queryByRole("link", { name: "Open" })).toBeNull();
    expect(actions.markInboxItemRead).not.toHaveBeenCalled(); // already read
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the arrow keys and j/k select the next and previous rows", async () => {
    const { user } = renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    // The list is one Tab stop: the first row.
    const tabStops = screen
      .getAllByRole("button")
      .filter((b) => b.hasAttribute("data-inbox-row") && b.tabIndex === 0);
    expect(tabStops).toEqual([row("Review: Estimate v1")]);
    act(() => row("Review: Estimate v1").focus());
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row("Decision needed"));
    expect(row("Decision needed").getAttribute("aria-current")).toBe("true");
    expect(within(detail()).getByRole("link", { name: "Open" }).getAttribute("href")).toBe(
      `/opportunities/${OPP}/assessments`,
    );
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("Review cancelled"));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row("Decision needed"));
    await user.keyboard("{ArrowUp}");
    expect(row("Review: Estimate v1").getAttribute("aria-current")).toBe("true");
    expect(actions.markInboxItemRead).toHaveBeenCalledTimes(2);
  });

  it("j/k do nothing with single-key shortcuts off; Enter selects", async () => {
    const { user } = renderView(page(), false);
    await screen.findByRole("region", { name: "Inbox items" });
    row("Review: Estimate v1").focus();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row("Review: Estimate v1"));
    expect(actions.markInboxItemRead).not.toHaveBeenCalled();
    await user.keyboard("{Enter}");
    expect(row("Review: Estimate v1").getAttribute("aria-current")).toBe("true");
  });

  it("Mark all read is disabled with nothing unread and marks everything read", async () => {
    const { user } = renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    const button = screen.getByRole("button", { name: "Mark all read" });
    expect(button.hasAttribute("disabled")).toBe(false);
    await user.click(button);
    expect(actions.markAllInboxRead).toHaveBeenCalled();
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("0"));
    expect(screen.getByRole("button", { name: "Mark all read" }).hasAttribute("disabled")).toBe(
      true,
    );
    for (const dot of screen.getAllByTestId("unread-dot")) {
      expect(dot.className).toContain("bg-transparent");
    }
  });

  it("an empty Inbox shows the empty card without an illustration", async () => {
    const { container } = renderView(page([]));
    const empty = await screen.findByTestId("inbox-empty");
    expect(within(empty).getByText("Inbox is empty")).toBeTruthy();
    expect(
      within(empty).getByText(
        "Review requests and notifications for your Opportunities appear here.",
      ),
    ).toBeTruthy();
    expect(empty.querySelector("svg, img")).toBeNull();
    expect(screen.getByRole("button", { name: "Mark all read" }).hasAttribute("disabled")).toBe(
      true,
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows Previous and Next links, never more rows on scroll", async () => {
    const many = Array.from({ length: 25 }, (_, n) =>
      item(1, { id: `00000000-0000-7000-8000-0000000001${String(n).padStart(2, "0")}` }),
    );
    renderView(page(many, { page: 2, total: 60 }));
    const nav = await screen.findByRole("navigation", { name: "Pagination" });
    expect(within(nav).getByText("26–50 of 60")).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "Previous" }).getAttribute("href")).toBe("/inbox");
    expect(within(nav).getByRole("link", { name: "Next" }).getAttribute("href")).toBe(
      "/inbox?page=3",
    );
  });

  it("reads the Inbox again when the window regains focus", async () => {
    renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    actions.getInbox.mockResolvedValue({ kind: "ok", page: page([ITEMS[2]!]) });
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() =>
      expect(screen.queryByText("Decision needed", { exact: false })).toBeNull(),
    );
    expect(actions.getInbox).toHaveBeenCalledWith(1);
  });

  it("drops the shared count as soon as a row is selected", async () => {
    let finish: (value: unknown) => void = () => {};
    actions.markInboxItemRead.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { user } = renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("2"));
    await user.click(row("Review: Estimate v1"));
    expect(screen.getByTestId("count").textContent).toBe("1"); // before the API answers
    await act(async () => finish({ kind: "ok", item: { ...ITEMS[0]!, read: true } }));
  });

  it("restores the row and the count when marking read fails", async () => {
    actions.markInboxItemRead.mockResolvedValue({ kind: "error" });
    actions.getInboxUnreadCount.mockResolvedValue({ kind: "error" });
    // One unread item: Mark all read stays enabled only if the page count is restored.
    const { user } = renderView(page([ITEMS[0]!, { ...ITEMS[1]!, read: true }, ITEMS[2]!]));
    await screen.findByRole("region", { name: "Inbox items" });
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("1"));
    await user.click(row("Review: Estimate v1"));
    await waitFor(() =>
      expect(within(row("Review: Estimate v1")).getByTestId("unread-dot").className).toContain(
        "bg-primary",
      ),
    );
    expect(screen.getByTestId("count").textContent).toBe("1");
    expect(screen.getByRole("button", { name: "Mark all read" }).hasAttribute("disabled")).toBe(
      false,
    );
  });

  it("Mark all read keeps the count the API reports", async () => {
    actions.markAllInboxRead.mockResolvedValue({ kind: "ok", unread: 1 });
    actions.getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 2 });
    const { user } = renderView();
    await screen.findByRole("region", { name: "Inbox items" });
    await user.click(screen.getByRole("button", { name: "Mark all read" }));
    await waitFor(() => expect(screen.getByTestId("count").textContent).toBe("1"));
    expect(screen.getByRole("button", { name: "Mark all read" }).hasAttribute("disabled")).toBe(
      false,
    );
  });

  it("after a failed first load, a refresh reads the page asked for", async () => {
    renderView(null, true, 3);
    await screen.findByText("The platform is not reachable right now. Try again in a moment.");
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await waitFor(() => expect(actions.getInbox).toHaveBeenCalledWith(3));
  });

  it("says when the platform is not reachable", async () => {
    renderView(null);
    expect(
      await screen.findByText("The platform is not reachable right now. Try again in a moment."),
    ).toBeTruthy();
  });
});
