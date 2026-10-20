import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SourceTextResult } from "@/app/opportunities/actions";
import type { SourcesResult } from "@/app/opportunities/data";
import type { Me } from "@/lib/api/server";
import type { Source, SourceParse } from "@/lib/sources";
import { axeViolations } from "@/test/axe";

const loadSourceText = vi.hoisted(() =>
  vi.fn<(o: string, s: string, v: number) => Promise<SourceTextResult>>(),
);
const loadSources = vi.hoisted(() => vi.fn<(o: string) => Promise<SourcesResult>>());
vi.mock("@/app/opportunities/actions", () => ({
  addSource: vi.fn(),
  addTextSource: vi.fn(),
  retryParse: vi.fn(),
  loadSources,
  loadSourceText,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/sources",
  useSelectedLayoutSegment: () => "sources",
}));

import { AppShell } from "../shell/app-shell";
import { ShellProviders } from "../shell/shell-context";
import { SourceInspector } from "./source-inspector";
import { SourcesSection } from "./sources-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const ME: Me = {
  id: "00000000-0000-7000-8000-000000000000",
  name: "[USER]",
  email: "user@example.invalid",
  roles: ["sales_representative"],
  permissions: [],
};

function source(n: number, name: string, parse: SourceParse | null, extra: Partial<Source> = {}): Source {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    kind: "email",
    filename: name,
    version: 2,
    version_count: 3,
    size_bytes: 2048,
    uploaded_by: { id: "00000000-0000-7000-8000-0000000000a1", name: "[UPLOADER]" },
    uploaded_at: "2026-10-04T13:05:00Z",
    created_at: "2026-10-04T13:05:00Z",
    parse,
    ...extra,
  };
}

const parsed: SourceParse = { status: "parsed", error_code: null };
const PARSED = source(1, "kickoff.eml", parsed);

function renderInspector(s: Source) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <SourceInspector opportunityId={OPP_ID} source={s} />
    </ShellProviders>,
  );
}

