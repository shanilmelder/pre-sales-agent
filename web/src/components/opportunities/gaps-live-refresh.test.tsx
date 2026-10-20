import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import { GapsLiveRefresh } from "./gaps-live-refresh";

class FakeSource {
  static last: FakeSource | null = null;
  readonly listeners = new Map<string, (() => void)[]>();
  constructor(readonly url: string) {
    FakeSource.last = this;
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {}
  emit(type: string) {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }
}

describe("GapsLiveRefresh (Story 4.7)", () => {
  beforeEach(() => {
    refresh.mockReset();
    vi.stubGlobal("EventSource", FakeSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("skips the first callback on connecting, then refreshes on each gaps.changed", async () => {
    render(<GapsLiveRefresh opportunityId="00000000-0000-7000-8000-000000000001" />);
    const source = FakeSource.last!;

    await act(async () => source.emit("open"));
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => source.emit("gaps.changed"));
    await act(async () => source.emit("gaps.changed"));
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
