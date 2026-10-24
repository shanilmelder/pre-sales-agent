import { describe, expect, it } from "vitest";

import {
  agentLabel,
  agentRole,
  START_NEW_RUN,
  runStatusTone,
  taskCounters,
  activitySummary,
  evidenceLabels,
  findingKey,
  mergeFindings,
  RED_TEAM_ROLE,
  runAlert,
  severitySummary,
  severityTotals,
  assessmentLabel,
  confidenceLabel,
  formatElapsed,
  isAssessing,
  kindLabel,
  recommendationInfo,
  runStatusLabel,
  skipNote,
  taskElapsed,
  taskStatusLabel,
  decisionSentence,
  isWaiting,
  openDecision,
  planLabel,
  planTaskLabel,
  RUN_STATUS_LABELS,
} from "@/lib/assessments";

describe("assessment labels", () => {
  it("names agents by role", () => {
    expect(agentLabel("engineering_agent")).toBe("Engineering Agent");
    expect(agentLabel("pm_agent")).toBe("PM Agent");
    expect(agentLabel("security_agent")).toBe("Security Agent");
    expect(assessmentLabel({ agent: "pm_agent", version: 2 })).toBe(
      "PM Agent v2",
    );
  });

  it("gives every recommendation an icon, a label and a tone", () => {
    expect(recommendationInfo("proceed")).toMatchObject({
      label: "Proceed",
      tone: "text-resolved",
    });
    expect(recommendationInfo("proceed_with_conditions")).toMatchObject({
      label: "Proceed with conditions",
      tone: "text-gap",
    });
    expect(recommendationInfo("do_not_proceed")).toMatchObject({
      label: "Do not proceed",
      tone: "text-blocker",
    });
  });

  it("words confidence and kinds", () => {
    expect(confidenceLabel("low")).toBe("Low confidence");
    expect(kindLabel("dependency")).toBe("Dependency");
  });

  it("labels task statuses for the pill", () => {
    expect(taskStatusLabel("queued")).toBe("Queued");
    expect(taskStatusLabel("running")).toBe("Running");
    expect(taskStatusLabel("succeeded")).toBe("Done");
    expect(taskStatusLabel("failed")).toBe("Failed");
    expect(taskStatusLabel("skipped")).toBe("Skipped");
  });

  it("is assessing only while queued or running", () => {
    const run = (
      status:
        | "queued"
        | "running"
        | "succeeded"
        | "partially_failed"
        | "failed"
        | "cancelled",
    ) => ({
      id: "x",
      status,
      created_at: "2026-10-05T09:00:00Z",
      queued_at: "2026-10-05T09:00:00Z",
      finished_at: null,
      tasks: [],
      plan_version: 1,
      decisions: [],
      plan_versions: [],
    });
    expect(isAssessing(run("queued"))).toBe(true);
    expect(isAssessing(run("running"))).toBe(true);
    expect(isAssessing(run("partially_failed"))).toBe(false);
    expect(isAssessing(run("cancelled"))).toBe(false);
    expect(isAssessing(null)).toBe(false);
    expect(runStatusLabel(run("cancelled"))).toBe(
      "Cancelled — completed results kept",
    );
  });
});

describe("elapsed time", () => {
  const START = "2026-10-05T09:00:00Z";
  const at = (seconds: number) => Date.parse(START) + seconds * 1000;

  it("formats m:ss in whole seconds", () => {
    expect(formatElapsed(0)).toBe("0:00");
    expect(formatElapsed(999)).toBe("0:00");
    expect(formatElapsed(65_000)).toBe("1:05");
    expect(formatElapsed(130_000)).toBe("2:10");
    expect(formatElapsed(75 * 60_000 + 9_000)).toBe("75:09");
    expect(formatElapsed(-5_000)).toBe("0:00"); // a browser clock behind the server's
  });

  it("ticks while running, from started_at to now", () => {
    const task = {
      status: "running",
      started_at: START,
      finished_at: null,
    } as const;
    expect(taskElapsed(task, at(65))).toBe("1:05");
    expect(taskElapsed(task, at(66))).toBe("1:06");
  });

  it("keeps the final duration once done, failed or skipped", () => {
    const finished = "2026-10-05T09:02:10Z";
    for (const status of ["succeeded", "failed", "skipped"] as const) {
      expect(
        taskElapsed(
          { status, started_at: START, finished_at: finished },
          at(999),
        ),
      ).toBe("2:10");
    }
  });

  it("ignores a leftover finish time on a queued or running task", () => {
    const leftover = "2026-10-05T09:00:30Z";
    expect(
      taskElapsed(
        { status: "queued", started_at: START, finished_at: leftover },
        at(65),
      ),
    ).toBe("");
    expect(
      taskElapsed(
        { status: "running", started_at: START, finished_at: leftover },
        at(65),
      ),
    ).toBe("1:05");
  });

  it("is blank before starting or when a failed task has no finish time", () => {
    expect(
      taskElapsed(
        { status: "queued", started_at: null, finished_at: null },
        at(5),
      ),
    ).toBe("");
    expect(
      taskElapsed(
        { status: "failed", started_at: START, finished_at: null },
        at(5),
      ),
    ).toBe("");
    expect(
      taskElapsed(
        { status: "failed", started_at: null, finished_at: null },
        at(5),
      ),
    ).toBe("");
  });

  it("is blank for a task skipped before it started", () => {
    expect(
      taskElapsed(
        { status: "skipped", started_at: null, finished_at: null },
        at(5),
      ),
    ).toBe("");
  });
});

