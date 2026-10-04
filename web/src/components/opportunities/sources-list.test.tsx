import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RetryParseResult } from "@/app/opportunities/actions";
import type { SourcesResult } from "@/app/opportunities/data";
import type { ParseErrorCode, Source, SourceParse } from "@/lib/sources";
import { axeViolations } from "@/test/axe";

const retryParse = vi.hoisted(() =>
  vi.fn<(opportunityId: string, sourceId: string) => Promise<RetryParseResult>>(),
);
const loadSources = vi.hoisted(() => vi.fn<(opportunityId: string) => Promise<SourcesResult>>());
vi.mock("@/app/opportunities/actions", () => ({
  addSource: vi.fn(),
  addTextSource: vi.fn(),
  retryParse,
  loadSources,
}));

import { LiveRegionProvider } from "../shell/live-region";
import { SourcesList, SourcesSection } from "./sources-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const UPLOADER = { id: "00000000-0000-7000-8000-0000000000a1", name: "[UPLOADER]" };

function source(n: number, name: string, parse: SourceParse | null): Source {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    kind: "document",
    filename: name,
    version: 1,
    version_count: 1,
    size_bytes: 10,
    uploaded_by: UPLOADER,
    uploaded_at: "2026-10-04T13:05:00Z",
    created_at: "2026-10-04T13:05:00Z",
    parse,
  };
}

const queued: SourceParse = { status: "queued", error_code: null };
const parsing: SourceParse = { status: "parsing", error_code: null };
const parsed: SourceParse = { status: "parsed", error_code: null };
const failed = (code: ParseErrorCode): SourceParse => ({ status: "failed", error_code: code });

function rowFor(name: string) {
  return within(screen.getByRole("table")).getByText(name).closest("tr")!;
}

function renderSection(initial: Source[], canAdd = true) {
  return render(
    <LiveRegionProvider>
      <SourcesSection opportunityId={OPP_ID} canAdd={canAdd} initial={initial} />
    </LiveRegionProvider>,
  );
}

