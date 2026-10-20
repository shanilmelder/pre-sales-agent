import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  OFFLINE_AFTER_MS,
  useConflictsEvents,
  useEventStreamStatus,
  useGapsEvents,
  useOpportunityEvents,
  useSourceEvents,
} from "./opportunity-events";

type Listener = (event: { type: string; data?: string; lastEventId?: string }) => void;

class FakeSource {
  static instances: FakeSource[] = [];
  readonly listeners = new Map<string, Listener[]>();
  closed = false;
  /** 0 CONNECTING, 1 OPEN, 2 CLOSED, as on EventSource. */
  readyState = 0;
  constructor(readonly url: string) {
    FakeSource.instances.push(this);
  }
  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  emit(type: string, init: { data?: string; lastEventId?: string } = {}) {
    if (type === "open") this.readyState = 1;
    for (const listener of this.listeners.get(type) ?? []) listener({ type, ...init });
  }
  /** The browser gave up (e.g. the route answered 502): CLOSED, then `error`. */
  fail() {
    this.readyState = 2;
    this.emit("error");
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

function Everyone({
  progress,
  gaps,
  sources,
}: {
  progress: (event: unknown) => void;
  gaps: () => void;
  sources: () => void;
}) {
  const a = useOpportunityEvents(ID, progress);
  const b = useGapsEvents(ID, gaps);
  const c = useSourceEvents(ID, sources);
  const status = useEventStreamStatus(ID);
  return (
    <p data-testid="all">
      {[a, b, c].map((on) => (on ? "1" : "0")).join("")} {status}
    </p>
  );
}

describe("the shared reconnecting connection (Story 2.3)", () => {
  beforeEach(() => {
    FakeSource.instances = [];
    vi.stubGlobal("EventSource", FakeSource);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("serves progress, Gaps and Source subscribers from one EventSource, each its own frames", async () => {
    const progress = vi.fn();
    const gaps = vi.fn();
    const sources = vi.fn();
    const view = render(<Everyone progress={progress} gaps={gaps} sources={sources} />);
    expect(FakeSource.instances).toHaveLength(1);
    const source = FakeSource.instances[0]!;
    expect(view.getByTestId("all").textContent).toBe("000 connecting");

    await act(async () => source.emit("open"));
    expect(view.getByTestId("all").textContent).toBe("111 open");
    // Every subscriber re-reads on connecting.
    expect([progress.mock.calls, gaps.mock.calls.length, sources.mock.calls.length]).toEqual([
      [[null]],
      1,
      1,
    ]);

    await act(async () =>
      source.emit("intake.source.parsed", {
        lastEventId: "trace-1",
        data: JSON.stringify({ event_type: "intake.source.parsed" }),
      }),
    );
    expect([progress.mock.calls.length, gaps.mock.calls.length, sources.mock.calls.length]).toEqual(
      [1, 1, 2],
    );

    const run = { event_type: "workflows.run.queued", summary: "run queued" };
    await act(async () =>
      source.emit("workflows.run.queued", { lastEventId: "p-2", data: JSON.stringify(run) }),
    );
    expect(progress).toHaveBeenLastCalledWith(run);
    expect(sources).toHaveBeenCalledTimes(2);

    view.unmount();
    expect(source.closed).toBe(true);
  });

  it("reopens with backoff and the last frame id once the browser gives up, then shows offline at 60 s", async () => {
    const sources = vi.fn();
    function Probe() {
      useSourceEvents(ID, sources);
      return <p data-testid="status">{useEventStreamStatus(ID)}</p>;
    }
    const view = render(<Probe />);
    const first = FakeSource.instances[0]!;
    await act(async () => first.emit("open"));
    await act(async () =>
      first.emit("intake.source.added", { lastEventId: "0199-a", data: "{}" }),
    );

    await act(async () => first.fail());
    expect(view.getByTestId("status").textContent).toBe("reconnecting");
    expect(FakeSource.instances).toHaveLength(1);

    await act(async () => vi.advanceTimersByTime(1000));
    expect(FakeSource.instances).toHaveLength(2);
    const second = FakeSource.instances[1]!;
    expect(second.url).toBe(`/api/opportunities/${ID}/events?last_event_id=0199-a`);

    // Refused again: 2 s, then 5 s, then 10 s between tries, capped.
    await act(async () => second.fail());
    await act(async () => vi.advanceTimersByTime(1999));
    expect(FakeSource.instances).toHaveLength(2);
    await act(async () => vi.advanceTimersByTime(1));
    expect(FakeSource.instances).toHaveLength(3);
    await act(async () => FakeSource.instances[2]!.fail());
    await act(async () => vi.advanceTimersByTime(5000));
    expect(FakeSource.instances).toHaveLength(4);
    await act(async () => FakeSource.instances[3]!.fail());
    await act(async () => vi.advanceTimersByTime(10000));
    expect(FakeSource.instances).toHaveLength(5);
    await act(async () => FakeSource.instances[4]!.fail());
    await act(async () => vi.advanceTimersByTime(10000));
    expect(FakeSource.instances).toHaveLength(6);

    await act(async () => vi.advanceTimersByTime(OFFLINE_AFTER_MS));
    expect(view.getByTestId("status").textContent).toBe("offline");

    const callsBefore = sources.mock.calls.length;
    const latest = FakeSource.instances.at(-1)!;
    await act(async () => latest.emit("open"));
    expect(view.getByTestId("status").textContent).toBe("open");
    expect(sources.mock.calls.length).toBe(callsBefore + 1); // re-reads on reconnect
  });

  it("leaves a browser-side retry (CONNECTING) to the browser", async () => {
    function Probe() {
      return <p data-testid="status">{useEventStreamStatus(ID)}</p>;
    }
    const view = render(<Probe />);
    const source = FakeSource.instances[0]!;
    await act(async () => source.emit("open"));

    source.readyState = 0;
    await act(async () => source.emit("error"));
    await act(async () => vi.advanceTimersByTime(15000));

    expect(FakeSource.instances).toHaveLength(1);
    expect(view.getByTestId("status").textContent).toBe("reconnecting");
    await act(async () => source.emit("open"));
    expect(view.getByTestId("status").textContent).toBe("open");
    // The offline timer was cleared: still open well after 60 s.
    await act(async () => vi.advanceTimersByTime(OFFLINE_AFTER_MS * 2));
    expect(view.getByTestId("status").textContent).toBe("open");
  });
});
