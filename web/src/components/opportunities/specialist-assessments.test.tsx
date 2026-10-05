import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  StartAssessmentResult,
  StartRedTeamReviewResult,
} from "@/app/opportunities/actions";
import type {
  AssessmentsResult,
  RedTeamResult,
} from "@/app/opportunities/data";
import type {
  Assessment,
  AssessmentAgent,
  AssessmentFinding,
  AssessmentRun,
  AssessmentsView,
  AssessmentTask,
} from "@/lib/assessments";
import type { RedTeamView, Severity } from "@/lib/red-team";
import { axeViolations } from "@/test/axe";

const startAssessmentRun = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartAssessmentResult>>(),
);
const retryAssessmentTask = vi.hoisted(() =>
  vi.fn<
    (
      opportunityId: string,
      runId: unknown,
      agent: string,
    ) => Promise<StartAssessmentResult>
  >(),
);
const loadAssessments = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<AssessmentsResult>>(),
);
const startRedTeamReview = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartRedTeamReviewResult>>(),
);
const loadRedTeam = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<RedTeamResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  startAssessmentRun,
  retryAssessmentTask,
  loadAssessments,
  startRedTeamReview,
  loadRedTeam,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/opportunities/x/assessments",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { FindingSelectionProvider } from "./finding-selection";
import { RedTeamSection } from "./red-team-list";
import {
  SpecialistAssessmentsHeader,
  SpecialistAssessmentsSection,
} from "./specialist-assessments";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const RUN_ID = "00000000-0000-7000-8000-0000000000a1";
const AGENTS: AssessmentAgent[] = [
  "engineering_agent",
  "pm_agent",
  "security_agent",
];

function finding(
  n: number,
  severity: Severity,
  kind: AssessmentFinding["kind"] = "risk",
) {
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    position: n,
    kind,
    severity,
    title: `[FINDING ${n}]`,
    detail: `[DETAIL ${n}]`,
    requirements: [
      {
        id: `00000000-0000-7000-8000-0000000${String(n).padStart(3, "0")}0aa`,
        version: 1,
        label: "R2",
        excerpt: `[EXCERPT ${n}]`,
      },
    ],
  } satisfies AssessmentFinding;
}

function assessment(
  agent: AssessmentAgent,
  version: number,
  findings: AssessmentFinding[],
  extra: Partial<Assessment> = {},
): Assessment {
  return {
    id: `00000000-0000-7000-8000-0000000b${String(version).padStart(4, "0")}`,
    agent,
    version,
    status: "current",
    run_id: RUN_ID,
    recommendation: "proceed_with_conditions",
    confidence: "medium",
    confidence_basis: "[BASIS]",
    dropped_count: 0,
    created_at: "2026-10-05T09:00:00Z",
    counts: { critical: 1, high: 1, medium: 0, low: 0 },
    findings,
    effort: [
      {
        requirement: {
          id: "00000000-0000-7000-8000-0000000000f1",
          version: 1,
          label: "R1",
          excerpt: "",
        },
        hours: 40,
        basis: "[EFFORT BASIS 1]",
      },
      {
        requirement: {
          id: "00000000-0000-7000-8000-0000000000f3",
          version: 1,
          label: "R3",
          excerpt: "",
        },
        hours: 24.3,
        basis: "[EFFORT BASIS 3]",
      },
    ],
    total_hours: 64.3,
    ...extra,
  };
}

const ENGINEERING = assessment("engineering_agent", 2, [
  finding(3, "critical"),
  finding(1, "high", "constraint"),
]);
const PM = assessment("pm_agent", 1, [finding(4, "low", "dependency")], {
  recommendation: "proceed",
  confidence: "high",
  confidence_basis: "[PM BASIS]",
  counts: { critical: 0, high: 0, medium: 0, low: 1 },
  effort: [],
  total_hours: 0,
});

function task(
  agent: AssessmentAgent,
  status: AssessmentTask["status"],
  code: AssessmentTask["error_code"] = null,
) {
  return { agent, status, error_code: code };
}

function run(
  status: AssessmentRun["status"],
  tasks: AssessmentTask[],
): AssessmentRun {
  return { id: RUN_ID, status, created_at: "2026-10-05T09:00:00Z", tasks };
}