describe("skipNote (Story 7.1)", () => {
  it("explains a task skipped because its Agent is disabled, and nothing else", () => {
    expect(skipNote({ status: "skipped", skip_reason: "agent_disabled" })).toBe(
      "Agent disabled — assess manually",
    );
    expect(skipNote({ status: "skipped", skip_reason: null })).toBeNull(); // a cancel's
    expect(skipNote({ status: "skipped" })).toBeNull();
    expect(skipNote({ status: "failed", skip_reason: null })).toBeNull();
  });
});

describe("run header helpers (Story 17.3c)", () => {
  it("describes each agent's role", () => {
    expect(agentRole("security_agent")).toBe(
      "Mandatory controls and the effort they need",
    );
    expect(agentRole("pm_agent")).toContain("Delivery approach");
    expect(agentRole("engineering_agent")).toContain("Feasibility");
  });

  it("counts tasks, showing only non-zero states after Complete", () => {
    expect(taskCounters(["succeeded", "running", "queued", "queued"])).toEqual([
      { key: "complete", value: "1/4", label: "Complete" },
      { key: "running", value: "1", label: "Running" },
      { key: "queued", value: "2", label: "Queued" },
    ]);
    expect(
      taskCounters(["failed", "skipped", "skipped", "running"]).map(
        (c) => `${c.value} ${c.label}`,
      ),
    ).toEqual(["0/4 Complete", "1 Failed", "1 Running", "2 Skipped"]);
    expect(taskCounters([])).toEqual([
      { key: "complete", value: "0/0", label: "Complete" },
    ]);
  });

  it("summarises the active tasks", () => {
    expect(activitySummary(["running", "queued", "queued", "succeeded"])).toBe(
      "1 running · 2 queued",
    );
    expect(activitySummary(["queued"])).toBe("1 queued");
    expect(activitySummary(["succeeded", "failed"])).toBe("");
  });

  it("describes the Red Team's role", () => {
    expect(RED_TEAM_ROLE).toBe(
      "Argues integrations are harder and Requirements incomplete",
    );
  });

  it("labels the restart button", () => {
    expect(START_NEW_RUN).toBe("Start new run");
  });
});

describe("runStatusTone", () => {
  it("maps each run status to its tone", () => {
    expect(runStatusTone("succeeded")).toBe("text-resolved");
    expect(runStatusTone("running")).toBe("text-agent");
    expect(runStatusTone("partially_failed")).toBe("text-gap");
    expect(runStatusTone("failed")).toBe("text-blocker");
    expect(runStatusTone("queued")).toBe("text-muted-foreground");
    expect(runStatusTone("cancelled")).toBe("text-muted-foreground");
  });
});

describe("runAlert", () => {
  const task = (agent: string, status: string, error_code: string | null = null) =>
    ({ agent, status, error_code }) as never;

  it("says why a failed or partly failed run stopped and that results are kept", () => {
    expect(
      runAlert({
        status: "partially_failed",
        tasks: [
          task("engineering_agent", "succeeded"),
          task("security_agent", "failed", "model_timeout"),
        ],
      }),
    ).toEqual({
      title: "The run partly failed",
      detail:
        "Security Agent: the model took too long to answer. Completed results are kept.",
    });
    expect(
      runAlert({ status: "failed", tasks: [task("pm_agent", "failed")] })
        ?.title,
    ).toBe("The run failed");
  });

  it("says a cancelled run was cancelled", () => {
    expect(runAlert({ status: "cancelled", tasks: [] })).toEqual({
      title: "The run was cancelled",
      detail: "Completed results are kept.",
    });
  });

  it("has nothing to say for a run in progress or done", () => {
    for (const status of ["queued", "running", "succeeded"] as const) {
      expect(runAlert({ status, tasks: [] })).toBeNull();
    }
  });
});