beforeEach(() => {
  retryParse.mockReset();
  loadSources.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("SourcesList status column", () => {
  it("shows Queued, Parsing with a running dot, Parsed and Parse failed with its reason", async () => {
    const { container } = render(
      <SourcesList
        canAdd
        sources={[
          source(1, "a.vtt", queued),
          source(2, "b.eml", parsing),
          source(3, "c.docx", parsed),
          source(4, "d.pdf", failed("no_text")),
        ]}
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Status" })).toBeTruthy();
    expect(within(rowFor("a.vtt")).getByText("Queued")).toBeTruthy();
    expect(within(rowFor("b.eml")).getByText("Parsing")).toBeTruthy();
    expect(within(rowFor("b.eml")).getByTestId("running-dot").className).toContain(
      "motion-reduce:animate-none",
    );
    expect(within(rowFor("c.docx")).getByText("Parsed")).toBeTruthy();
    const failedRow = rowFor("d.pdf");
    expect(within(failedRow).getByText("Parse failed")).toBeTruthy();
    expect(within(failedRow).getByText("No text found — scanned PDF?").className).toContain(
      "text-blocker",
    );
    expect(within(failedRow).getByRole("button", { name: "Retry: d.pdf" })).toBeTruthy();
    expect(within(failedRow).getByRole("button", { name: "Paste text instead: d.pdf" })).toBeTruthy();
    // Only failed rows get the actions.
    expect(screen.getAllByRole("button", { name: /^Retry/ })).toHaveLength(1);
    expect(await axeViolations(container)).toEqual([]);
  });

  it.each([
    ["unreadable", "The file couldn't be read"],
    ["no_text", "No text found — scanned PDF?"],
    ["timeout", "Parsing took too long"],
    ["too_large_output", "Too much text to process"],
    ["not_supported", "Outlook .msg files aren't supported yet — paste the text instead"],
  ] as const)("a %s failure says %s", (code, sentence) => {
    render(<SourcesList sources={[source(1, "x.msg", failed(code))]} />);
    expect(screen.getByText(sentence)).toBeTruthy();
  });

  it("a not_supported row offers Paste text instead but no Retry", () => {
    render(<SourcesList canAdd sources={[source(1, "mail.msg", failed("not_supported"))]} />);
    expect(screen.queryByRole("button", { name: /^Retry/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Paste text instead: mail.msg" })).toBeTruthy();
  });

  it("without can_add_sources a failed row has no Retry or Paste text instead", () => {
    render(<SourcesList sources={[source(1, "d.pdf", failed("unreadable"))]} />);
    expect(screen.getByText("The file couldn't be read")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("a Source with no parse state shows no pill", () => {
    render(<SourcesList sources={[source(1, "old.pdf", null)]} />);
    expect(within(rowFor("old.pdf")).queryByText(/Queued|Parsing|Parsed|Parse failed/)).toBeNull();
  });
});

describe("SourcesSection parsing", () => {
  it("polls every 2 s while a row is Queued or Parsing, then stops", async () => {
    vi.useFakeTimers();
    const first = source(1, "call.vtt", queued);
    loadSources
      .mockResolvedValueOnce({ kind: "ok", sources: [{ ...first, parse: parsing }] })
      .mockResolvedValueOnce({ kind: "ok", sources: [{ ...first, parse: parsed }] });
    renderSection([first]);
    expect(within(rowFor("call.vtt")).getByText("Queued")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadSources).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadSources).toHaveBeenCalledWith(OPP_ID);
    expect(within(rowFor("call.vtt")).getByText("Parsing")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(within(rowFor("call.vtt")).getByText("Parsed")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadSources).toHaveBeenCalledTimes(2);
  });

  it("keeps polling after a failed read", async () => {
    vi.useFakeTimers();
    const first = source(1, "call.vtt", parsing);
    loadSources
      .mockResolvedValueOnce({ kind: "error" })
      .mockResolvedValueOnce({ kind: "ok", sources: [{ ...first, parse: parsed }] });
    renderSection([first], false);
    for (let i = 0; i < 2; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
    }
    expect(loadSources).toHaveBeenCalledTimes(2);
    expect(within(rowFor("call.vtt")).getByText("Parsed")).toBeTruthy();
  });

  it("does not poll when nothing is pending", async () => {
    vi.useFakeTimers();
    renderSection([source(1, "a.pdf", parsed), source(2, "b.pdf", failed("unreadable"))]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadSources).not.toHaveBeenCalled();
  });

  it("Retry requeues a failed row, which then polls to Parsed", async () => {
    const user = userEvent.setup();
    const broken = source(1, "rfp.pdf", failed("timeout"));
    retryParse.mockResolvedValue({ kind: "ok", source: { ...broken, parse: queued } });
    loadSources.mockResolvedValue({ kind: "ok", sources: [{ ...broken, parse: parsed }] });
    renderSection([broken]);

    await user.click(screen.getByRole("button", { name: "Retry: rfp.pdf" }));

    expect(retryParse).toHaveBeenCalledWith(OPP_ID, broken.id);
    expect(within(rowFor("rfp.pdf")).getByText("Queued")).toBeTruthy();
    expect(within(rowFor("rfp.pdf")).queryByRole("button", { name: /Retry/ })).toBeNull();
    await waitFor(() => expect(within(rowFor("rfp.pdf")).getByText("Parsed")).toBeTruthy(), {
      timeout: 4000,
    });
  });

  it("a failed Retry says so on the row and keeps the buttons", async () => {
    const user = userEvent.setup();
    retryParse.mockResolvedValue({ kind: "error" });
    renderSection([source(1, "rfp.pdf", failed("unreadable"))]);

    await user.click(screen.getByRole("button", { name: "Retry: rfp.pdf" }));

    expect(
      await within(rowFor("rfp.pdf")).findByText("The retry failed. Try again."),
    ).toBeTruthy();
    expect(within(rowFor("rfp.pdf")).getByRole("button", { name: "Retry: rfp.pdf" })).toBeTruthy();
  });

  it("a Retry answered 409 re-reads the list", async () => {
    const user = userEvent.setup();
    const broken = source(1, "rfp.pdf", failed("unreadable"));
    retryParse.mockResolvedValue({ kind: "conflict" });
    loadSources.mockResolvedValue({ kind: "ok", sources: [{ ...broken, parse: parsed }] });
    renderSection([broken]);

    await user.click(screen.getByRole("button", { name: "Retry: rfp.pdf" }));

    await waitFor(() => expect(within(rowFor("rfp.pdf")).getByText("Parsed")).toBeTruthy());
  });

  it("Paste text instead opens the paste area and focuses it", async () => {
    const user = userEvent.setup();
    const { container } = renderSection([source(1, "mail.msg", failed("not_supported"))]);
    expect(screen.queryByLabelText("Text to add")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Paste text instead: mail.msg" }));

    const textarea = screen.getByLabelText("Text to add");
    expect(document.activeElement).toBe(textarea);
    // Again while it is open: focus goes back to it.
    await user.click(screen.getByRole("button", { name: "Paste text instead: mail.msg" }));
    expect(document.activeElement).toBe(screen.getByLabelText("Text to add"));
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a poll that started before a Retry can't put the failed row back", async () => {
    vi.useFakeTimers();
    const pendingRow = source(1, "call.vtt", queued);
    const broken = source(2, "rfp.pdf", failed("unreadable"));
    let answerPoll: (result: SourcesResult) => void = () => {};
    loadSources.mockImplementationOnce(
      () => new Promise<SourcesResult>((resolve) => (answerPoll = resolve)),
    );
    loadSources.mockResolvedValue({ kind: "ok", sources: [pendingRow, { ...broken, parse: queued }] });
    retryParse.mockResolvedValue({ kind: "ok", source: { ...broken, parse: queued } });
    renderSection([pendingRow, broken]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll starts and waits
    });
    expect(loadSources).toHaveBeenCalledTimes(1);
    await act(async () => {
      screen.getByRole("button", { name: "Retry: rfp.pdf" }).click();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(rowFor("rfp.pdf")).getByText("Queued")).toBeTruthy();

    await act(async () => {
      answerPoll({ kind: "ok", sources: [pendingRow, broken] }); // read before the Retry
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(within(rowFor("rfp.pdf")).getByText("Queued")).toBeTruthy();
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadSources.mockResolvedValue({ kind: "ok", sources: [source(1, "a.vtt", queued)] });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection([source(1, "a.vtt", queued)], false);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadSources).not.toHaveBeenCalled();

      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(loadSources).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("stops polling after 15 minutes of continuous pending", async () => {
    vi.useFakeTimers();
    loadSources.mockResolvedValue({ kind: "ok", sources: [source(1, "a.vtt", parsing)] });
    renderSection([source(1, "a.vtt", parsing)], false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadSources).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 15 * 60 * 1000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll already scheduled still runs
    });
    const calls = loadSources.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(loadSources).toHaveBeenCalledTimes(calls);
    expect(calls).toBeLessThanOrEqual(2);
  });
});
