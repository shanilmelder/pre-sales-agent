import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ResolveRunDecisionInput,
  RunDecisionResult,
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
  RunDecision,
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
const resolveRunDecision = vi.hoisted(() =>
  vi.fn<(input: ResolveRunDecisionInput) => Promise<RunDecisionResult>>(),
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
  resolveRunDecision,
  loadAssessments,
  startRedTeamReview,
  loadRedTeam,
}));
const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh,
  }),
  usePathname: () => "/opportunities/x/assessments",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { FindingSelectionProvider } from "./finding-selection";
import {
  AgentRunPanel,
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
    config_version_id: "00000000-0000-7000-8000-0000000c0001",
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
    plan_version: 1,
    decisions: [],
    plan_versions: [],
  };
}

/** Each task card's non-empty parts (name, pill, elapsed time, note, Retry). */
function panelRows() {
  const progress = screen.getByRole("list", { name: "Agent progress" });
  return within(progress)
    .getAllByRole("listitem")
    .map((li) =>
      [
        li.querySelector("[data-part='name']")?.textContent,
        li.querySelector("[data-task-pill]")?.textContent,
        li.querySelector("[data-testid='elapsed']")?.textContent,
        li.querySelector("[data-part='note']")?.textContent,
        li.querySelector("button")?.textContent,
      ].filter((t): t is string => !!t),
    );
}

/** The run header with the Agent tasks grid under it, as the section lays them out. */
function HeaderAndTasks(
  props: Parameters<typeof SpecialistAssessmentsHeader>[0],
) {
  return (
    <>
      <SpecialistAssessmentsHeader {...props} />
      {props.run ? (
        <AgentRunPanel
          run={props.run}
          canStart={props.canStart}
          stalled={props.stalled}
        />
      ) : null}
    </>
  );
}

/** The Findings table's rows. */
const findingRows = () =>
  within(screen.getByRole("grid", { name: "Findings" }))
    .getAllByRole("row")
    .map((r) => r.textContent);

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
    can_resolve: canStart,
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
  resolveRunDecision.mockReset();
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
    expect(screen.queryByTestId("run-header")).toBeNull();
    expect(
      screen.getByText(
        "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows a result card per agent with an Assessment, and one Findings table", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(succeeded, FULL));

    const engineering = screen.getByRole("article", {
      name: "Engineering Agent",
    });
    expect(within(engineering).getByText("v2")).toBeTruthy();
    const pill = engineering.querySelector("[data-recommendation]");
    expect(pill?.textContent).toBe("Proceed with conditions");
    expect(pill?.getAttribute("data-slot")).toBe("pill");
    expect(pill?.getAttribute("data-tone")).toBe("gap");
    expect(pill?.querySelector("svg")).toBeTruthy();
    expect(within(engineering).getByText("Medium confidence")).toBeTruthy();
    expect(within(engineering).getByText("[BASIS]")).toBeTruthy();
    // Up to three Requirement evidence chips, one per label.
    expect(
      within(within(engineering).getByRole("list", { name: "Evidence" }))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["R2", "R1", "R3"]);
    // The effort table is behind Show effort.
    expect(
      within(engineering).queryByRole("table", {
        name: "Engineering Agent effort",
      }),
    ).toBeNull();
    const showEffort = within(engineering).getByRole("button", {
      name: "Show effort: Engineering Agent",
    });
    expect(showEffort.getAttribute("aria-expanded")).toBe("false");
    await user.click(showEffort);
    expect(showEffort.getAttribute("aria-expanded")).toBe("true");
    expect(showEffort.textContent).toBe("Hide effort");
    expect(showEffort.getAttribute("aria-label")).toBe(
      "Hide effort: Engineering Agent",
    );
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
    await user.click(
      within(pm).getByRole("button", { name: "Show effort: PM Agent" }),
    );
    expect(within(pm).getByText("No effort sized.")).toBeTruthy();
    // No card for an agent without an Assessment.
    expect(screen.queryByRole("article", { name: "Security Agent" })).toBeNull();

    expect(findingRows()).toEqual([
      "CriticalRisk[FINDING 3]Engineering Agent1 Requirement",
      "HighConstraint[FINDING 1]Engineering Agent1 Requirement",
      "LowDependency[FINDING 4]PM Agent1 Requirement",
    ]);
    expect(
      screen.getByText("1 Critical · 1 High · 0 Medium · 1 Low"),
    ).toBeTruthy();
    expect(row(3).className).toContain("min-h-row");
    expect(screen.getByText("Assessment complete")).toBeTruthy();
    expect(panelRows().map((r) => r[1])).toEqual(["Done", "Done", "Done"]);
    expect(
      screen
        .getAllByRole("heading", { level: 3 })
        .map((h) => h.textContent),
    ).toEqual(["Agent tasks", "Results so far", "Findings"]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Enter opens a Finding in the right pane, read-only, with focus on its title", async () => {
    const user = userEvent.setup();
    const { container } = renderSection(view(succeeded, FULL));

    await user.tab(); // Start new run
    await user.tab(); // Show effort (Engineering Agent)
    await user.tab(); // Show effort (PM Agent)
    await user.tab(); // the first row of the Findings table
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
          name: "Start new run",
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

  it("refreshes the tab's server reads once when the polled run finishes", async () => {
    vi.useFakeTimers();
    refresh.mockClear();
    loadAssessments
      .mockResolvedValueOnce({ kind: "ok", assessments: view(running) })
      .mockResolvedValue({ kind: "ok", assessments: view(succeeded, FULL) });
    renderSection(view(queued));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(refresh).not.toHaveBeenCalled(); // still running
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByText("[FINDING 3]")).toBeTruthy();
    expect(refresh).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not refresh on a page load of a finished run", async () => {
    vi.useFakeTimers();
    refresh.mockClear();
    renderSection(view(succeeded, FULL));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6000);
    });
    expect(loadAssessments).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
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

