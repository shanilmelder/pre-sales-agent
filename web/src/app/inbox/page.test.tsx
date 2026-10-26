import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MeResult } from "@/lib/api/server";
import { permissionsFor } from "@/test/permissions";

const getMe = vi.hoisted(() => vi.fn<() => Promise<MeResult>>());
vi.mock("@/lib/api/server", () => ({ getMe, createServerApiClient: vi.fn() }));
const getInbox = vi.hoisted(() => vi.fn());
vi.mock("@/app/inbox/actions", () => ({
  getInbox,
  getInboxUnreadCount: async () => ({ kind: "ok", unread: 0 }),
  markInboxItemRead: vi.fn(),
  markAllInboxRead: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => ({
  loadReviewPanel: async () => ({ kind: "not-found" }),
  decideReviewRequest: vi.fn(),
}));
const redirect = vi.hoisted(() =>
  vi.fn((href: string) => {
    throw new Error(`NEXT_REDIRECT ${href}`);
  }),
);
vi.mock("next/navigation", () => ({
  redirect,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/inbox",
}));

import { InboxView } from "@/components/inbox/inbox-view";

import InboxPage from "./page";

function emptyPage(page: number, total: number) {
  return { kind: "ok", page: { items: [], page, page_size: 25, total, unread: 0 } };
}

beforeEach(() => {
  getMe.mockResolvedValue({
    kind: "ok",
    me: {
      id: "00000000-0000-7000-8000-000000000000",
      name: "[USER]",
      email: "user@example.invalid",
      roles: ["pm_reviewer"],
      permissions: permissionsFor(["pm_reviewer"]),
    },
  });
  getInbox.mockReset();
  redirect.mockClear();
});

describe("/inbox page", () => {
  it("reads the page in `?page=`", async () => {
    getInbox.mockResolvedValue({
      kind: "ok",
      page: { items: [{ id: "x" }], page: 3, page_size: 25, total: 60, unread: 0 },
    });
    const element = await InboxPage({ searchParams: Promise.resolve({ page: "3" }) });
    expect(getInbox).toHaveBeenCalledWith(3);
    // AppShell > InboxView, keyed and told which page to refresh.
    const view = (element as ReactElement<{ children: ReactElement }>).props.children;
    expect(view.type).toBe(InboxView);
    expect(view.key).toBe("3");
    expect((view.props as { pageNumber: number; initial: unknown }).pageNumber).toBe(3);
    expect(redirect).not.toHaveBeenCalled();
  });

  it("past the last page, goes to the last one", async () => {
    getInbox.mockResolvedValue(emptyPage(4, 60));
    await expect(InboxPage({ searchParams: Promise.resolve({ page: "4" }) })).rejects.toThrow(
      "NEXT_REDIRECT /inbox?page=3",
    );
    expect(getInbox).toHaveBeenCalledWith(4);
  });

  it("past the end of an empty Inbox, goes to the Inbox itself", async () => {
    getInbox.mockResolvedValue(emptyPage(2, 0));
    await expect(InboxPage({ searchParams: Promise.resolve({ page: "2" }) })).rejects.toThrow(
      "NEXT_REDIRECT /inbox",
    );
  });
});
