import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { StartRedTeamReviewResult } from "@/app/opportunities/actions";
import type { RedTeamResult } from "@/app/opportunities/data";
import type { AssessmentsView } from "@/lib/assessments";
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
const loadAssessments = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({
  startRedTeamReview,
  loadRedTeam,
  loadAssessments,
  startAssessmentRun: vi.fn(),
  retryAssessmentTask: vi.fn(),
  cancelAssessmentRun: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => "/opportunities/x/assessments",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { SpecialistAssessmentsSection } from "./specialist-assessments";

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

/** No Assessment run and no Assessments: the tab shows only the Red Team. */
const NO_ASSESSMENTS: AssessmentsView = {
  run: null,
  assessments: [
    { agent: "engineering_agent", assessment: null },
    { agent: "pm_agent", assessment: null },
    { agent: "security_agent", assessment: null },
  ],
  can_start: false,
};

/** The Assessments tab body with the given Red Team view (the `useRedTeam` hook's behaviour
 * is tested through it). */
function renderSection(initial: RedTeamView | null, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <SpecialistAssessmentsSection
        opportunityId={OPP_ID}
        initial={NO_ASSESSMENTS}
        redTeam={initial}
      />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) => screen.getByRole("button", { name: new RegExp(`\\[FINDING ${n}\\]`) });
const pane = () => screen.getByRole("complementary", { name: "Details" });
/** The Red Team's task card. */
const redCard = () =>
  within(screen.getByRole("list", { name: "Agent progress" }))
    .getByText("Red Team")
    .closest("li") as HTMLElement;
const redStatus = () => redCard().querySelector("[data-task-pill]")?.textContent;
const retryButton = () => screen.queryByRole("button", { name: "Retry Red Team" });
const resultCard = () => screen.getByRole("article", { name: "Red Team" });

beforeEach(() => {
  startRedTeamReview.mockReset();
  loadRedTeam.mockReset();
  loadAssessments.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the Red Team Findings in the Findings table", () => {
  it("shows dense rows ranked by severity with pill, category, title, Raised by and chips", async () => {
    const { container } = renderSection(view(review(), succeeded));
    const grid = screen.getByRole("grid", { name: "Findings" });
    const rows = within(grid).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "CriticalRequirement incomplete[FINDING 3]Red Team1 Requirement2 Estimate lines",
      "HighIntegration harder[FINDING 1]Red Team1 Requirement1 Estimate line",
      "LowHidden dependency[FINDING 2]Red Team1 Requirement0 Estimate lines",
    ]);
    const pills = Array.from(grid.querySelectorAll("[data-severity]"));
    expect(pills.map((p) => p.getAttribute("data-severity"))).toEqual(["critical", "high", "low"]);
    // Blocker red only for critical, gap amber only for high; every pill has an icon.
    expect(pills.map((p) => p.getAttribute("data-tone"))).toEqual(["blocker", "gap", "neutral"]);
    for (const pill of pills) {
      expect(pill.getAttribute("data-slot")).toBe("pill");
      expect(pill.querySelector("svg")).toBeTruthy();
    }
    // Critical rows are tinted red.
    expect(rows[0].className).toContain("bg-blocker-tint");
    expect(rows[1].className).not.toContain("bg-blocker-tint");
    expect(row(3).className).toContain("min-h-row");
    const tabStops = within(grid)
      .getAllByRole("button")
      .filter((b) => b.tabIndex === 0);
    expect(tabStops).toEqual([row(3)]);
    const heading = screen.getByRole("heading", { level: 3, name: "Findings" });
    expect(
      within(heading.parentElement as HTMLElement).getByText(
        "1 Critical · 1 High · 0 Medium · 1 Low",
      ),
    ).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("j/k and the arrows move between rows; j/k off with shortcuts off", async () => {
    const user = userEvent.setup();
    const { unmount } = renderSection(view(review(), succeeded));
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

    renderSection(view(review(), succeeded), false);
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

describe("the Red Team task and result cards", () => {
  it("shows the review's result card with its version, severity counts and evidence", () => {
    renderSection(view(review(2), succeeded));
    const card = resultCard();
    expect(within(card).getByText("v2")).toBeTruthy();
    expect(within(card).getByText("1 Critical · 1 High · 0 Medium · 1 Low")).toBeTruthy();
    expect(within(card).getByText("3 Findings against Estimate v2")).toBeTruthy();
    expect(within(card).getByText("R2")).toBeTruthy();
    expect(within(card).queryByRole("button")).toBeNull(); // no Show effort
    expect(redStatus()).toBe("Done");
    expect(
      within(redCard()).getByText("Argues integrations are harder and Requirements incomplete"),
    ).toBeTruthy();
    // No elapsed time: the Red Team run has no timestamps.
    expect(within(redCard()).queryByTestId("elapsed")).toBeNull();
    expect(retryButton()).toBeNull();
  });

  it("a queued review waits for the worker; a running one has a static running dot", () => {
    const { unmount } = renderSection(view(null, queued));
    expect(redStatus()).toBe("Queued");
    expect(within(redCard()).getByText("Waiting for the worker")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
    unmount();

    renderSection(view(null, running));
    expect(redStatus()).toBe("Running");
    const runningDot = screen.getByTestId("running-dot");
    expect(runningDot.tagName.toLowerCase()).toBe("svg");
    expect(runningDot.getAttribute("class") ?? "").toContain("lucide-loader-circle");
    expect(runningDot.getAttribute("class") ?? "").toContain("text-agent");
    expect(runningDot.getAttribute("class") ?? "").not.toContain("animate");
    expect(
      redCard().querySelector("[data-testid='state-bar']")?.getAttribute("data-state"),
    ).toBe("running");
  });

  it("shows the failure reason and Retry for those who may start a review", () => {
    renderSection(view(null, failed));
    expect(redStatus()).toBe("Failed");
    expect(within(redCard()).getByText("the model service couldn't be reached")).toBeTruthy();
    expect(retryButton()).toBeTruthy();
    expect(redCard().querySelector("[data-slot='card']")?.className).toContain("border-blocker");
  });

  it("hides Retry from those who may not start one", () => {
    renderSection(view(null, failed, false));
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("useRedTeam through the Assessments tab", () => {
  it("shows the empty sentence before any review", async () => {
    const { container } = renderSection(view(null, null));
    expect(
      screen.getByText("The Red Team reviews the Opportunity after the Estimate is drafted."),
    ).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Agent progress" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("says so when the Red Team could not be loaded", () => {
    renderSection(null);
    expect(
      screen.getByText("The Red Team Review could not be loaded. Try again in a moment."),
    ).toBeTruthy();
  });

  it("polls every 2 s while reviewing, then shows the new review", async () => {
    vi.useFakeTimers();
    loadRedTeam
      .mockResolvedValueOnce({ kind: "ok", redTeam: view(null, running) })
      .mockResolvedValue({ kind: "ok", redTeam: view(review(1), succeeded) });
    renderSection(view(null, queued));
    expect(redStatus()).toBe("Queued");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadRedTeam).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadRedTeam).toHaveBeenCalledWith(OPP_ID);
    expect(redStatus()).toBe("Running");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(screen.getByText("[FINDING 3]")).toBeTruthy();
    expect(within(resultCard()).getByText("v1")).toBeTruthy();
    expect(redStatus()).toBe("Done");
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
    expect(within(resultCard()).getByText("v1")).toBeTruthy();
    expect(redStatus()).toBe("Running");
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

  it.each([queued, running])(
    "a review stalled while $status says to reload, with no running dot or activity icon",
    async (r) => {
      vi.useFakeTimers();
      loadRedTeam.mockResolvedValue({ kind: "ok", redTeam: view(null, r) });
      let hidden = true;
      const spy = vi.spyOn(document, "hidden", "get").mockImplementation(() => hidden);
      try {
        renderSection(view(null, r));
        vi.setSystemTime(Date.now() + 16 * 60 * 1000);
        hidden = false;
        act(() => {
          document.dispatchEvent(new Event("visibilitychange"));
        });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(100);
        });
        expect(within(redCard()).getByText("Still reviewing — reload to check.")).toBeTruthy();
        expect(within(redCard()).queryByText("Waiting for the worker")).toBeNull();
        expect(screen.queryByTestId("running-dot")).toBeNull();
        expect(screen.getByText(`1 ${r.status}`)).toBeTruthy();
        expect(screen.queryByTestId("activity-icon")).toBeNull();
      } finally {
        spy.mockRestore();
      }
    },
  );

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
    expect(within(redCard()).getByText("the model service couldn't be reached")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.click(retryButton()!);

    expect(startRedTeamReview).toHaveBeenCalledWith(OPP_ID);
    expect(redStatus()).toBe("Queued");
    expect(retryButton()).toBeNull();
    await waitFor(() => expect(screen.getByText("[FINDING 3]")).toBeTruthy(), { timeout: 4000 });
  });

  it("a Retry answered 409 re-reads the section", async () => {
    const user = userEvent.setup();
    startRedTeamReview.mockResolvedValue({ kind: "conflict" });
    loadRedTeam.mockResolvedValue({ kind: "ok", redTeam: view(null, running) });
    renderSection(view(null, failed));

    await user.click(retryButton()!);

    await waitFor(() => expect(redStatus()).toBe("Running"));
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

    await user.click(retryButton()!);

    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(retryButton()).toBeTruthy();
  });

  it("a sales representative sees the same Findings, read-only, and no Retry", async () => {
    const user = userEvent.setup();
    renderSection(view(review(), failed, false));
    expect(retryButton()).toBeNull();

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

    expect(within(resultCard()).getByText("v3")).toBeTruthy();
    expect(within(pane()).queryByText("[ARGUMENT 1]")).toBeNull();
    expect(
      within(pane()).getByText("Select a gap or estimate line to see its details."),
    ).toBeTruthy();
  });

  it("says so when a finished run had nothing to review", () => {
    renderSection(view(null, succeeded));
    expect(screen.getByText("There were no active Requirements to review.")).toBeTruthy();
  });
});
