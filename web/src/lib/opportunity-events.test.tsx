import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useConflictsEvents, useGapsEvents } from "./opportunity-events";

class FakeSource {
  static instances: FakeSource[] = [];
  readonly listeners = new Map<string, (() => void)[]>();
  closed = false;
  constructor(readonly url: string) {
    FakeSource.instances.push(this);
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.closed = true;
  }
  emit(type: string) {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }
}

const ID = "00000000-0000-7000-8000-000000000001";

function Probe({ onChange, name }: { onChange: () => void; name: string }) {
  const connected = useGapsEvents(ID, onChange);
  return <p data-testid={name}>{connected ? "connected" : "disconnected"}</p>;
}

describe("useGapsEvents (Story 4.7)", () => {
  beforeEach(() => {
    FakeSource.instances = [];
    vi.stubGlobal("EventSource", FakeSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shares one EventSource per Opportunity and closes it with the last subscriber", async () => {
    const first = vi.fn();
    const second = vi.fn();
    const view = render(
      <>
        <Probe name="a" onChange={first} />
        <Probe name="b" onChange={second} />
      </>,
    );
    expect(FakeSource.instances).toHaveLength(1);
    const source = FakeSource.instances[0]!;
    expect(source.url).toBe(`/api/opportunities/${ID}/events`);

    await act(async () => source.emit("open"));
    expect(view.getByTestId("a").textContent).toBe("connected");
    expect(view.getByTestId("b").textContent).toBe("connected");
    expect([first.mock.calls.length, second.mock.calls.length]).toEqual([1, 1]);

    await act(async () => source.emit("gaps.changed"));
    expect([first.mock.calls.length, second.mock.calls.length]).toEqual([2, 2]);

    await act(async () => source.emit("error"));
    expect(view.getByTestId("a").textContent).toBe("disconnected");

    view.rerender(<Probe name="a" onChange={first} />);
    expect(source.closed).toBe(false);
    view.unmount();
    expect(source.closed).toBe(true);
  });

  it("a late subscriber to an open stream catches up at once", async () => {
    const early = vi.fn();
    const late = vi.fn();
    const view = render(<Probe name="a" onChange={early} />);
    await act(async () => FakeSource.instances[0]!.emit("open"));

    view.rerender(
      <>
        <Probe name="a" onChange={early} />
        <Probe name="b" onChange={late} />
      </>,
    );

    expect(FakeSource.instances).toHaveLength(1);
    expect(late).toHaveBeenCalledTimes(1);
    expect(view.getByTestId("b").textContent).toBe("connected");
  });
});

function ConflictsProbe({ onChange }: { onChange: () => void }) {
  useConflictsEvents(ID, onChange);
  return null;
}

describe("useConflictsEvents (Story 6.2)", () => {
  beforeEach(() => {
    FakeSource.instances = [];
    vi.stubGlobal("EventSource", FakeSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shares the EventSource with useGapsEvents and follows only its own frame", async () => {
    const gaps = vi.fn();
    const conflicts = vi.fn();
    const view = render(
      <>
        <Probe name="a" onChange={gaps} />
        <ConflictsProbe onChange={conflicts} />
      </>,
    );
    expect(FakeSource.instances).toHaveLength(1);
    const source = FakeSource.instances[0]!;
    await act(async () => source.emit("open"));
    expect([gaps.mock.calls.length, conflicts.mock.calls.length]).toEqual([1, 1]);

    await act(async () => source.emit("conflicts.changed"));
    expect([gaps.mock.calls.length, conflicts.mock.calls.length]).toEqual([1, 2]);
    await act(async () => source.emit("gaps.changed"));
    expect([gaps.mock.calls.length, conflicts.mock.calls.length]).toEqual([2, 2]);

    view.unmount();
    expect(source.closed).toBe(true);
  });
});