const queued = run(
  "queued",
  AGENTS.map((a) => task(a, "queued")),
);
const running = run("running", [
  task("engineering_agent", "running"),
  task("pm_agent", "succeeded"),
  task("security_agent", "queued"),
]);
const partial = run("partially_failed", [
  task("engineering_agent", "succeeded"),
  task("pm_agent", "succeeded"),
  task("security_agent", "failed", "model_unavailable"),
]);
const succeeded = run(
  "succeeded",
  AGENTS.map((a) => task(a, "succeeded")),
);

function view(
  r: AssessmentRun | null,
  current: Partial<Record<AssessmentAgent, Assessment>> = {},
  canStart = true,
): AssessmentsView {
  return {
    run: r,
    assessments: AGENTS.map((agent) => ({
      agent,
      assessment: current[agent] ?? null,
    })),
    can_start: canStart,
  };
}

const FULL = { engineering_agent: ENGINEERING, pm_agent: PM };

function renderSection(initial: AssessmentsView, singleKeyShortcuts = true) {
  return render(
    <ShellProviders singleKeyShortcuts={singleKeyShortcuts}>
      <SpecialistAssessmentsSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const row = (n: number) =>
  screen.getByRole("button", { name: new RegExp(`\\[FINDING ${n}\\]`) });
const pane = () => screen.getByRole("complementary", { name: "Details" });

beforeEach(() => {
  startAssessmentRun.mockReset();
  retryAssessmentTask.mockReset();
  loadAssessments.mockReset();
  startRedTeamReview.mockReset();
  loadRedTeam.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("SpecialistAssessmentsSection", () => {
  it("shows the empty sentence and Run assessment before any run", async () => {
    const { container } = renderSection(view(null));
    expect(
      screen.getByRole("heading", { level: 3, name: "Specialist Assessments" }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "No assessment yet. Run assessment to have the Engineering, PM and Security Agents review this Opportunity.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows one card per agent with recommendation, confidence, counts, Findings and effort", async () => {
    const { container } = renderSection(view(succeeded, FULL));

    const engineering = screen.getByRole("article", {
      name: "Engineering Agent",
    });
    expect(within(engineering).getByText("v2")).toBeTruthy();
    const pill = engineering.querySelector("[data-recommendation]");
    expect(pill?.textContent).toBe("Proceed with conditions");
    expect(pill?.querySelector("svg")?.getAttribute("class")).toContain(
      "text-gap",
    );
    expect(within(engineering).getByText("Medium confidence")).toBeTruthy();
    expect(within(engineering).getByText(": [BASIS]")).toBeTruthy();
    expect(
      within(engineering).getByText("1 critical · 1 high · 0 medium · 0 low"),
    ).toBeTruthy();
    const grid = within(engineering).getByRole("grid", {
      name: "Engineering Agent Findings",
    });
    expect(
      within(grid)
        .getAllByRole("row")
        .map((r) => r.textContent),
    ).toEqual([
      "CriticalRisk[FINDING 3]1 Requirement",
      "HighConstraint[FINDING 1]1 Requirement",
    ]);
    expect(row(3).className).toContain("min-h-row");
    const table = within(engineering).getByRole("table", {
      name: "Engineering Agent effort",
    });
    expect(
      within(table)
        .getAllByRole("row")
        .map((r) => r.textContent),
    ).toEqual([
      "RequirementHoursBasis",
      "R140.0[EFFORT BASIS 1]",
      "R324.3[EFFORT BASIS 3]",
      "Total64.3",
    ]);

    const pm = screen.getByRole("article", { name: "PM Agent" });
    expect(pm.querySelector("[data-recommendation]")?.textContent).toBe(
      "Proceed",
    );
    expect(within(pm).getByText("High confidence")).toBeTruthy();
    expect(within(pm).getByText("No effort sized.")).toBeTruthy();
    const security = screen.getByRole("article", { name: "Security Agent" });
    expect(within(security).getByText("No Assessment yet.")).toBeTruthy();
    expect(screen.getByText("Assessment complete")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Agent progress" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Enter opens a Finding in the right pane, read-only, with focus on its title", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(succeeded, FULL));

    await user.tab(); // Run assessment
    await user.tab(); // the first row of the first card
    expect(document.activeElement).toBe(row(3));
    await user.keyboard("j");
    expect(document.activeElement).toBe(row(1));
    await user.keyboard("{Enter}");

    const inspector = pane();
    const heading = within(inspector).getByRole("heading", {
      level: 3,
      name: "[FINDING 1]",
    });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(row(1).closest("[role=row]")?.getAttribute("aria-selected")).toBe(
      "true",
    );
    expect(within(inspector).getByText("High")).toBeTruthy();
    expect(
      within(inspector).getByText("Constraint · Engineering Agent"),
    ).toBeTruthy();
    expect(within(inspector).getByText("[DETAIL 1]")).toBeTruthy();
    expect(within(inspector).getByText("R2")).toBeTruthy();
    expect(within(inspector).getByText("[EXCERPT 1]")).toBeTruthy();
    const region = within(inspector).getByRole("region", {
      name: "[FINDING 1]",
    });
    expect(within(region).queryByRole("button")).toBeNull();
    expect(within(region).queryByRole("textbox")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Run assessment starts a run, shows each agent's progress and polls until done", async () => {
    const user = userEvent.setup();
    startAssessmentRun.mockResolvedValue({ kind: "ok", run: queued });
    loadAssessments
      .mockResolvedValueOnce({ kind: "ok", assessments: view(running) })
      .mockResolvedValue({ kind: "ok", assessments: view(succeeded, FULL) });
    renderSection(view(null));

    await user.click(screen.getByRole("button", { name: "Run assessment" }));

    expect(startAssessmentRun).toHaveBeenCalledWith(OPP_ID);
    const progress = screen.getByRole("list", { name: "Agent progress" });
    expect(
      within(progress)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "Engineering Agent — Assessing…",
      "PM Agent — Assessing…",
      "Security Agent — Assessing…",
    ]);
    expect(screen.getAllByTestId("running-dot")[0].className).toContain(
      "motion-reduce:animate-none",
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Run assessment",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    await waitFor(
      () => expect(screen.getByText("PM Agent — Done")).toBeTruthy(),
      {
        timeout: 4000,
      },
    );
    await waitFor(() => expect(screen.getByText("[FINDING 3]")).toBeTruthy(), {
      timeout: 4000,
    });
    expect(screen.queryByRole("list", { name: "Agent progress" })).toBeNull();
  }, 15_000);

  it("polls every 2 s only while assessing", async () => {
    vi.useFakeTimers();
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(succeeded, FULL),
    });
    renderSection(view(running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(loadAssessments).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(loadAssessments).toHaveBeenCalledWith(OPP_ID);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.getByRole("status").textContent).toBe("Assessment complete");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadAssessments).toHaveBeenCalledTimes(1);
  });

  it("pauses polling while the tab is hidden", async () => {
    vi.useFakeTimers();
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(running),
    });
    let hidden = true;
    const spy = vi
      .spyOn(document, "hidden", "get")
      .mockImplementation(() => hidden);
    try {
      renderSection(view(running));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10_000);
      });
      expect(loadAssessments).not.toHaveBeenCalled();
      hidden = false;
      act(() => {
        document.dispatchEvent(new Event("visibilitychange"));
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000);
      });
      expect(loadAssessments).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("stops polling after 15 minutes and says to reload", async () => {
    vi.useFakeTimers();
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(running),
    });
    renderSection(view(running));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(loadAssessments).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() + 15 * 60 * 1000);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000); // the poll already scheduled still runs
    });
    const calls = loadAssessments.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(loadAssessments).toHaveBeenCalledTimes(calls);
    expect(screen.getByText("Still assessing — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("a failed agent shows its reason and Retry, which re-runs only that task", async () => {
    const user = userEvent.setup();
    const retried = run("queued", [
      task("engineering_agent", "succeeded"),
      task("pm_agent", "succeeded"),
      task("security_agent", "queued"),
    ]);
    retryAssessmentTask.mockResolvedValue({ kind: "ok", run: retried });
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(running, FULL),
    });
    const { container } = renderSection(view(partial, FULL));
    expect(screen.getByText("Assessment partly failed")).toBeTruthy();
    const progress = screen.getByRole("list", { name: "Agent progress" });
    expect(
      within(progress)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "Engineering Agent — Done",
      "PM Agent — Done",
      "Security Agent — Failed: the model service couldn't be reachedRetry",
    ]);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(
      screen.getByRole("button", { name: "Retry Security Agent" }),
    );

    expect(retryAssessmentTask).toHaveBeenCalledWith(
      OPP_ID,
      RUN_ID,
      "security_agent",
    );
    expect(screen.getByText("Security Agent — Assessing…")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("a sales representative sees the same Assessments, with no Run assessment or Retry", async () => {
    const user = userEvent.setup();
    renderSection(view(partial, FULL, false));
    expect(screen.queryByRole("button", { name: "Run assessment" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();

    await user.click(row(4));

    expect(within(pane()).getByText("[DETAIL 4]")).toBeTruthy();
  });

  it.each([
    [
      { kind: "error" } as const,
      "The assessment could not be started. Try again.",
    ],
    [
      { kind: "forbidden" } as const,
      "Only the owner and collaborators, except sales representatives, can run an assessment.",
    ],
  ])("a failed start says so (%#)", async (result, sentence) => {
    const user = userEvent.setup();
    startAssessmentRun.mockResolvedValue(result);
    renderSection(view(null));

    await user.click(screen.getByRole("button", { name: "Run assessment" }));

    expect(await screen.findByText(sentence)).toBeTruthy();
  });

  it("a start answered 409 re-reads the section", async () => {
    const user = userEvent.setup();
    startAssessmentRun.mockResolvedValue({ kind: "conflict" });
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(running),
    });
    renderSection(view(null));

    await user.click(screen.getByRole("button", { name: "Run assessment" }));

    await waitFor(() =>
      expect(screen.getByText("Engineering Agent — Assessing…")).toBeTruthy(),
    );
  });

  it("says so when a finished run had nothing to assess", () => {
    renderSection(view(succeeded));
    expect(
      screen.getByText("There were no active Requirements to assess."),
    ).toBeTruthy();
  });
});

