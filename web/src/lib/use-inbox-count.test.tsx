import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getInboxUnreadCount = vi.hoisted(() => vi.fn());
vi.mock("@/app/inbox/actions", () => ({ getInboxUnreadCount }));

import { INBOX_POLL_MS } from "@/lib/inbox";

import {
  adjustInboxUnread,
  refreshInboxUnread,
  resetInboxUnread,
  setInboxUnread,
  useInboxUnread,
} from "./use-inbox-count";

/** Let the mocked action's promise settle. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  resetInboxUnread();
  getInboxUnreadCount.mockReset();
  getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 4 });
});

afterEach(() => vi.useRealTimers());

describe("useInboxUnread", () => {
  it("reads the count on mount, then every 30 s", async () => {
    const { result } = renderHook(() => useInboxUnread());
    expect(result.current).toBeNull();
    await settle();
    expect(result.current).toBe(4);
    expect(getInboxUnreadCount).toHaveBeenCalledTimes(1);

    getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 5 });
    await act(async () => {
      vi.advanceTimersByTime(INBOX_POLL_MS);
    });
    await settle();
    expect(getInboxUnreadCount).toHaveBeenCalledTimes(2);
    expect(result.current).toBe(5);
  });

  it("reads again on window focus", async () => {
    const { result } = renderHook(() => useInboxUnread());
    await settle();
    getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 1 });
    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await settle();
    expect(result.current).toBe(1);
  });

  it("keeps the last count when a read fails, and shares one store", async () => {
    const first = renderHook(() => useInboxUnread());
    const second = renderHook(() => useInboxUnread());
    await settle();
    getInboxUnreadCount.mockResolvedValue({ kind: "error" });
    await act(async () => {
      await refreshInboxUnread();
    });
    expect(first.result.current).toBe(4);
    act(() => setInboxUnread(0));
    expect([first.result.current, second.result.current]).toEqual([0, 0]);
  });

  it("inside an Opportunity, reads again on a new Review Request frame", async () => {
    const opportunityId = "00000000-0000-7000-8000-000000000001";
    const sources: FakeSource[] = [];
    class FakeSource {
      readonly listeners = new Map<string, (() => void)[]>();
      readyState = 0;
      constructor(readonly url: string) {
        sources.push(this);
      }
      addEventListener(type: string, listener: () => void) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      close() {
        this.readyState = 2;
      }
      emit(type: string) {
        if (type === "open") this.readyState = 1;
        for (const listener of this.listeners.get(type) ?? []) listener();
      }
    }
    vi.stubGlobal("EventSource", FakeSource);
    try {
      const { result, unmount } = renderHook(() => useInboxUnread(opportunityId));
      await settle();
      const source = sources.find((s) => s.url === `/api/opportunities/${opportunityId}/events`)!;
      expect(source).toBeTruthy();
      await act(async () => source.emit("open"));
      await settle();
      const before = getInboxUnreadCount.mock.calls.length;
      getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 5 });

      await act(async () => source.emit("reviews.review_request.created"));
      await settle();

      expect(getInboxUnreadCount.mock.calls.length).toBeGreaterThan(before);
      expect(result.current).toBe(5);
      unmount();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("a refresh asked for during a read runs once more after it", async () => {
    const { result } = renderHook(() => useInboxUnread());
    await settle();
    let answer: (value: unknown) => void = () => {};
    getInboxUnreadCount.mockReturnValueOnce(new Promise((resolve) => (answer = resolve)));
    getInboxUnreadCount.mockResolvedValue({ kind: "ok", unread: 2 });
    const first = refreshInboxUnread(); // started before a mark-read
    const second = refreshInboxUnread(); // asked for after it
    await act(async () => {
      answer({ kind: "ok", unread: 3 }); // the stale count
      await Promise.all([first, second]);
    });
    expect(getInboxUnreadCount).toHaveBeenCalledTimes(3);
    expect(result.current).toBe(2);
    // A refresh after the reads settled starts a new one.
    await act(async () => {
      await refreshInboxUnread();
    });
    expect(getInboxUnreadCount).toHaveBeenCalledTimes(4);
  });

  it("adjusts the count optimistically once it is known", async () => {
    const { result } = renderHook(() => useInboxUnread());
    act(() => adjustInboxUnread(-1)); // unknown yet: nothing
    expect(result.current).toBeNull();
    await settle();
    act(() => adjustInboxUnread(-1));
    expect(result.current).toBe(3);
  });

  it("stops polling once unmounted", async () => {
    const { unmount } = renderHook(() => useInboxUnread());
    await settle();
    unmount();
    await act(async () => {
      vi.advanceTimersByTime(INBOX_POLL_MS * 2);
    });
    expect(getInboxUnreadCount).toHaveBeenCalledTimes(1);
  });
});
