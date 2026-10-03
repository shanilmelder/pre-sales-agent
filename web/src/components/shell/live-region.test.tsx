import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ANNOUNCE_CLEAR_MS,
  ANNOUNCE_INTERVAL_MS,
  LiveRegionProvider,
  createThrottledAnnouncer,
  useAnnounce,
} from "./live-region";

describe("createThrottledAnnouncer", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("sends at most one message per interval, keeping the latest", () => {
    const emit = vi.fn();
    const { announce } = createThrottledAnnouncer(emit);
    announce("one");
    announce("two");
    announce("three");
    expect(emit.mock.calls).toEqual([["one"]]);
    vi.advanceTimersByTime(ANNOUNCE_INTERVAL_MS - 1);
    expect(emit).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(emit.mock.calls).toEqual([["one"], ["three"]]);
    // The next one waits a full interval after "three".
    announce("four");
    expect(emit).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(ANNOUNCE_INTERVAL_MS);
    expect(emit.mock.calls.at(-1)).toEqual(["four"]);
  });

  it("sends immediately once the interval has passed", () => {
    const emit = vi.fn();
    const { announce } = createThrottledAnnouncer(emit);
    announce("one");
    vi.advanceTimersByTime(ANNOUNCE_INTERVAL_MS);
    announce("two");
    expect(emit.mock.calls).toEqual([["one"], ["two"]]);
  });
});

describe("LiveRegionProvider", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("mounts one polite live region that shows announcements", () => {
    let announce: (message: string) => void = () => {};
    function Probe() {
      announce = useAnnounce();
      return null;
    }
    render(
      <LiveRegionProvider>
        <Probe />
      </LiveRegionProvider>,
    );
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    act(() => announce("Right pane opened"));
    expect(region.textContent).toBe("");
    act(() => vi.advanceTimersByTime(ANNOUNCE_CLEAR_MS));
    expect(region.textContent).toBe("Right pane opened");
  });

  it("clears the region first, so a repeated message changes the DOM again", () => {
    let announce: (message: string) => void = () => {};
    function Probe() {
      announce = useAnnounce();
      return null;
    }
    render(
      <LiveRegionProvider>
        <Probe />
      </LiveRegionProvider>,
    );
    const region = screen.getByRole("status");
    act(() => announce("Saved"));
    act(() => vi.advanceTimersByTime(ANNOUNCE_CLEAR_MS));
    expect(region.textContent).toBe("Saved");
    act(() => vi.advanceTimersByTime(ANNOUNCE_INTERVAL_MS));
    act(() => announce("Saved"));
    expect(region.textContent).toBe("");
    act(() => vi.advanceTimersByTime(ANNOUNCE_CLEAR_MS));
    expect(region.textContent).toBe("Saved");
  });
});