describe("merged Findings", () => {
  const req = (id: string, label: string) => ({ id, version: 1, label, excerpt: "" });
  const specialist = (id: string, severity: string, requirements = [req("r1", "R1")]) =>
    ({ id, position: 1, kind: "risk", severity, title: id, detail: "", requirements }) as never;
  const red = (id: string, severity: string) =>
    ({
      id,
      position: 1,
      category: "integration_harder",
      severity,
      title: id,
      argument: "",
      requirements: [req("r2", "R2"), req("r3", "R3")],
      lines: [{ id: "l1" }],
    }) as never;
  const slot = (agent: string, findings: unknown[] | null) =>
    ({
      agent,
      assessment: findings === null ? null : { findings },
    }) as never;

  it("ranks every source's Findings critical to low, stable within a severity", () => {
    const rows = mergeFindings(
      [
        slot("engineering_agent", [specialist("e1", "high"), specialist("e2", "low")]),
        slot("pm_agent", null),
        slot("security_agent", [specialist("s1", "critical")]),
      ],
      { findings: [red("t1", "high"), red("t2", "medium")] },
    );
    expect(rows.map((r) => r.id)).toEqual(["s1", "e1", "t1", "t2", "e2"]);
    const redRow = rows.find((r) => r.id === "t1")!;
    expect(redRow).toMatchObject({
      source: "red-team",
      type: "Integration harder",
      raisedBy: "Red Team",
      requirements: 2,
      lines: 1,
    });
    expect(rows[0]).toMatchObject({
      source: "specialist",
      agent: "security_agent",
      type: "Risk",
      raisedBy: "Security Agent",
      requirements: 1,
      lines: null,
    });
    expect(findingKey(redRow)).toBe("red-team:t1");
    expect(findingKey(rows[0])).toBe("security_agent:s1");
    expect(severitySummary(severityTotals(rows))).toBe(
      "1 Critical · 2 High · 1 Medium · 1 Low",
    );
  });

  it("works without a Red Team review", () => {
    expect(mergeFindings([slot("pm_agent", [])], null)).toEqual([]);
  });

  it("folds in the Critic's Findings, raised by Critic, after the Red Team's (Story 6.4)", () => {
    const critic = (id: string, severity: string, category = "timeline") =>
      ({
        id,
        position: 1,
        category,
        severity,
        title: id,
        argument: "",
        requirements: [req("r4", "R4")],
        findings: [{ id: "f1" }, { id: "f2" }],
      }) as never;
    const rows = mergeFindings(
      [slot("engineering_agent", [specialist("e1", "high")])],
      { findings: [red("t1", "high")] },
      { findings: [critic("c1", "critical"), critic("c2", "high", "coverage")] },
    );
    expect(rows.map((r) => r.id)).toEqual(["c1", "e1", "t1", "c2"]);
    expect(rows[0]).toMatchObject({
      source: "critic",
      type: "Timeline",
      raisedBy: "Critic",
      requirements: 1,
      lines: null,
      cited: 2,
    });
    expect(rows[3].type).toBe("Coverage");
    expect(findingKey(rows[0])).toBe("critic:c1");
    expect(agentLabel("critic_agent")).toBe("Critic");
    expect(agentRole("critic_agent")).toContain("coverage");
  });

  it("lists up to three distinct Requirement labels, Findings first", () => {
    expect(
      evidenceLabels(
        [{ requirements: [req("a", "R1"), req("a", "R1")] }, { requirements: [req("b", "R2")] }],
        [{ requirement: req("c", "R3") }, { requirement: req("d", "R4") }],
      ).map((r) => r.label),
    ).toEqual(["R1", "R2", "R3"]);
  });
});

describe("waiting for a person (Story 5.5)", () => {
  it("names the decision and the plan, and reads waiting as amber and not assessing", () => {
    expect(
      decisionSentence({ agent: "security_agent", agent_name: "Security Agent" }),
    ).toBe("Security assessment not planned: Security Agent is disabled");
    expect(decisionSentence({ agent: "pm_agent", agent_name: "" })).toBe(
      "PM assessment not planned: PM Agent is disabled",
    );
    expect(planLabel(2)).toBe("Plan v2");
    expect(
      planTaskLabel({
        agent: "engineering_agent",
        config_version_id: "x",
        config_version: 3,
        semver: "0.2.0",
      }),
    ).toBe("Engineering Agent 0.2.0 (config v3)");
    expect(
      planTaskLabel({ agent: "pm_agent", config_version_id: "x", config_version: null, semver: null }),
    ).toBe("PM Agent");
    expect(runStatusTone("waiting_for_human")).toBe("text-gap");
    expect(RUN_STATUS_LABELS.waiting_for_human).toBe("Waiting for you");
    const waiting = {
      id: "x",
      status: "waiting_for_human" as const,
      created_at: "2026-10-05T09:00:00Z",
      queued_at: "2026-10-05T09:00:00Z",
      finished_at: null,
      tasks: [],
      plan_version: 1,
      plan_versions: [],
      decisions: [
        {
          id: "d",
          kind: "plan_escalation" as const,
          agent: "security_agent" as const,
          agent_name: "Security Agent",
          agent_active: false,
          status: "open" as const,
          choice: null,
          row_version: 1,
          created_at: "2026-10-05T09:00:00Z",
          resolved_by: null,
          resolved_at: null,
        },
      ],
    };
    expect(isAssessing(waiting)).toBe(false);
    expect(isWaiting(waiting)).toBe(true);
    expect(openDecision(waiting, "security_agent")?.id).toBe("d");
    expect(openDecision(waiting, "pm_agent")).toBeNull();
    expect(openDecision({ ...waiting, status: "queued" }, "security_agent")).toBeNull();
  });
});
