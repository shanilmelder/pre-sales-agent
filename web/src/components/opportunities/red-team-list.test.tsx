import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StartRedTeamReviewResult } from "@/app/opportunities/actions";
import type { RedTeamResult } from "@/app/opportunities/data";
import type {
  RedTeamFinding,
  RedTeamReview,
  RedTeamRun,
  RedTeamView,
  Severity,
} from "@/lib/red-team";
import { axeViolations } from "@/test/axe";

const startRedTeamReview = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartRedTeamReviewResult>>(),
);
const loadRedTeam = vi.hoisted(() => vi.fn<(opportunityId: string) => Promise<RedTeamResult>>());
vi.mock("@/app/opportunities/actions", () => ({ startRedTeamReview, loadRedTeam }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => "/opportunities/x/assessments",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { RedTeamHeader, RedTeamList, RedTeamSection } from "./red-team-list";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

function finding(
  n: number,
  severity: Severity,
  opts: { lines?: number; category?: RedTeamFinding["category"] } = {},
): RedTeamFinding {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    position: n,
    category: opts.category ?? "integration_harder",
    severity,
    title: `[FINDING ${n}]`,
    argument: `[ARGUMENT ${n}]`,
    requirements: [
      {
        id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0aa`,
        version: 1,
        label: "R2",
        excerpt: `[EXCERPT ${n}]`,
      },
    ],
    lines: Array.from({ length: opts.lines ?? 0 }, (_, i) => ({
      id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}1${i}0`,
      section: "integration",
      title: `[LINE ${n}.${i + 1}]`,
      effort_hours: 12.5 + i,
    })),
  };
}

function review(n = 2, findings: RedTeamFinding[] = FINDINGS): RedTeamReview {
  return {
    id: `00000000-0000-7000-8000-00000000${String(n).padStart(4, "0")}`,
    version: n,
    status: "current",
    estimate_version_id: "00000000-0000-7000-8000-0000000000d1",
    estimate_version: n,
    dropped_count: 0,
    created_at: "2026-10-05T09:00:00Z",
    counts: { critical: 1, high: 1, medium: 0, low: 1 },
    findings,
  };
}

const FINDINGS = [
  finding(3, "critical", { lines: 2, category: "requirement_incomplete" }),
  finding(1, "high", { lines: 1 }),
  finding(2, "low", { category: "hidden_dependency" }),
];

const queued: RedTeamRun = { status: "queued", error_code: null };
const running: RedTeamRun = { status: "running", error_code: null };
const succeeded: RedTeamRun = { status: "succeeded", error_code: null };
const failed: RedTeamRun = { status: "failed", error_code: "model_unavailable" };

function view(r: RedTeamReview | null, run: RedTeamRun | null, canStart = true): RedTeamView {
  return { review: r, run, can_start: canStart };
}

function renderSection(initial: RedTeamView, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <RedTeamSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) => screen.getByRole("button", { name: new RegExp(`\\[FINDING ${n}\\]`) });
const pane = () => screen.getByRole("complementary", { name: "Details" });

beforeEach(() => {
  startRedTeamReview.mockReset();
  loadRedTeam.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("RedTeamList", () => {
  it("shows dense rows in the given order with severity pill, category, title and chips", async () => {
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <RedTeamList items={FINDINGS} />
      </ShellProviders>,
    );
    const grid = screen.getByRole("grid", { name: "Red Team Findings" });
    const rows = within(grid).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "CriticalRequirement incomplete[FINDING 3]1 Requirement2 Estimate lines",
      "HighIntegration harder[FINDING 1]1 Requirement1 Estimate line",
      "LowHidden dependency[FINDING 2]1 Requirement0 Estimate lines",
    ]);
    const pills = Array.from(grid.querySelectorAll("[data-severity]"));
    expect(pills.map((p) => p.getAttribute("data-severity"))).toEqual(["critical", "high", "low"]);
    // Blocker red only for critical, gap amber only for high; every pill has an icon.
    expect(pills[0].querySelector("svg")?.getAttribute("class")).toContain("text-blocker");
    expect(pills[1].querySelector("svg")?.getAttribute("class")).toContain("text-gap");
    expect(pills[2].querySelector("svg")?.getAttribute("class")).toContain("text-muted-foreground");
    expect(grid.querySelectorAll(".text-blocker")).toHaveLength(1);
    expect(row(3).className).toContain("min-h-row");
    const tabStops = screen.getAllByRole("button").filter((b) => b.tabIndex === 0);
    expect(tabStops).toEqual([row(3)]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("j/k and the arrows move between rows; j/k off with shortcuts off", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <ShellProviders singleKeyShortcuts>
        <RedTeamList items={FINDINGS} />
      </ShellProviders>,
    );
    await user.tab();
    expect(document.activeElement).toBe(row(3));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("j");
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(2));
    await user.keyboard("k");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{ArrowUp}");
    expect(document.activeElement).toBe(row(3));
    unmount();

    render(
      <ShellProviders singleKeyShortcuts={false}>
        <RedTeamList items={FINDINGS} />
      </ShellProviders>,
    );
    await user.tab();
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(3));
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(row(1));
  });
});

