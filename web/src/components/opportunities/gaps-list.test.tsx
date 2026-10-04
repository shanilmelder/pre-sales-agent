import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StartGapDetectionResult } from "@/app/opportunities/actions";
import type { GapsResult } from "@/app/opportunities/data";
import type { Detection, Gap, GapCategory, GapList, Impact } from "@/lib/gaps";
import { axeViolations } from "@/test/axe";

const startGapDetection = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartGapDetectionResult>>(),
);
const loadGaps = vi.hoisted(() => vi.fn<(opportunityId: string) => Promise<GapsResult>>());
vi.mock("@/app/opportunities/actions", () => ({ startGapDetection, loadGaps }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/gaps",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { DetectionStatus, GapsList, GapsSection } from "./gaps-list";
import { ImpactBar } from "./impact-bar";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

function gap(n: number, impact: Impact, category: GapCategory = "integration_details"): Gap {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    title: `[GAP ${n}]`,
    category,
    trigger: { kind: "agent_category", category },
    why_it_matters: `[WHY ${n}]`,
    impact,
    impact_basis: `[BASIS ${n}]`,
    origin: "detected",
    status: "open",
    row_version: 1,
    created_at: "2026-10-05T09:00:00Z",
    requirements: [
      {
        id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0aa`,
        version: 1,
        label: "R2",
        excerpt: `[EXCERPT ${n}]`,
      },
    ],
    question: {
      id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0bb`,
      text: `[QUESTION ${n}]`,
      topic: `[TOPIC ${n}]`,
      status: "drafted",
      status_changed_at: "2026-10-05T09:00:00Z",
      row_version: 1,
    },
  };
}

const queued: Detection = { status: "queued", error_code: null };
const running: Detection = { status: "running", error_code: null };
const succeeded: Detection = { status: "succeeded", error_code: null };
const failed: Detection = { status: "failed", error_code: "model_unavailable" };

function list(items: Gap[], detection: Detection | null, canStart = true): GapList {
  return { items, detection, can_start_detection: canStart };
}

function renderSection(initial: GapList, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <GapsSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) => screen.getByRole("button", { name: new RegExp(`\\[GAP ${n}\\]`) });
const pane = () => screen.getByRole("complementary", { name: "Details" });

beforeEach(() => {
  startGapDetection.mockReset();
  loadGaps.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ImpactBar", () => {
  it.each([
    ["high", "High", 3],
    ["medium", "Medium", 2],
    ["low", "Low", 1],
  ] as const)("%s fills %s segments of 3, with its label", (impact, label, filled) => {
    render(<ImpactBar impact={impact} />);
    expect(screen.getByText(label)).toBeTruthy();
    const bar = screen.getByTestId("impact-bar");
    expect(bar.getAttribute("aria-hidden")).toBe("true");
    expect(bar.children).toHaveLength(3);
    expect(bar.querySelectorAll("[data-filled]")).toHaveLength(filled);
  });
});

describe("GapsList", () => {
  it("shows each Gap as a row with impact, category, title and the Draft pill", async () => {
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <GapsList
          items={[gap(1, "high"), gap(2, "medium", "data_volumes"), gap(3, "low", "commercial")]}
        />
      </ShellProviders>,
    );
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toBe("HighIntegration details[GAP 1]Draft");
    expect(rows[1].textContent).toBe("MediumData volumes[GAP 2]Draft");
    expect(rows[2].textContent).toBe("LowCommercial[GAP 3]Draft");
    expect(within(rows[0]).getByRole("button").className).toContain("min-h-row");
    const tabStops = screen.getAllByRole("button").filter((b) => b.tabIndex === 0);
    expect(tabStops).toEqual([row(1)]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("j/k and the arrows move between rows; j/k are off with single-key shortcuts off", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ShellProviders singleKeyShortcuts>
        <GapsList items={[gap(1, "high"), gap(2, "low")]} />
      </ShellProviders>,
    );
    await user.tab();
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(2));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(2));
    unmount();

    render(
      <ShellProviders singleKeyShortcuts={false}>
        <GapsList items={[gap(1, "high"), gap(2, "low")]} />
      </ShellProviders>,
    );
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(2));
  });
});

