import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StartExtractionResult } from "@/app/opportunities/actions";
import type { RequirementsResult } from "@/app/opportunities/data";
import type {
  Classification,
  Extraction,
  Requirement,
  RequirementList,
} from "@/lib/requirements";
import { axeViolations } from "@/test/axe";

const startExtraction = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartExtractionResult>>(),
);
const loadRequirements = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<RequirementsResult>>(),
);
const getPassage = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({ startExtraction, loadRequirements, getPassage }));

import { ShellProviders } from "../shell/shell-context";
import { ExtractionStatus, RequirementsList, RequirementsSection } from "./requirements-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

function requirement(n: number, classification: Classification, ...labels: string[]): Requirement {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    text: `[REQUIREMENT ${n}]`,
    classification,
    origin: "extracted",
    locked_by_human: false,
    version: 1,
    row_version: 1,
    created_at: "2026-10-04T13:05:00Z",
    evidence: labels.map((label, i) => ({
      passage_id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}${i}aa`,
      source_id: "00000000-0000-7000-8000-0000000000b1",
      source_version: 1,
      filename: label.split(" · ")[1] ?? "",
      label,
    })),
  };
}

const queued: Extraction = { status: "queued", error_code: null, source_count: null };
const running: Extraction = { status: "running", error_code: null, source_count: 2 };
const succeeded: Extraction = { status: "succeeded", error_code: null, source_count: 2 };
const failed: Extraction = { status: "failed", error_code: "model_unavailable", source_count: 2 };

function list(
  items: Requirement[],
  extraction: Extraction | null,
  canStart = true,
): RequirementList {
  return { items, extraction, can_start_extraction: canStart };
}

function renderSection(initial: RequirementList) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <RequirementsSection opportunityId={OPP_ID} initial={initial} />
    </ShellProviders>,
  );
}

beforeEach(() => {
  startExtraction.mockReset();
  loadRequirements.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RequirementsList", () => {
  it("groups by classification in order with label and count, hiding empty groups", async () => {
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <RequirementsList
          items={[
            requirement(1, "commercial", "S2 · mail.eml"),
            requirement(2, "functional", "S1 · call.vtt", "S2 · mail.eml"),
            requirement(3, "non_functional", "S1 · call.vtt"),
            requirement(4, "functional", "S1 · call.vtt"),
          ]}
        />
      </ShellProviders>,
    );
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Functional 2", "Non-functional 1", "Commercial 1"]);
    expect(screen.queryByRole("heading", { name: /Integration|Data|Security/ })).toBeNull();

    const functional = screen.getByRole("region", { name: "Functional 2" });
    const rows = within(functional).getAllByRole("row");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("[REQUIREMENT 2]")).toBeTruthy();
    expect(within(rows[1]).getByText("[REQUIREMENT 4]")).toBeTruthy();
    expect(within(rows[0]).getByText("S1 · call.vtt")).toBeTruthy();
    expect(within(rows[0]).getByText("S2 · mail.eml")).toBeTruthy();
    // Part B: each row and each Evidence chip is a button; the list is one Tab stop.
    expect(within(rows[0]).getByRole("button", { name: "S1 · call.vtt" })).toBeTruthy();
    const tabStops = screen.getAllByRole("button").filter((b) => b.tabIndex === 0);
    expect(tabStops.map((b) => b.textContent)).toEqual(["[REQUIREMENT 2]"]);
    expect(rows.map((row) => row.getAttribute("aria-selected"))).toEqual(["false", "false"]);
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("RequirementsList keys", () => {
  it("j/k are off with single-key shortcuts off; arrows still work", async () => {
    const user = userEvent.setup();
    render(
      <ShellProviders singleKeyShortcuts={false}>
        <RequirementsList items={[requirement(1, "functional"), requirement(2, "data")]} />
      </ShellProviders>,
    );
    const row = (n: number) => screen.getByRole("button", { name: `[REQUIREMENT ${n}]` });
    await user.tab();
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(2));
  });
});

describe("ExtractionStatus", () => {
  it.each([queued, running])("shows Extracting Requirements with a running dot while $status", (e) => {
    render(<ExtractionStatus extraction={e} canStart />);
    expect(screen.getByText("Extracting Requirements")).toBeTruthy();
    expect(screen.getByTestId("running-dot").className).toContain("motion-reduce:animate-none");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the failure reason and Retry for those who may start an extraction", async () => {
    const { container } = render(<ExtractionStatus extraction={failed} canStart />);
    expect(
      screen.getByText("Extraction failed: the model service couldn't be reached").closest("p")!
        .className,
    ).toContain("text-blocker");
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("hides Retry from readers", () => {
    render(
      <ExtractionStatus
        extraction={{ status: "failed", error_code: "input_too_large", source_count: 3 }}
      />,
    );
    expect(
      screen.getByText("Extraction failed: the Sources are too long to process in one go"),
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("hides Retry for too much text and says what to do instead", () => {
    render(
      <ExtractionStatus
        extraction={{ status: "failed", error_code: "input_too_large", source_count: 3 }}
        canStart
      />,
    );
    expect(
      screen.getByText("Too much source text for one extraction — remove or shorten a Source."),
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says to reload instead of the running dot once polling has stopped", () => {
    render(<ExtractionStatus extraction={running} stalled />);
    expect(screen.getByText("Still extracting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
    expect(screen.queryByText("Extracting Requirements")).toBeNull();
  });

  it.each([succeeded, null])("shows nothing when done or never run (%#)", (e) => {
    const { container } = render(<ExtractionStatus extraction={e} canStart />);
    expect(container.textContent).toBe("");
  });
});

describe("RequirementsSection", () => {
  it("shows the empty sentence when nothing has been extracted", () => {
    renderSection(list([], null));
    expect(screen.getByText("Requirements appear here after Sources are parsed.")).toBeTruthy();
  });

  it("polls every 2 s while extracting, then shows the grouped Requirements", async () => {
    vi.useFakeTimers();
    loadRequirements
      .mockResolvedValueOnce({ kind: "ok", list: list([], running) })
      .mockResolvedValueOnce({
        kind: "ok",
        list: list([requirement(1, "security", "S1 · call.vtt")], succeeded),
      });
    renderSection(list([], queued));
    expect(screen.getByText("Extracting Requirements")).toBeTruthy();
    expect(screen.queryByText("Requirements appear here after Sources are parsed.")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadRequirements).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadRequirements).toHaveBeenCalledWith(OPP_ID);
    expect(screen.getByText("Extracting Requirements")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.queryByText("Extracting Requirements")).toBeNull();
    expect(screen.getByRole("heading", { level: 3, name: "Security 1" })).toBeTruthy();
    expect(screen.getByText("S1 · call.vtt")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadRequirements).toHaveBeenCalledTimes(2);
  });

  it("keeps the earlier Requirements while a new extraction runs", () => {
    renderSection(list([requirement(1, "data", "S1 · a.txt")], running));
    expect(screen.getByText("Extracting Requirements")).toBeTruthy();
    expect(screen.getByText("[REQUIREMENT 1]")).toBeTruthy();
  });

  it("does not poll when no extraction is running", async () => {
    vi.useFakeTimers();
    renderSection(list([requirement(1, "data")], succeeded));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadRequirements).not.toHaveBeenCalled();
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([], running) });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(list([], running));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadRequirements).not.toHaveBeenCalled();
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(loadRequirements).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("Retry starts a new extraction, which then polls to done", async () => {
    const user = userEvent.setup();
    startExtraction.mockResolvedValue({ kind: "ok", extraction: queued });
    loadRequirements.mockResolvedValue({
      kind: "ok",
      list: list([requirement(1, "functional", "S1 · call.vtt")], succeeded),
    });
    const { container } = renderSection(list([], failed));
    expect(screen.getByText("Extraction failed: the model service couldn't be reached")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(startExtraction).toHaveBeenCalledWith(OPP_ID);
    expect(screen.getByText("Extracting Requirements")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    await waitFor(() => expect(screen.getByText("[REQUIREMENT 1]")).toBeTruthy(), {
      timeout: 4000,
    });
  });

  it("a Retry answered 409 re-reads the tab", async () => {
    const user = userEvent.setup();
    startExtraction.mockResolvedValue({ kind: "conflict" });
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([], running) });
    renderSection(list([], failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("Extracting Requirements")).toBeTruthy());
  });

  it.each([
    [{ kind: "error" } as const, "The retry failed. Try again."],
    [{ kind: "forbidden" } as const, "Only the owner and collaborators can extract Requirements."],
    [{ kind: "not-found" } as const, "You don't have access to this Opportunity"],
  ])("a failed Retry says so and keeps the button (%#)", async (result, sentence) => {
    const user = userEvent.setup();
    startExtraction.mockResolvedValue(result);
    renderSection(list([], failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("a reader sees the failure without Retry", () => {
    renderSection(list([], failed, false));
    expect(screen.getByText("Extraction failed: the model service couldn't be reached")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("RequirementsSection after review", () => {
  function liveRegion() {
    return screen.getByRole("status");
  }

  it("stops polling after 15 minutes and says to reload", async () => {
    vi.useFakeTimers();
    loadRequirements.mockResolvedValue({ kind: "ok", list: list([], running) });
    renderSection(list([], running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadRequirements).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 15 * 60 * 1000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll already scheduled still runs
    });
    const calls = loadRequirements.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(loadRequirements).toHaveBeenCalledTimes(calls);
    expect(calls).toBeLessThanOrEqual(2);
    expect(screen.getByText("Still extracting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it.each([
    [[requirement(1, "data")], succeeded, "1 Requirement"],
    [[requirement(1, "data"), requirement(2, "security")], succeeded, "2 Requirements"],
    [[], failed, "Extraction failed: the model service couldn't be reached"],
  ])("announces the outcome when a poll finds the run done (%#)", async (items, done, text) => {
    vi.useFakeTimers();
    loadRequirements.mockResolvedValue({ kind: "ok", list: list(items, done) });
    renderSection(list([], running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100); // the region empties, then is written
    });
    expect(liveRegion().textContent).toBe(text);
  });

  it("a finished run with no Requirements says how many Sources it read", () => {
    renderSection(list([], succeeded));
    expect(screen.getByText("No Requirements were found in 2 Sources.")).toBeTruthy();
    expect(screen.queryByText("Requirements appear here after Sources are parsed.")).toBeNull();
  });

  it("uses the singular for one Source", () => {
    renderSection(list([], { status: "succeeded", error_code: null, source_count: 1 }));
    expect(screen.getByText("No Requirements were found in 1 Source.")).toBeTruthy();
  });

  it("takes new data the server passes in", () => {
    const { rerender } = renderSection(list([], failed));
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
    rerender(
      <ShellProviders singleKeyShortcuts>
        <RequirementsSection
          opportunityId={OPP_ID}
          initial={list([requirement(7, "commercial")], succeeded)}
        />
      </ShellProviders>,
    );
    expect(screen.getByText("[REQUIREMENT 7]")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });
});