describe("the inspector", () => {
  it("Enter opens the Finding in the right pane, read-only, with focus on its title", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(review(), succeeded));

    await user.tab();
    await user.keyboard("{Enter}");

    const inspector = pane();
    const heading = within(inspector).getByRole("heading", { level: 3, name: "[FINDING 3]" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(row(3).closest("[role=row]")?.getAttribute("aria-selected")).toBe("true");
    expect(within(inspector).getByText("Critical")).toBeTruthy();
    expect(within(inspector).getByText("Requirement incomplete")).toBeTruthy();
    expect(within(inspector).getByText("[ARGUMENT 3]")).toBeTruthy();
    expect(within(inspector).getByText("R2")).toBeTruthy();
    expect(within(inspector).getByText("[EXCERPT 3]")).toBeTruthy();
    expect(within(inspector).getByText("[LINE 3.1]")).toBeTruthy();
    expect(within(inspector).getByText("12.5 h")).toBeTruthy();
    expect(within(inspector).getByText("13.5 h")).toBeTruthy();
    const section = within(inspector).getByRole("region", { name: "[FINDING 3]" });
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a click opens the Finding without moving focus into the pane; no lines, no lines block", async () => {
    const user = userEvent.setup();
    renderSection(view(review(), succeeded));

    await user.click(row(2));

    expect(within(pane()).getByRole("heading", { level: 3, name: "[FINDING 2]" })).toBeTruthy();
    expect(within(pane()).queryByText("Challenged Estimate lines")).toBeNull();
    expect(document.activeElement).toBe(row(2));
  });
});

