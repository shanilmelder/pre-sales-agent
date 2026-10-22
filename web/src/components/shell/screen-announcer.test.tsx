import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const pathname = vi.hoisted(() => ({ current: "/inbox" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

import { ANNOUNCE_CLEAR_MS, LiveRegionProvider } from "./live-region";
import { ScreenAnnouncer, TITLE_SETTLE_MS, screenName } from "./screen-announcer";

function tree() {
  return (
    <LiveRegionProvider>
      <ScreenAnnouncer />
    </LiveRegionProvider>
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  pathname.current = "/inbox";
});
afterEach(() => {
  vi.useRealTimers();
  document.title = "";
});

describe("screenName", () => {
  it("drops the product suffix", () => {
    expect(screenName("Knowledge · Pre Sales Agent Framework")).toBe("Knowledge");
    expect(screenName("Users & roles · Pre Sales Agent Framework")).toBe("Users & roles");
  });
  it("returns nothing for no title or the bare product name", () => {
    expect(screenName("")).toBe("");
    expect(screenName("Pre Sales Agent Framework")).toBe("");
  });
});

describe("ScreenAnnouncer", () => {
  it("announces the screen name once on load", () => {
    document.title = "Inbox · Pre Sales Agent Framework";
    render(tree());
    act(() => vi.advanceTimersByTime(TITLE_SETTLE_MS + ANNOUNCE_CLEAR_MS));
    expect(screen.getByRole("status").textContent).toBe("Inbox");
  });

  it("announces the new screen after navigation", () => {
    document.title = "Inbox · Pre Sales Agent Framework";
    const { rerender } = render(tree());
    act(() => vi.advanceTimersByTime(TITLE_SETTLE_MS + ANNOUNCE_CLEAR_MS));
    document.title = "Knowledge · Pre Sales Agent Framework";
    pathname.current = "/knowledge";
    rerender(tree());
    // Announcements are throttled to one per interval, so the second waits for it.
    act(() => vi.advanceTimersByTime(10_000));
    expect(screen.getByRole("status").textContent).toBe("Knowledge");
  });

  it("announces nothing without a title", () => {
    render(tree());
    act(() => vi.advanceTimersByTime(TITLE_SETTLE_MS + ANNOUNCE_CLEAR_MS));
    expect(screen.getByRole("status").textContent).toBe("");
  });
});