/** A stand-in for the browser's EventSource (jsdom has none): records its URL and
 * listeners, and lets a test emit the stream's events. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, ((event: Event) => void)[]>();
  closed = false;

  constructor(readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data?: Record<string, unknown>) {
    const event =
      data === undefined
        ? new Event(type)
        : new MessageEvent(type, { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

function progress(event_type: string, summary: string) {
  return {
    event_type,
    subject_type: event_type.startsWith("workflows.task")
      ? "workflows.task"
      : "workflows.run",
    subject_id: RUN_ID,
    subject_version: null,
    occurred_at: "2026-10-14T09:00:00Z",
    summary,
  };
}

/** A run waiting on a decision about the Security Agent (Story 5.5). */
const DECISION_ID = "00000000-0000-7000-8000-0000000000d1";
function decision(overrides: Partial<RunDecision> = {}): RunDecision {
  return {
    id: DECISION_ID,
    kind: "plan_escalation",
    agent: "security_agent",
    agent_name: "Security Agent",
    agent_active: false,
    status: "open",
    choice: null,
    row_version: 1,
    created_at: at(60),
    resolved_by: null,
    resolved_at: null,
    ...overrides,
  };
}
function waitingRun(open: RunDecision = decision()): AssessmentRun {
  return {
    ...run("waiting_for_human", [
      task("engineering_agent", "succeeded"),
      task("pm_agent", "succeeded"),
      task("security_agent", "queued", null, { started_at: null }),
    ]),
    finished_at: null,
    decisions: [open],
    plan_versions: [
      {
        version: 1,
        created_by: "Owner Person",
        created_at: at(0),
        tasks: [
          { agent: "engineering_agent", config_version_id: "c1", config_version: 1 },
          { agent: "pm_agent", config_version_id: "c2", config_version: 1 },
          { agent: "security_agent", config_version_id: "c3", config_version: 2 },
        ],
      },
    ],
  };
}