beforeEach(() => {
  loadSourceText.mockReset();
  loadSources.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourceInspector (Story 2.3)", () => {
  it("shows the metadata and loads the full text of a parsed version by itself", async () => {
    loadSourceText.mockResolvedValue({
      kind: "ok",
      version: 2,
      text: "Line one\n\nNeeds SSO",
      charCount: 19,
    });
    const { container } = renderInspector(PARSED);

    expect(screen.getByRole("heading", { name: "kickoff.eml" })).toBeTruthy();
    const facts = container.querySelector("dl")! as HTMLElement;
    expect(within(facts).getByText("Email")).toBeTruthy();
    expect(within(facts).getByText("v2 of 3")).toBeTruthy();
    expect(within(facts).getByText("2.0 KB")).toBeTruthy();
    expect(within(facts).getByText("[UPLOADER]")).toBeTruthy();
    expect(within(facts).getByText("4 Oct 2026, 13:05 UTC")).toBeTruthy();
    expect(screen.getByText("Parsed")).toBeTruthy();

    const text = await screen.findByLabelText("Extracted text of kickoff.eml");
    expect(text.tagName).toBe("PRE");
    expect(text.textContent).toBe("Line one\n\nNeeds SSO");
    expect(loadSourceText).toHaveBeenCalledWith(OPP_ID, PARSED.id, 2);

    const download = screen.getByRole("link", { name: "Download original: kickoff.eml" });
    expect(download.getAttribute("href")).toBe(
      `/api/opportunities/${OPP_ID}/sources/${PARSED.id}/versions/2/download`,
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says the text comes once parsing finishes, without loading it", () => {
    renderInspector(source(2, "notes.txt", { status: "parsing", error_code: null }));
    expect(screen.getByText("Available once parsing finishes")).toBeTruthy();
    expect(loadSourceText).not.toHaveBeenCalled();
  });

  it("a failed parse shows its reason and that no text was extracted", async () => {
    const { container } = renderInspector(
      source(3, "scan.pdf", { status: "failed", error_code: "no_text" }),
    );
    expect(screen.getByText("Parse failed")).toBeTruthy();
    expect(screen.getByText("No text found — scanned PDF?")).toBeTruthy();
    expect(screen.getByText("No text was extracted from this version.")).toBeTruthy();
    expect(loadSourceText).not.toHaveBeenCalled();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says so when the text can't be loaded", async () => {
    loadSourceText.mockResolvedValue({ kind: "error" });
    renderInspector(PARSED);
    expect(await screen.findByText("The text could not be loaded.")).toBeTruthy();
  });

  it("loads the text when a shown version becomes parsed", async () => {
    loadSourceText.mockResolvedValue({ kind: "ok", version: 2, text: "Now parsed", charCount: 10 });
    const pending = source(4, "a.txt", { status: "parsing", error_code: null });
    const view = renderInspector(pending);
    expect(loadSourceText).not.toHaveBeenCalled();
    view.rerender(
      <ShellProviders singleKeyShortcuts>
        <SourceInspector opportunityId={OPP_ID} source={{ ...pending, parse: parsed }} />
      </ShellProviders>,
    );
    expect((await screen.findByLabelText("Extracted text of a.txt")).textContent).toBe("Now parsed");
  });
});

describe("opening a Source from the Sources tab (Story 2.3)", () => {
  function renderTab(initial: Source[]) {
    return render(
      <ShellProviders singleKeyShortcuts>
        <AppShell me={ME}>
          <SourcesSection opportunityId={OPP_ID} canAdd={false} initial={initial} />
        </AppShell>
      </ShellProviders>,
    );
  }

  it("a click on a row opens it in the right pane's inspector", async () => {
    loadSourceText.mockResolvedValue({ kind: "ok", version: 2, text: "Body", charCount: 4 });
    const user = userEvent.setup();
    renderTab([PARSED, source(5, "other.txt", parsed)]);

    await user.click(screen.getByRole("button", { name: "kickoff.eml" }));

    const heading = await screen.findByRole("heading", { name: "kickoff.eml", level: 3 });
    expect(heading.closest("section")).toBeTruthy();
    expect(screen.getByRole("button", { name: "kickoff.eml" }).getAttribute("aria-current")).toBe(
      "true",
    );
    expect(await screen.findByText("Body")).toBeTruthy();
  });

  it("Enter on a row opens it and moves focus to the inspector", async () => {
    loadSourceText.mockResolvedValue({ kind: "ok", version: 2, text: "Body", charCount: 4 });
    const user = userEvent.setup();
    renderTab([PARSED]);

    screen.getByRole("button", { name: "kickoff.eml" }).focus();
    await user.keyboard("{Enter}");

    const heading = await screen.findByRole("heading", { name: "kickoff.eml", level: 3 });
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });
});

describe("live pills from the event stream (Story 2.3)", () => {
  class FakeSource {
    static last: FakeSource | null = null;
    readonly listeners = new Map<string, ((event?: unknown) => void)[]>();
    readyState = 0;
    constructor(readonly url: string) {
      FakeSource.last = this;
    }
    addEventListener(type: string, listener: (event?: unknown) => void) {
      this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
    }
    close() {
      this.readyState = 2;
    }
    emit(type: string, event: object = {}) {
      if (type === "open") this.readyState = 1;
      for (const listener of this.listeners.get(type) ?? []) listener({ type, ...event });
    }
  }

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.stubGlobal("EventSource", FakeSource);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("re-reads on source frames and doesn't poll while connected; polls again after a drop", async () => {
    const queued = source(6, "a.txt", { status: "queued", error_code: null });
    loadSources.mockResolvedValue({ kind: "ok", sources: [queued] });
    render(
      <ShellProviders singleKeyShortcuts>
        <SourcesSection opportunityId={OPP_ID} canAdd={false} initial={[queued]} />
      </ShellProviders>,
    );
    const stream = FakeSource.last!;
    await act(async () => stream.emit("open")); // a connect re-reads once
    expect(loadSources).toHaveBeenCalledTimes(1);

    // Connected: no 2 s poll however long the row stays Queued.
    await act(async () => vi.advanceTimersByTime(10_000));
    expect(loadSources).toHaveBeenCalledTimes(1);

    loadSources.mockResolvedValue({ kind: "ok", sources: [{ ...queued, parse: parsed }] });
    await act(async () =>
      stream.emit("intake.source.parsed", { lastEventId: "t-1", data: "{}" }),
    );
    expect(loadSources).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(screen.getByText("Parsed")).toBeTruthy());

    // Another frame type isn't the Sources tab's.
    await act(async () => stream.emit("workflows.run.queued", { data: "{}" }));
    expect(loadSources).toHaveBeenCalledTimes(2);
  });

  it("applies only the latest-started re-read when responses arrive out of order", async () => {
    const queued = source(8, "c.txt", { status: "queued", error_code: null });
    loadSources.mockResolvedValue({ kind: "ok", sources: [queued] });
    render(
      <ShellProviders singleKeyShortcuts>
        <SourcesSection opportunityId={OPP_ID} canAdd={false} initial={[queued]} />
      </ShellProviders>,
    );
    const stream = FakeSource.last!;
    await act(async () => stream.emit("open"));

    let older!: (r: SourcesResult) => void;
    let newer!: (r: SourcesResult) => void;
    loadSources
      .mockImplementationOnce(() => new Promise((resolve) => (older = resolve)))
      .mockImplementationOnce(() => new Promise((resolve) => (newer = resolve)));
    await act(async () => stream.emit("intake.source.parse_started", { data: "{}" }));
    await act(async () => stream.emit("intake.source.parsed", { data: "{}" }));

    await act(async () => newer({ kind: "ok", sources: [{ ...queued, parse: parsed }] }));
    expect(screen.getByText("Parsed")).toBeTruthy();
    // The older read (still Parsing) lands last: it is ignored.
    await act(async () =>
      older({ kind: "ok", sources: [{ ...queued, parse: { status: "parsing", error_code: null } }] }),
    );
    expect(screen.getByText("Parsed")).toBeTruthy();
    expect(screen.queryByText("Parsing")).toBeNull();
  });

  it("falls back to the 2 s poll while the stream is down", async () => {
    const queued = source(7, "b.txt", { status: "queued", error_code: null });
    loadSources.mockResolvedValue({ kind: "ok", sources: [queued] });
    render(
      <ShellProviders singleKeyShortcuts>
        <SourcesSection opportunityId={OPP_ID} canAdd={false} initial={[queued]} />
      </ShellProviders>,
    );
    const stream = FakeSource.last!;
    await act(async () => stream.emit("open"));
    const afterOpen = loadSources.mock.calls.length;

    await act(async () => stream.emit("error"));
    await act(async () => vi.advanceTimersByTime(2_100));
    expect(loadSources.mock.calls.length).toBeGreaterThan(afterOpen);
  });
});