describe("SpecialistAssessmentsHeader", () => {
  it("shows nothing but Run assessment before any run", () => {
    render(<SpecialistAssessmentsHeader run={null} canStart />);
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("keeps the agent lines once a run has failed, without Retry for readers", () => {
    render(
      <SpecialistAssessmentsHeader
        run={run(
          "failed",
          AGENTS.map((a) => task(a, "failed", "model_timeout")),
        )}
      />,
    );
    expect(screen.getByText("Assessment failed")).toBeTruthy();
    expect(
      screen.getByText(
        "Engineering Agent — Failed: the model took too long to answer",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("one Finding selected across the tab", () => {
  const redTeam: RedTeamView = {
    review: {
      id: "00000000-0000-7000-8000-0000000000c1",
      version: 1,
      status: "current",
      estimate_version_id: null,
      estimate_version: null,
      dropped_count: 0,
      created_at: "2026-10-05T09:00:00Z",
      counts: { critical: 0, high: 1, medium: 0, low: 0 },
      findings: [
        {
          id: "00000000-0000-7000-8000-0000000000c2",
          position: 1,
          category: "integration_harder",
          severity: "high",
          title: "[RED TEAM FINDING]",
          argument: "[ARGUMENT]",
          requirements: [],
          lines: [],
        },
      ],
    },
    run: { status: "succeeded", error_code: null },
    can_start: false,
  };

  it("selecting a Red Team Finding clears the specialist selection, and back", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ShellProviders singleKeyShortcuts>
        <FindingSelectionProvider>
          <SpecialistAssessmentsSection
            opportunityId={OPP_ID}
            initial={view(succeeded, FULL)}
          />
          <RedTeamSection opportunityId={OPP_ID} initial={redTeam} />
        </FindingSelectionProvider>
        <RightPane />
      </ShellProviders>,
    );
    const redRow = screen.getByRole("button", { name: /\[RED TEAM FINDING\]/ });

    await user.click(row(3));
    expect(within(pane()).getByText("[DETAIL 3]")).toBeTruthy();
    expect(row(3).closest("[role=row]")?.getAttribute("aria-selected")).toBe(
      "true",
    );

    await user.click(redRow);
    expect(within(pane()).getByText("[ARGUMENT]")).toBeTruthy();
    expect(within(pane()).queryByText("[DETAIL 3]")).toBeNull();
    expect(row(3).closest("[role=row]")?.getAttribute("aria-selected")).toBe(
      "false",
    );
    expect(redRow.closest("[role=row]")?.getAttribute("aria-selected")).toBe(
      "true",
    );

    await user.click(row(4));
    expect(within(pane()).getByText("[DETAIL 4]")).toBeTruthy();
    expect(within(pane()).queryByText("[ARGUMENT]")).toBeNull();
    expect(redRow.closest("[role=row]")?.getAttribute("aria-selected")).toBe(
      "false",
    );
    expect(await axeViolations(container)).toEqual([]);
  });
});
