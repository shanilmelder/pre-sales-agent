import { describe, expect, it } from "vitest";

import {
  agentLabel,
  assessmentLabel,
  confidenceLabel,
  isAssessing,
  kindLabel,
  recommendationInfo,
  taskLine,
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

  it("says what each agent is doing", () => {
    expect(
      taskLine({
        agent: "engineering_agent",
        status: "running",
        error_code: null,
      }),
    ).toBe("Engineering Agent — Assessing…");
    expect(
      taskLine({ agent: "pm_agent", status: "succeeded", error_code: null }),
    ).toBe("PM Agent — Done");
    expect(
      taskLine({
        agent: "security_agent",
        status: "failed",
        error_code: "output_invalid",
      }),
    ).toBe("Security Agent — Failed: the model's answer couldn't be used");
  });

  it("is assessing only while queued or running", () => {
    const run = (
      status:
        "queued" | "running" | "succeeded" | "partially_failed" | "failed",
    ) => ({
      id: "x",
      status,
      created_at: "2026-10-05T09:00:00Z",
      tasks: [],
    });
    expect(isAssessing(run("queued"))).toBe(true);
    expect(isAssessing(run("running"))).toBe(true);
    expect(isAssessing(run("partially_failed"))).toBe(false);
    expect(isAssessing(null)).toBe(false);
  });
});