describe("live updates over the event stream (Story 5.2)", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
    refresh.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const source = () => FakeEventSource.instances[0];

  it("a run that starts waiting for a person re-reads, shows Waiting for you and refreshes", async () => {
    loadAssessments.mockResolvedValue({ kind: "ok", assessments: view(running, FULL) });
    renderSection(view(running, FULL));
    await act(async () => {
      source().emit("open");
    });
    expect(screen.queryByText("Waiting for you")).toBeNull();

    loadAssessments.mockResolvedValue({ kind: "ok", assessments: view(waitingRun(), FULL) });
    await act(async () => {
      source().emit(
        "workflows.run.waiting_for_human",
        progress("workflows.run.waiting_for_human", "security_agent waiting_for_human"),
      );
    });

    expect(loadAssessments).toHaveBeenCalledTimes(2);
    expect(screen.getAllByText("Waiting for you").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Security assessment not planned: Security Agent is disabled"),
    ).toBeTruthy();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("follows the same-origin stream: each task event re-reads the section, with no polling", async () => {
    vi.useFakeTimers();
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(queued),
    });
    const { unmount } = renderSection(view(queued));

    expect(source().url).toBe(`/api/opportunities/${OPP_ID}/events`);
    await act(async () => {
      source().emit("open"); // catches up once connected
    });
    expect(loadAssessments).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(loadAssessments).toHaveBeenCalledTimes(1); // live: no polling

    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(running),
    });
    await act(async () => {
      source().emit(
        "workflows.task.ended",
        progress("workflows.task.ended", "pm_agent succeeded"),
      );
    });
    expect(panelRows()[1]).toEqual(["PM Agent", "Done", "0:40"]);

    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(succeeded, FULL),
    });
    await act(async () => {
      source().emit(
        "workflows.run.ended",
        progress("workflows.run.ended", "run succeeded"),
      );
    });
    expect(screen.getByText("[FINDING 3]")).toBeTruthy();
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(loadAssessments).toHaveBeenCalledTimes(3);

    unmount();
    expect(source().closed).toBe(true);
  });

  it("shows a run queued automatically without a page refresh", async () => {
    loadAssessments.mockResolvedValue({ kind: "ok", assessments: view(null) });
    renderSection(view(null));
    await act(async () => {
      source().emit("open");
    });

    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(queued),
    });
    await act(async () => {
      source().emit(
        "workflows.run.queued",
        progress("workflows.run.queued", "run queued"),
      );
    });

    expect(panelRows().map((r) => r[1])).toEqual([
      "Queued",
      "Queued",
      "Queued",
    ]);
  });

  it("ignores frames that are not progress events", async () => {
    renderSection(view(succeeded, FULL));
    await act(async () => {
      source().emit("workflows.task.started", { event_type: "something.else" });
    });
    expect(loadAssessments).not.toHaveBeenCalled();
  });

  it("says to reload after 15 minutes of a run that sends no events, without re-reading", async () => {
    vi.useFakeTimers();
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(running),
    });
    renderSection(view(running));
    await act(async () => {
      source().emit("open");
    });
    expect(loadAssessments).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15 * 60 * 1000);
    });

    expect(loadAssessments).toHaveBeenCalledTimes(1); // live: no polling
    expect(screen.getByText("Still assessing — reload to check.")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("drops an older re-read that lands after a newer one", async () => {
    let answerFirst: (result: AssessmentsResult) => void = () => {};
    loadAssessments
      .mockImplementationOnce(
        () =>
          new Promise<AssessmentsResult>((resolve) => {
            answerFirst = resolve;
          }),
      )
      .mockResolvedValueOnce({
        kind: "ok",
        assessments: view(succeeded, FULL),
      });
    renderSection(view(queued));

    await act(async () => {
      source().emit(
        "workflows.task.started",
        progress("workflows.task.started", "pm_agent running"),
      );
      source().emit(
        "workflows.run.ended",
        progress("workflows.run.ended", "run succeeded"),
      );
    });
    expect(screen.getByText("[FINDING 3]")).toBeTruthy();

    await act(async () => {
      answerFirst({ kind: "ok", assessments: view(running) }); // the older read, late
    });

    expect(screen.getByText("[FINDING 3]")).toBeTruthy();
    expect(screen.queryByTestId("running-dot")).toBeNull();
  });

  it("falls back to polling every 2 s while the stream is down", async () => {
    vi.useFakeTimers();
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(queued),
    });
    renderSection(view(queued));
    await act(async () => {
      source().emit("open");
    });
    expect(loadAssessments).toHaveBeenCalledTimes(1);

    await act(async () => {
      source().emit("error"); // dropped; the browser reconnects by itself
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(loadAssessments).toHaveBeenCalledTimes(2);
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
      <HeaderAndTasks
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
    render(<HeaderAndTasks run={failed} canStart />);
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
    render(<HeaderAndTasks run={lost} />);
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
        <HeaderAndTasks run={running} />,
      );
      expect(panelRows()[0]).toEqual(["Engineering Agent", "Running", "1:05"]);
      rerender(<HeaderAndTasks run={running} stalled />);
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

  it("the running dot is a static icon with no animation", () => {
    render(<HeaderAndTasks run={running} />);
    const dot = screen.getByTestId("running-dot");
    expect(dot.tagName.toLowerCase()).toBe("svg");
    expect(dot.getAttribute("class") ?? "").toContain("lucide-loader-circle");
    expect(dot.getAttribute("class") ?? "").toContain("text-agent");
    expect(dot.getAttribute("class") ?? "").not.toContain("animate");
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
            redTeam={redTeam}
          />
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

describe("a disabled Agent (Story 7.1)", () => {
  it("shows its skipped task as 'Agent disabled — assess manually', with no Retry", async () => {
    // Story 5.5: a person chose Continue without, so the run itself succeeded.
    const skipped = run("succeeded", [
      task("engineering_agent", "succeeded"),
      task("pm_agent", "succeeded"),
      {
        ...task("security_agent", "skipped", null, { started_at: null }),
        skip_reason: "agent_disabled",
      },
    ]);
    const { container } = renderSection(view(skipped, FULL));
    expect(panelRows()).toEqual([
      ["Engineering Agent", "Done", "0:40"],
      ["PM Agent", "Done", "0:40"],
      ["Security Agent", "Skipped", "Agent disabled — assess manually"],
    ]);
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
    expect(screen.getByText("Assessment complete")).toBeTruthy();
    expect(screen.queryByTestId("run-alert")).toBeNull(); // no "partly failed" alert
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("a run waiting for a person (Story 5.5)", () => {
  const securityCard = () =>
    screen
      .getAllByRole("listitem")
      .find((li) => li.textContent?.includes("Security Agent") && li.dataset.taskStatus)!;

  it("shows Waiting for you, why, and the two choices; Re-plan waits for the agent", async () => {
    const { container } = renderSection(view(waitingRun(), FULL));

    const card = securityCard();
    expect(within(card).getByText("Waiting for you")).toBeTruthy();
    expect(
      within(card).getByText(
        "Security assessment not planned: Security Agent is disabled",
      ),
    ).toBeTruthy();
    expect(within(card).getByRole("button", { name: "Continue without Security Agent" }))
      .toBeTruthy();
    const replan = within(card).getByRole("button", { name: "Re-plan Security Agent" });
    expect((replan as HTMLButtonElement).disabled).toBe(true);
    const hint = document.getElementById(replan.getAttribute("aria-describedby")!);
    expect(hint?.textContent).toBe("Enable the agent first");
    expect(screen.getAllByText("Waiting for you").length).toBeGreaterThan(1); // header too
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeTruthy();
    const start = screen.getByRole("button", { name: "Start new run" });
    expect((start as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("plan-versions").textContent).toContain("Plan v1");
    expect(screen.getByTestId("plan-versions").textContent).toContain("Security Agent v2");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Continue without sends the decision's version and shows the queued run", async () => {
    const user = userEvent.setup();
    const queuedAgain: AssessmentRun = {
      ...waitingRun(decision({ status: "resolved", choice: "continue_without", row_version: 2 })),
      status: "queued",
    };
    resolveRunDecision.mockResolvedValue({ kind: "ok", run: queuedAgain });
    renderSection(view(waitingRun(), FULL));

    await user.click(screen.getByRole("button", { name: "Continue without Security Agent" }));

    expect(resolveRunDecision).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      runId: RUN_ID,
      decisionId: DECISION_ID,
      rowVersion: 1,
      choice: "continue_without",
    });
    expect(await screen.findByText("Assessment queued")).toBeTruthy();
    expect(screen.queryByText("Waiting for you")).toBeNull();
  });

  it("Re-plan is enabled once the agent is active again", async () => {
    const user = userEvent.setup();
    resolveRunDecision.mockResolvedValue({ kind: "error" });
    renderSection(view(waitingRun(decision({ agent_active: true })), FULL));

    const replan = screen.getByRole("button", { name: "Re-plan Security Agent" });
    expect((replan as HTMLButtonElement).disabled).toBe(false);
    expect(replan.getAttribute("aria-describedby")).toBeNull();
    await user.click(replan);
    expect(resolveRunDecision).toHaveBeenCalledWith(
      expect.objectContaining({ choice: "replan" }),
    );
    expect(
      await screen.findByText("The decision could not be saved. Try again."),
    ).toBeTruthy();
  });

  it("a decision someone resolved first says who, and re-reads", async () => {
    const user = userEvent.setup();
    resolveRunDecision.mockResolvedValue({
      kind: "stale",
      message: "Already resolved by Sam Person.",
    });
    loadAssessments.mockResolvedValue({
      kind: "ok",
      assessments: view(
        {
          ...waitingRun(decision({ status: "resolved", choice: "replan", row_version: 2 })),
          status: "running",
        },
        FULL,
      ),
    });
    renderSection(view(waitingRun(), FULL));

    await user.click(screen.getByRole("button", { name: "Continue without Security Agent" }));

    expect(await screen.findByText("Already resolved by Sam Person.")).toBeTruthy();
    expect(loadAssessments).toHaveBeenCalledWith(OPP_ID);
    await waitFor(() => expect(screen.queryByRole("button", { name: /Re-plan/ })).toBeNull());
  });

  it("shows no decision while the run is queued again, even with another still open", async () => {
    const queuedAgain: AssessmentRun = { ...waitingRun(), status: "queued" };
    renderSection(view(queuedAgain, FULL));
    expect(screen.queryByText("Waiting for you")).toBeNull();
    expect(screen.queryByRole("button", { name: /Continue without/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Re-plan/ })).toBeNull();
    expect(panelRows()[2]).toEqual(["Security Agent", "Queued", "Waiting for the worker"]);
  });

  it("is read-only for those who may not resolve (sales representatives)", async () => {
    const { container } = renderSection(view(waitingRun(), FULL, false));
    expect(within(securityCard()).getByText("Waiting for you")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Continue without/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Re-plan/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel run" })).toBeNull();
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
    expect(
      within(dialog).getByText("Completed results are kept."),
    ).toBeTruthy();
    expect(await axeViolations(container.ownerDocument.body)).toEqual([]);

    await user.click(
      within(dialog).getByRole("button", { name: "Keep running" }),
    );

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
    const start = screen.getByRole("button", { name: "Start new run" });
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
    const start = screen.getByRole("button", { name: "Start new run" });
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
      <HeaderAndTasks
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
    expect(screen.getByRole("button", { name: "Start new run" })).toBeTruthy();
  });
});

describe("Assessments run header and agent cards (Story 17.3c)", () => {
  it("shows no header card and Run assessment when there is no run", () => {
    render(<SpecialistAssessmentsHeader run={null} canStart />);
    expect(screen.queryByTestId("run-header")).toBeNull();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
  });

  it("shows the title, status pill, start time, counters and one role-described card per agent", async () => {
    const { container } = render(
      <HeaderAndTasks run={running} canStart />,
    );
    const header = screen.getByTestId("run-header");
    expect(within(header).getByText("Assessments")).toBeTruthy();
    expect(
      header.querySelector("[data-slot='pill'][data-status='running']")
        ?.textContent,
    ).toBe("Assessing");
    expect(
      within(header).getByText("Started 5 Oct 2026, 09:00 UTC"),
    ).toBeTruthy();
    expect(
      within(header)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["1/3 Complete", "1 Running", "1 Queued"]);
    const items = within(
      screen.getByRole("list", { name: "Agent progress" }),
    ).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(
      within(items[0]).getByText(
        "Feasibility, architecture and per-integration effort",
      ),
    ).toBeTruthy();
    expect(
      within(items[1]).getByText(
        "Delivery approach, phases and customer dependencies",
      ),
    ).toBeTruthy();
    expect(
      within(items[2]).getByText("Mandatory controls and the effort they need"),
    ).toBeTruthy();
    expect(items[0].querySelector("[data-slot='card']")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start new run" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("counts Failed and offers Retry and Start new run for a partly failed run", () => {
    render(<HeaderAndTasks run={partial} canStart />);
    expect(
      within(screen.getByTestId("run-header"))
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(["2/3 Complete", "1 Failed"]);
    expect(
      screen.getByRole("button", { name: "Retry Security Agent" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Start new run" })).toBeTruthy();
  });

  it("reads cancelled with no Retry", () => {
    const cancelled = run("cancelled", [
      task("engineering_agent", "succeeded"),
      task("pm_agent", "failed", "model_timeout"),
      task("security_agent", "skipped"),
    ]);
    render(<HeaderAndTasks run={cancelled} canStart />);
    expect(
      screen
        .getByTestId("run-header")
        .querySelector("[data-slot='pill'][data-status='cancelled']")
        ?.textContent,
    ).toBe("Cancelled — completed results kept");
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("shows header and counters but no buttons to a viewer who cannot start", () => {
    render(<HeaderAndTasks run={partial} />);
    expect(screen.getByTestId("run-header")).toBeTruthy();
    expect(
      screen.getByTestId("run-header").querySelector("[data-counter='failed']")
        ?.textContent,
    ).toBe("1 Failed");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("Assessments tab redesign: the I/O matrix", () => {
  const redFinding = {
    id: "00000000-0000-7000-8000-0000000000d2",
    position: 1,
    category: "hidden_dependency" as const,
    severity: "high" as const,
    title: "[RED FINDING]",
    argument: "[RED ARGUMENT]",
    requirements: [
      {
        id: "00000000-0000-7000-8000-0000000000d3",
        version: 1,
        label: "R5",
        excerpt: "",
      },
    ],
    lines: [],
  };
  function red(
    status: "queued" | "running" | "succeeded" | "failed" | null,
    canStart = true,
    withReview = false,
  ): RedTeamView {
    return {
      review: withReview
        ? {
            id: "00000000-0000-7000-8000-0000000000d1",
            version: 1,
            status: "current",
            estimate_version_id: null,
            estimate_version: null,
            dropped_count: 0,
            created_at: "2026-10-05T09:00:00Z",
            counts: { critical: 0, high: 1, medium: 0, low: 0 },
            findings: [redFinding],
          }
        : null,
      run: status
        ? {
            status,
            error_code: status === "failed" ? "model_timeout" : null,
          }
        : null,
      can_start: canStart,
    };
  }
  function renderTab(initial: AssessmentsView, redTeam: RedTeamView) {
    return render(
      <ShellProviders singleKeyShortcuts>
        <FindingSelectionProvider>
          <SpecialistAssessmentsSection
            opportunityId={OPP_ID}
            initial={initial}
            redTeam={redTeam}
          />
        </FindingSelectionProvider>
        <RightPane />
      </ShellProviders>,
    );
  }
  const counters = () =>
    within(screen.getByRole("list", { name: "Task counters" }))
      .getAllByRole("listitem")
      .map((li) => li.textContent);
  const card = (name: string) =>
    within(screen.getByRole("list", { name: "Agent progress" }))
      .getByText(name)
      .closest("li")
      ?.querySelector("[data-slot='card']") as HTMLElement;

  it("No run: no header card, Run assessment and the no-Assessment text", () => {
    renderTab(view(null), red(null));
    expect(screen.queryByTestId("run-header")).toBeNull();
    expect(screen.queryByTestId("run-alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Run assessment" })).toBeTruthy();
    expect(
      screen.getByText(
        "The Engineering, PM and Security Agents assess the Opportunity after its Gaps are detected.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Agent progress" })).toBeNull();
  });

  it("Running: counters cover the Red Team; green, indigo and neutral cards", async () => {
    const { container } = renderTab(
      view(
        run("running", [
          task("engineering_agent", "succeeded"),
          task("pm_agent", "running"),
          task("security_agent", "queued"),
        ]),
      ),
      red("queued"),
    );
    expect(counters()).toEqual(["1/4 Complete", "1 Running", "2 Queued"]);
    expect(screen.getByText("1 running · 2 queued")).toBeTruthy();
    expect(screen.queryByTestId("run-alert")).toBeNull();
    expect(panelRows().map((r) => r[0])).toEqual([
      "Engineering Agent",
      "PM Agent",
      "Security Agent",
      "Red Team",
    ]);
    expect(card("Engineering Agent").className).toContain("border-resolved");
    expect(card("PM Agent").className).toContain("border-primary");
    expect(card("Security Agent").className).not.toMatch(
      /border-(resolved|primary|blocker)/,
    );
    expect(card("Red Team").className).not.toMatch(
      /border-(resolved|primary|blocker)/,
    );
    const bars = Array.from(
      screen.getAllByTestId("state-bar"),
      (b) => `${b.getAttribute("data-state")}:${b.getAttribute("aria-hidden")}`,
    );
    expect(bars).toEqual([
      "succeeded:true",
      "running:true",
      "queued:true",
      "queued:true",
    ]);
    // The state bar shows no percentage.
    expect(container.textContent).not.toMatch(/\d+%/);
    expect(
      (screen.getByRole("button", { name: "Start new run" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Failed: an amber alert, a red card with Retry and a Failed counter", async () => {
    const user = userEvent.setup();
    retryAssessmentTask.mockResolvedValue({ kind: "error" });
    const { container } = renderTab(
      view(
        run("failed", [
          task("engineering_agent", "failed", "model_unavailable"),
          task("pm_agent", "skipped", null, { started_at: null }),
          task("security_agent", "skipped", null, { started_at: null }),
        ]),
      ),
      red(null),
    );
    const alert = screen.getByTestId("run-alert");
    expect(alert.textContent).toBe(
      "The run failedEngineering Agent: the model service couldn't be reached. Completed results are kept.",
    );
    expect(counters()).toEqual(["0/3 Complete", "1 Failed", "2 Skipped"]);
    const failedCard = card("Engineering Agent");
    expect(failedCard.className).toContain("border-blocker");
    expect(failedCard.className).toContain("bg-blocker-tint");
    await user.click(
      screen.getByRole("button", { name: "Retry Engineering Agent" }),
    );
    expect(retryAssessmentTask).toHaveBeenCalledWith(
      OPP_ID,
      RUN_ID,
      "engineering_agent",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Failed Red Team: Retry fires the Red Team retry request", async () => {
    const user = userEvent.setup();
    startRedTeamReview.mockResolvedValue({
      kind: "ok",
      run: { status: "queued", error_code: null },
    });
    renderTab(view(succeeded, FULL), red("failed"));
    expect(counters()).toEqual(["3/4 Complete", "1 Failed"]);
    expect(card("Red Team").className).toContain("border-blocker");
    expect(
      within(card("Red Team")).getByText("the model took too long to answer"),
    ).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Retry Red Team" }));

    expect(startRedTeamReview).toHaveBeenCalledWith(OPP_ID);
    expect(retryAssessmentTask).not.toHaveBeenCalled();
  });

  it("Cancelled: the alert says so; no Retry", () => {
    renderTab(
      view(
        run("cancelled", [
          task("engineering_agent", "succeeded"),
          task("pm_agent", "failed", "model_timeout"),
          task("security_agent", "skipped", null, { started_at: null }),
        ]),
      ),
      red(null),
    );
    expect(screen.getByTestId("run-alert").textContent).toBe(
      "The run was cancelledCompleted results are kept.",
    );
    expect(screen.queryByRole("button", { name: /Retry/ })).toBeNull();
  });

  it("Mixed Findings: one table sorted by severity; a click opens the matching inspector", async () => {
    const user = userEvent.setup();
    renderTab(
      view(succeeded, {
        engineering_agent: assessment("engineering_agent", 1, [
          finding(5, "low"),
        ]),
        security_agent: assessment("security_agent", 1, [
          finding(6, "critical"),
        ]),
      }),
      red("succeeded", false, true),
    );
    expect(findingRows()).toEqual([
      "CriticalRisk[FINDING 6]Security Agent1 Requirement",
      "HighHidden dependency[RED FINDING]Red Team1 Requirement0 Estimate lines",
      "LowRisk[FINDING 5]Engineering Agent1 Requirement",
    ]);
    expect(
      screen.getByRole("article", { name: "Red Team" }).textContent,
    ).toContain("1 Finding");

    await user.click(screen.getByRole("button", { name: /\[RED FINDING\]/ }));
    expect(within(pane()).getByText("[RED ARGUMENT]")).toBeTruthy();

    await user.click(row(6));
    expect(within(pane()).getByText("[DETAIL 6]")).toBeTruthy();
    expect(within(pane()).queryByText("[RED ARGUMENT]")).toBeNull();
    expect(
      screen
        .getByRole("button", { name: /\[RED FINDING\]/ })
        .closest("[role=row]")
        ?.getAttribute("aria-selected"),
    ).toBe("false");
  });

  it.each([
    ["a specialist row", /\[FINDING 6\]/, "[FINDING 6]", /\[FINDING 5\]/],
    ["a Red Team row", /\[RED FINDING\]/, "[RED FINDING]", /\[FINDING 5\]/],
  ])(
    "closing the pane after a keyboard open returns focus to the row; not after a click (%s)",
    async (_name, keyboardRow, heading, clickRow) => {
      const user = userEvent.setup();
      renderTab(
        view(
          succeeded,
          {
            engineering_agent: assessment("engineering_agent", 1, [
              finding(5, "low"),
            ]),
            security_agent: assessment("security_agent", 1, [
              finding(6, "critical"),
            ]),
          },
          false,
        ),
        red("succeeded", false, true),
      );
      const button = () => screen.getByRole("button", { name: keyboardRow });

      act(() => button().focus());
      await user.keyboard("{Enter}");
      await waitFor(() =>
        expect(document.activeElement).toBe(
          within(pane()).getByRole("heading", { level: 3, name: heading }),
        ),
      );
      await user.click(
        within(pane()).getByRole("button", { name: "Close right pane" }),
      );
      await waitFor(() => expect(document.activeElement).toBe(button()));

      // A mouse open: closing leaves focus where the click put it, not on the row.
      await user.click(screen.getByRole("button", { name: clickRow }));
      await waitFor(() => expect(pane()).toBeTruthy());
      await user.click(
        within(pane()).getByRole("button", { name: "Close right pane" }),
      );
      await waitFor(() =>
        expect(
          screen.queryByRole("heading", { level: 3, name: "[FINDING 5]" }),
        ).toBeNull(),
      );
      expect(document.activeElement).not.toBe(
        screen.getByRole("button", { name: clickRow }),
      );
      expect(document.activeElement).not.toBe(button());
    },
  );

  it("No Findings: says so under the heading", () => {
    renderTab(
      view(succeeded, {
        pm_agent: assessment("pm_agent", 1, [], {
          counts: { critical: 0, high: 0, medium: 0, low: 0 },
        }),
      }),
      red(null),
    );
    const heading = screen.getByRole("heading", { level: 3, name: "Findings" });
    expect(
      within(heading.closest("section") as HTMLElement).getByText(
        "No Findings.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("grid", { name: "Findings" })).toBeNull();
  });

  it("Viewer: no start, cancel or Retry", () => {
    const { unmount } = renderTab(view(null, {}, false), red(null, false));
    expect(screen.queryByRole("button")).toBeNull();
    unmount();
    renderTab(
      view(
        run("partially_failed", [
          task("engineering_agent", "succeeded"),
          task("pm_agent", "running"),
          task("security_agent", "failed", "model_timeout"),
        ]),
        {},
        false,
      ),
      red("failed", false),
    );
    expect(screen.getByTestId("run-header")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
