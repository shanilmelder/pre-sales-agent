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
const cancelAssessmentRun = vi.hoisted(() =>
  vi.fn<
    (opportunityId: string, runId: unknown) => Promise<StartAssessmentResult>
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
  cancelAssessmentRun,
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

const T0 = Date.parse("2026-10-05T09:00:00Z");
/** The fixture clock: `s` seconds after the run was queued. */
const at = (s: number) => new Date(T0 + s * 1000).toISOString();

/** A task. Started tasks start 5 s in; finished ones (succeeded or failed) by default after
 * 40 s. */
function task(
  agent: AssessmentAgent,
  status: AssessmentTask["status"],
  code: AssessmentTask["error_code"] = null,
  times: Partial<Pick<AssessmentTask, "started_at" | "finished_at">> = {},
): AssessmentTask {
  const started = status === "queued" ? null : at(5);
  const finished =
    status === "succeeded" || status === "failed" ? at(45) : null;
  return {
    agent,
    status,
    error_code: code,
    started_at: started,
    finished_at: finished,
    ...times,
  };
}

function run(
  status: AssessmentRun["status"],
  tasks: AssessmentTask[],
): AssessmentRun {
  const finished = status === "queued" || status === "running" ? null : at(300);
  return {
    id: RUN_ID,
    status,
    created_at: at(0),
    queued_at: at(0),
    finished_at: finished,
    tasks,
  };
}

/** Each panel row's non-empty parts (role, pill, elapsed time, note, Retry). */
function panelRows() {
  const progress = screen.getByRole("list", { name: "Agent progress" });
  return within(progress)
    .getAllByRole("listitem")
    .map((li) =>
      Array.from(li.children)
        .map((c) => c.textContent ?? "")
        .filter((t) => t !== ""),
    );
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
  cancelAssessmentRun.mockReset();
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
        "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.",
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
    expect(panelRows().map((r) => r[1])).toEqual(["Done", "Done", "Done"]);
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
    expect(panelRows()).toEqual(
      ["Engineering Agent", "PM Agent", "Security Agent"].map((name) => [
        name,
        "Queued",
        "Waiting for the worker",
      ]),
    );
    expect(screen.queryByTestId("running-dot")).toBeNull();
    expect(
      (
        screen.getByRole("button", {
          name: "Run assessment",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    await waitFor(
      () => expect(panelRows()[1]).toEqual(["PM Agent", "Done", "0:40"]),
      { timeout: 4000 },
    );
    expect(screen.getAllByTestId("running-dot")).toHaveLength(1);
    await waitFor(() => expect(screen.getByText("[FINDING 3]")).toBeTruthy(), {
      timeout: 4000,
    });
    // The panel stays for the finished run, every row with its duration.
    expect(panelRows()).toEqual(
      ["Engineering Agent", "PM Agent", "Security Agent"].map((name) => [
        name,
        "Done",
        "0:40",
      ]),
    );
    expect(screen.queryByTestId("running-dot")).toBeNull();
  }, 15_000);

  it("opened while the automatic run is queued, shows the run panel and polls", async () => {
    vi.useFakeTimers();
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(succeeded, FULL),
    });
    renderSection(view(queued));

    expect(panelRows()).toEqual(
      ["Engineering Agent", "PM Agent", "Security Agent"].map((name) => [
        name,
        "Queued",
        "Waiting for the worker",
      ]),
    );
    expect(
      screen.queryByText(
        "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.",
      ),
    ).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(loadAssessments).toHaveBeenCalledWith(OPP_ID);
    expect(screen.getByText("[FINDING 3]")).toBeTruthy();
  });

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
    expect(panelRows()).toEqual([
      ["Engineering Agent", "Done", "0:40"],
      ["PM Agent", "Done", "0:40"],
      [
        "Security Agent",
        "Failed",
        "0:40",
        "the model service couldn't be reached",
        "Retry",
      ],
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
    expect(panelRows()[2]).toEqual([
      "Security Agent",
      "Queued",
      "Waiting for the worker",
    ]);
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("a sales representative sees the same Assessments, with no Run assessment or Retry", async () => {
    const user = userEvent.setup();
    renderSection(view(partial, FULL, false));
    expect(screen.queryByRole("button", { name: "Run assessment" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
    expect(panelRows()[2]).toEqual([
      "Security Agent",
      "Failed",
      "0:40",
      "the model service couldn't be reached",
    ]);

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
      expect(panelRows()[0].slice(0, 2)).toEqual([
        "Engineering Agent",
        "Running",
      ]),
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
    expect(panelRows()[0]).toEqual([
      "Engineering Agent",
      "Failed",
      "0:40",
      "the model took too long to answer",
    ]);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("AgentRunPanel timings", () => {
  const NOW = T0 + 70_000;

  it("shows a final duration, a ticking time and a waiting row, ticking without a fetch", async () => {
    vi.useFakeTimers();
    let container: HTMLElement;
    try {
      vi.setSystemTime(NOW);
      const timings = run("running", [
        task("engineering_agent", "succeeded", null, {
          started_at: at(5),
          finished_at: at(47),
        }),
        task("pm_agent", "running"), // started 5 s in: 65 s ago
        task("security_agent", "queued"),
      ]);
      loadAssessments.mockResolvedValue({
        kind: "ok",
        assessments: view(timings),
      });
      ({ container } = renderSection(view(timings)));

      expect(panelRows()).toEqual([
        ["Engineering Agent", "Done", "0:42"],
        ["PM Agent", "Running", "1:05"],
        ["Security Agent", "Queued", "Waiting for the worker"],
      ]);
      expect(screen.getAllByTestId("running-dot")).toHaveLength(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(panelRows()[1]).toEqual(["PM Agent", "Running", "1:06"]);
      expect(panelRows()[0]).toEqual(["Engineering Agent", "Done", "0:42"]);
      expect(loadAssessments).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a failed task shows its reason, its duration and Retry for those who may start", () => {
    const failed = run("partially_failed", [
      task("engineering_agent", "succeeded"),
      task("pm_agent", "succeeded"),
      task("security_agent", "failed", "model_timeout", {
        started_at: at(5),
        finished_at: at(135),
      }),
    ]);
    render(<SpecialistAssessmentsHeader run={failed} canStart />);
    expect(panelRows()[2]).toEqual([
      "Security Agent",
      "Failed",
      "2:10",
      "the model took too long to answer",
      "Retry",
    ]);
  });

  it("a lost run's task with no finish time shows no time", () => {
    const lost = {
      ...run("failed", [
        task("engineering_agent", "failed", "model_timeout", {
          finished_at: null,
        }),
        task("pm_agent", "failed", "model_timeout", {
          started_at: null,
          finished_at: null,
        }),
        task("security_agent", "succeeded"),
      ]),
      finished_at: null, // a lost run is not recorded as finished yet
    };
    render(<SpecialistAssessmentsHeader run={lost} />);
    expect(screen.getAllByTestId("elapsed").map((e) => e.textContent)).toEqual([
      "",
      "",
      "0:40",
    ]);
  });

  it("stops the clock once polling has stalled", async () => {
    vi.useFakeTimers();
    try {
      vi.setSystemTime(NOW);
      const { rerender } = render(
        <SpecialistAssessmentsHeader run={running} />,
      );
      expect(panelRows()[0]).toEqual(["Engineering Agent", "Running", "1:05"]);
      rerender(<SpecialistAssessmentsHeader run={running} stalled />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(
        screen.getByText("Still assessing — reload to check."),
      ).toBeTruthy();
      expect(panelRows()[0]).toEqual(["Engineering Agent", "Running", "1:05"]);
      expect(screen.queryByTestId("running-dot")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("the running dot is static under reduced motion", () => {
    render(<SpecialistAssessmentsHeader run={running} />);
    const dot = screen.getByTestId("running-dot");
    expect(dot.className).toContain("animate-pulse");
    expect(dot.className).toContain("motion-reduce:animate-none");
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

describe("cancelling a run (Story 5.5)", () => {
  const cancelled = run("cancelled", [
    task("engineering_agent", "succeeded"),
    task("pm_agent", "skipped", null, { finished_at: at(65) }),
    task("security_agent", "skipped", null, { started_at: null }),
  ]);
  const cancelButton = () => screen.getByRole("button", { name: "Cancel run" });

  it("asks first; Keep running sends nothing and gives focus back", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(running, FULL));

    await user.click(cancelButton());

    const dialog = await screen.findByRole("dialog", {
      name: "Cancel this run?",
    });
    expect(within(dialog).getByText("Completed results are kept.")).toBeTruthy();
    expect(await axeViolations(container.ownerDocument.body)).toEqual([]);

    await user.click(within(dialog).getByRole("button", { name: "Keep running" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(cancelAssessmentRun).not.toHaveBeenCalled();
    await waitFor(() => expect(document.activeElement).toBe(cancelButton()));
    expect(screen.getByText("Assessing")).toBeTruthy();
  });

  it("Confirm cancels: skipped rows, the cancelled header, an announcement and Run assessment again", async () => {
    const user = userEvent.setup();
    cancelAssessmentRun.mockResolvedValue({ kind: "ok", run: cancelled });
    const { container } = renderSection(view(running, FULL));

    await user.click(cancelButton());
    const dialog = await screen.findByRole("dialog", {
      name: "Cancel this run?",
    });
    await user.click(within(dialog).getByRole("button", { name: "Confirm" }));

    expect(cancelAssessmentRun).toHaveBeenCalledWith(OPP_ID, RUN_ID);
    expect(
      await screen.findByText("Cancelled — completed results kept"),
    ).toBeTruthy();
    expect(panelRows()).toEqual([
      ["Engineering Agent", "Done", "0:40"],
      ["PM Agent", "Skipped", "1:00"], // it had started: its duration until the cancel
      ["Security Agent", "Skipped"], // never started: no time
    ]);
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    const start = screen.getByRole("button", { name: "Run assessment" });
    expect((start as HTMLButtonElement).disabled).toBe(false);
    await waitFor(() => expect(document.activeElement).toBe(start));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe(
        "Cancelled — completed results kept",
      ),
    );
    expect(screen.getByText("[FINDING 3]")).toBeTruthy(); // completed results stay
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a cancel answered 409 re-reads the section", async () => {
    const user = userEvent.setup();
    cancelAssessmentRun.mockResolvedValue({ kind: "conflict" });
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(succeeded, FULL),
    });
    renderSection(view(running, FULL));

    await user.click(cancelButton());
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Confirm",
      }),
    );

    expect(await screen.findByText("Assessment complete")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    const start = screen.getByRole("button", { name: "Run assessment" });
    await waitFor(() => expect(document.activeElement).toBe(start));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe(
        "Assessment complete",
      ),
    );
  });

  it("Cancel run is disabled while another action is in flight", async () => {
    const user = userEvent.setup();
    let finish: (result: StartAssessmentResult) => void = () => {};
    cancelAssessmentRun.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    renderSection(view(running, FULL));

    await user.click(cancelButton());
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Confirm",
      }),
    );

    await waitFor(() =>
      expect((cancelButton() as HTMLButtonElement).disabled).toBe(true),
    );
    await user.click(cancelButton());
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(cancelAssessmentRun).toHaveBeenCalledTimes(1);
    await act(async () => finish({ kind: "error" }));
    expect((cancelButton() as HTMLButtonElement).disabled).toBe(false);
  });

  it("a failed cancel says so", async () => {
    const user = userEvent.setup();
    cancelAssessmentRun.mockResolvedValue({ kind: "error" });
    renderSection(view(queued));

    await user.click(cancelButton());
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Confirm",
      }),
    );

    expect(
      await screen.findByText("The run could not be cancelled. Try again."),
    ).toBeTruthy();
    expect(cancelButton()).toBeTruthy();
  });

  it("only those who may start see Cancel run, and only while queued or running", () => {
    const { unmount } = renderSection(view(running, FULL, false));
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    unmount();
    renderSection(view(partial, FULL));
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
  });

  it("a cancelled run offers no Retry, even for a task that failed before the cancel", () => {
    render(
      <SpecialistAssessmentsHeader
        canStart
        run={run("cancelled", [
          task("engineering_agent", "skipped", null, { started_at: null }),
          task("pm_agent", "succeeded"),
          task("security_agent", "failed", "model_unavailable"),
        ])}
      />,
    );
    expect(screen.getByText("Cancelled — completed results kept")).toBeTruthy();
    expect(panelRows()[2]).toEqual([
      "Security Agent",
      "Failed",
      "0:40",
      "the model service couldn't be reached",
    ]);
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
  });
});