describe("the inspector", () => {
  it("Enter opens the Gap in the right pane, read-only, with focus on its title", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(list([gap(1, "high"), gap(2, "low")], succeeded));

    await user.tab();
    await user.keyboard("j");
    await user.keyboard("{Enter}");

    const inspector = pane();
    const heading = within(inspector).getByRole("heading", { level: 3, name: "[GAP 2]" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(row(2).closest('[role="row"]')?.getAttribute("aria-selected")).toBe("true");
    expect(within(inspector).getByText("Integration details")).toBeTruthy();
    expect(within(inspector).getByText("[WHY 2]")).toBeTruthy();
    expect(within(inspector).getByText("Low")).toBeTruthy();
    expect(within(inspector).getByText("[BASIS 2]")).toBeTruthy();
    expect(within(inspector).getByText("R2")).toBeTruthy();
    expect(within(inspector).getByText("[EXCERPT 2]")).toBeTruthy();
    const question = within(inspector).getByRole("group", {
      name: "Clarification Question (read-only)",
    });
    expect(within(question).getByText("[QUESTION 2]")).toBeTruthy();
    expect(within(question).getByText("[TOPIC 2]")).toBeTruthy();
    expect(within(inspector).getByText("Draft")).toBeTruthy();
    const section = within(inspector).getByRole("region", { name: "[GAP 2]" });
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a click opens the Gap without moving focus into the pane", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], succeeded));

    await user.click(row(1));

    expect(within(pane()).getByRole("heading", { level: 3, name: "[GAP 1]" })).toBeTruthy();
    expect(document.activeElement).toBe(row(1));
  });
});

describe("DetectionStatus", () => {
  it.each([queued, running])("shows Detecting Gaps with a running dot while $status", (d) => {
    render(<DetectionStatus detection={d} canStart />);
    expect(screen.getByText("Detecting Gaps")).toBeTruthy();
    expect(screen.getByTestId("running-dot").className).toContain("motion-reduce:animate-none");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the failure reason and Retry for those who may start a detection", () => {
    render(<DetectionStatus detection={failed} canStart />);
    expect(screen.getByText("Gap detection failed: the model service couldn't be reached")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it.each([
    ["model_timeout", "the model took too long to answer"],
    ["output_invalid", "the model's answer couldn't be used"],
  ] as const)("names the %s reason", (code, reason) => {
    render(<DetectionStatus detection={{ status: "failed", error_code: code }} />);
    expect(screen.getByText(`Gap detection failed: ${reason}`)).toBeTruthy();
  });

  it("hides Retry from those who may not start one (sales representatives, readers)", () => {
    render(<DetectionStatus detection={failed} canStart={false} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says to reload instead of the running dot once polling has stopped", () => {
    render(<DetectionStatus detection={running} stalled />);
    expect(screen.getByText("Still detecting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("shows nothing once succeeded", () => {
    const { container } = render(<DetectionStatus detection={succeeded} canStart />);
    expect(container.textContent).toBe("");
  });
});

describe("GapsSection", () => {
  it("shows the empty sentence before any detection", () => {
    renderSection(list([], null));
    expect(screen.getByText("Gaps appear here after Requirements are extracted.")).toBeTruthy();
  });

  it("says when a finished detection found no Gaps", () => {
    renderSection(list([], succeeded));
    expect(screen.getByText("No Gaps were found in the Requirements.")).toBeTruthy();
  });

  it("polls every 2 s while detecting, then shows the ranked Gaps", async () => {
    vi.useFakeTimers();
    loadGaps
      .mockResolvedValueOnce({ kind: "ok", list: list([], running) })
      .mockResolvedValue({ kind: "ok", list: list([gap(1, "high"), gap(2, "low")], succeeded) });
    renderSection(list([], queued));
    expect(screen.getByText("Detecting Gaps")).toBeTruthy();
    expect(screen.queryByText("Gaps appear here after Requirements are extracted.")).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadGaps).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadGaps).toHaveBeenCalledWith(OPP_ID);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("[GAP 1]")).toBeTruthy();
    expect(screen.queryByText("Detecting Gaps")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadGaps).toHaveBeenCalledTimes(2);
  });

  it("does not poll when no detection is running", async () => {
    vi.useFakeTimers();
    renderSection(list([gap(1, "high")], succeeded));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadGaps).not.toHaveBeenCalled();
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({ kind: "ok", list: list([], running) });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(list([], running));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadGaps).not.toHaveBeenCalled();
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(loadGaps).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("stops polling after 15 minutes and says to reload", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({ kind: "ok", list: list([], running) });
    renderSection(list([], running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadGaps).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 15 * 60 * 1000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll already scheduled still runs
    });
    const calls = loadGaps.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(loadGaps).toHaveBeenCalledTimes(calls);
    expect(calls).toBeLessThanOrEqual(2);
    expect(screen.getByText("Still detecting — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("Retry starts a new detection, which then polls to done", async () => {
    const user = userEvent.setup();
    startGapDetection.mockResolvedValue({ kind: "ok", detection: queued });
    loadGaps.mockResolvedValue({ kind: "ok", list: list([gap(1, "high")], succeeded) });
    const { container } = renderSection(list([], failed));
    expect(screen.getByText("Gap detection failed: the model service couldn't be reached")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(startGapDetection).toHaveBeenCalledWith(OPP_ID);
    expect(screen.getByText("Detecting Gaps")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    await waitFor(() => expect(screen.getByText("[GAP 1]")).toBeTruthy(), { timeout: 4000 });
  });

  it("a Retry answered 409 re-reads the tab", async () => {
    const user = userEvent.setup();
    startGapDetection.mockResolvedValue({ kind: "conflict" });
    loadGaps.mockResolvedValue({ kind: "ok", list: list([], running) });
    renderSection(list([], failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("Detecting Gaps")).toBeTruthy());
  });

  it.each([
    [{ kind: "error" } as const, "The retry failed. Try again."],
    [
      { kind: "forbidden" } as const,
      "Only the owner and collaborators, except sales representatives, can detect Gaps.",
    ],
  ])("a failed Retry says so and keeps the button (%#)", async (result, sentence) => {
    const user = userEvent.setup();
    startGapDetection.mockResolvedValue(result);
    renderSection(list([], failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("a sales representative sees the same Gaps, read-only, and no Retry", async () => {
    const user = userEvent.setup();
    renderSection(list([gap(1, "high")], failed, false));
    expect(screen.getByText("Gap detection failed: the model service couldn't be reached")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    await user.click(row(1));

    expect(within(pane()).getByText("[QUESTION 1]")).toBeTruthy();
    expect(within(pane()).queryByRole("textbox")).toBeNull();
  });

  it("clears the inspector when a poll drops the selected Gap", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({ kind: "ok", list: list([gap(2, "low")], succeeded) });
    renderSection(list([gap(1, "high")], running));
    act(() => {
      row(1).click();
    });
    expect(within(pane()).getByRole("heading", { level: 3, name: "[GAP 1]" })).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByText("[GAP 2]")).toBeTruthy();
    expect(within(pane()).queryByText("[GAP 1]")).toBeNull();
    expect(within(pane()).getByText("Nothing selected.")).toBeTruthy();
  });

  it("announces the Gap count when a detection finishes", async () => {
    vi.useFakeTimers();
    loadGaps.mockResolvedValue({
      kind: "ok",
      list: list([gap(1, "high"), gap(2, "low")], succeeded),
    });
    renderSection(list([], running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.getByRole("status").textContent).toBe("2 Gaps");
  });
});