describe("RedTeamHeader", () => {
  it("shows Red Team v2 and the severity counts", () => {
    render(<RedTeamHeader review={review(2)} run={succeeded} canStart />);
    expect(screen.getByText("Red Team v2")).toBeTruthy();
    expect(screen.getByText("1 critical · 1 high · 0 medium · 1 low")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([queued, running])("shows Red Team reviewing with a running dot while $status", (r) => {
    render(<RedTeamHeader review={null} run={r} canStart />);
    expect(screen.getByText("Red Team reviewing")).toBeTruthy();
    expect(screen.getByTestId("running-dot").className).toContain("motion-reduce:animate-none");
  });

  it("shows the failure reason and Retry for those who may start a review", () => {
    render(<RedTeamHeader review={null} run={failed} canStart />);
    expect(
      screen.getByText("Red Team review failed: the model service couldn't be reached"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("hides Retry from those who may not start one", () => {
    render(<RedTeamHeader review={null} run={failed} canStart={false} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says to reload instead of the running dot once polling has stopped", () => {
    render(<RedTeamHeader review={null} run={running} stalled />);
    expect(screen.getByText("Still reviewing — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });
});

describe("RedTeamSection", () => {
  it("shows the empty sentence before any review", async () => {
    const { container } = renderSection(view(null, null));
    expect(screen.getByRole("heading", { level: 3, name: "Red Team" })).toBeTruthy();
    expect(
      screen.getByText("The Red Team reviews the Opportunity after the Estimate is drafted."),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("polls every 2 s while reviewing, then shows the new review", async () => {
    vi.useFakeTimers();
    loadRedTeam
      .mockResolvedValueOnce({ kind: "ok", redTeam: view(null, running) })
      .mockResolvedValue({ kind: "ok", redTeam: view(review(1), succeeded) });
    renderSection(view(null, queued));
    expect(screen.getByText("Red Team reviewing")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadRedTeam).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadRedTeam).toHaveBeenCalledWith(OPP_ID);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("[FINDING 3]")).toBeTruthy();
    expect(screen.getByText("Red Team v1")).toBeTruthy();
    expect(screen.queryByText("Red Team reviewing")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.getByRole("status").textContent).toBe("Red Team v1: 3 Findings");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadRedTeam).toHaveBeenCalledTimes(2);
  });

  it("keeps showing the current review while a re-review runs", () => {
    renderSection(view(review(1), running));
    expect(screen.getByText("Red Team v1")).toBeTruthy();
    expect(screen.getByText("Red Team reviewing")).toBeTruthy();
    expect(screen.getByText("[FINDING 1]")).toBeTruthy();
  });

  it("does not poll when no review is running", async () => {
    vi.useFakeTimers();
    renderSection(view(review(), succeeded));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadRedTeam).not.toHaveBeenCalled();
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadRedTeam.mockResolvedValue({ kind: "ok", redTeam: view(null, running) });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(view(null, running));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadRedTeam).not.toHaveBeenCalled();
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(loadRedTeam).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("stops polling after 15 minutes and says to reload", async () => {
    vi.useFakeTimers();
    loadRedTeam.mockResolvedValue({ kind: "ok", redTeam: view(null, running) });
    renderSection(view(null, running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadRedTeam).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 15 * 60 * 1000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll already scheduled still runs
    });
    const calls = loadRedTeam.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(loadRedTeam).toHaveBeenCalledTimes(calls);
    expect(calls).toBeLessThanOrEqual(2);
    expect(screen.getByText("Still reviewing — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("says to reload when shown again after being hidden past the 15-minute limit", async () => {
    vi.useFakeTimers();
    loadRedTeam.mockResolvedValue({ kind: "ok", redTeam: view(null, running) });
    let hidden = true;
    const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
    try {
      renderSection(view(null, running));
      vi.setSystemTime(Date.now() + 16 * 60 * 1000);
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadRedTeam).not.toHaveBeenCalled();
      expect(screen.getByText("Still reviewing — reload to check.")).toBeTruthy();
    } finally {
      spy.mockRestore();
    }
  });

  it("Retry starts a new review, which then polls to done", async () => {
    const user = userEvent.setup();
    startRedTeamReview.mockResolvedValue({ kind: "ok", run: queued });
    loadRedTeam.mockResolvedValue({ kind: "ok", redTeam: view(review(1), succeeded) });
    const { container } = renderSection(view(null, failed));
    expect(
      screen.getByText("Red Team review failed: the model service couldn't be reached"),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(startRedTeamReview).toHaveBeenCalledWith(OPP_ID);
    expect(screen.getByText("Red Team reviewing")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    await waitFor(() => expect(screen.getByText("[FINDING 3]")).toBeTruthy(), { timeout: 4000 });
  });

  it("a Retry answered 409 re-reads the section", async () => {
    const user = userEvent.setup();
    startRedTeamReview.mockResolvedValue({ kind: "conflict" });
    loadRedTeam.mockResolvedValue({ kind: "ok", redTeam: view(null, running) });
    renderSection(view(null, failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("Red Team reviewing")).toBeTruthy());
  });

  it.each([
    [{ kind: "error" } as const, "The retry failed. Try again."],
    [{ kind: "not-found" } as const, "You don't have access to this Opportunity"],
    [
      { kind: "forbidden" } as const,
      "Only the owner and collaborators, except sales representatives, can start a Red Team review.",
    ],
  ])("a failed Retry says so and keeps the button (%#)", async (result, sentence) => {
    const user = userEvent.setup();
    startRedTeamReview.mockResolvedValue(result);
    renderSection(view(null, failed));

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("a sales representative sees the same Findings, read-only, and no Retry", async () => {
    const user = userEvent.setup();
    renderSection(view(review(), failed, false));
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();

    await user.click(row(1));

    expect(within(pane()).getByText("[ARGUMENT 1]")).toBeTruthy();
    const section = within(pane()).getByRole("region", { name: "[FINDING 1]" });
    expect(within(section).queryByRole("textbox")).toBeNull();
    expect(within(section).queryByRole("button")).toBeNull();
  });

  it("clears the inspector when a newer review replaces the selected Finding", async () => {
    vi.useFakeTimers();
    loadRedTeam.mockResolvedValue({
      kind: "ok",
      redTeam: view(review(3, [finding(9, "medium")]), succeeded),
    });
    renderSection(view(review(2), running));
    act(() => {
      row(1).click();
    });
    expect(within(pane()).getByText("[ARGUMENT 1]")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });

    expect(screen.getByText("Red Team v3")).toBeTruthy();
    expect(within(pane()).queryByText("[ARGUMENT 1]")).toBeNull();
    expect(within(pane()).getByText("Nothing selected.")).toBeTruthy();
  });

  it("says so when a finished run had nothing to review", () => {
    renderSection(view(null, succeeded));
    expect(screen.getByText("There were no active Requirements to review.")).toBeTruthy();
  });
});
