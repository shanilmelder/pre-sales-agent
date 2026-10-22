import { describe, expect, it } from "vitest";

import {
  agentLabel,
  agentRole,
  START_NEW_RUN,
  runStatusTone,
  taskCounters,
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
    const t = (status: string) => ({ status }) as never;
    expect(
      taskCounters({ tasks: [t("succeeded"), t("running"), t("queued")] }),
    ).toEqual([
      { key: "complete", label: "1/3 Complete" },
      { key: "running", label: "1 Running" },
      { key: "queued", label: "1 Queued" },
    ]);
    expect(
      taskCounters({ tasks: [t("failed"), t("skipped"), t("skipped")] }).map(
        (c) => c.label,
      ),
    ).toEqual(["0/3 Complete", "1 Failed", "2 Skipped"]);
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
