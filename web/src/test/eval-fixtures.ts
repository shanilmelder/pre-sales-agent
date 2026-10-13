import type { EvalBar, EvalResult } from "@/lib/evals";

const BARS: Omit<EvalBar, "value" | "status" | "delta" | "regressed">[] = [
  {
    metric: "extraction_recall",
    label: "Extraction recall",
    requirement: "FR-5",
    agent_ids: ["intake_agent"],
    comparator: "min",
    threshold: 90,
  },
  {
    metric: "gap_recall",
    label: "Gap recall",
    requirement: "FR-11",
    agent_ids: ["clarification_agent"],
    comparator: "min",
    threshold: 80,
  },
  {
    metric: "irrelevant_gaps",
    label: "Irrelevant Gaps",
    requirement: "FR-11",
    agent_ids: ["clarification_agent"],
    comparator: "max",
    threshold: 20,
  },
  {
    metric: "evidence_support",
    label: "Evidence support",
    requirement: "FR-25",
    agent_ids: ["engineering_agent", "red_team_agent"],
    comparator: "min",
    threshold: 95,
  },
];

/** A stored eval result. `values` sets bar values by metric (missing: not measured). */
export function evalResult(
  n: number,
  values: Partial<Record<EvalBar["metric"], number>> = {},
  overrides: Partial<EvalResult> = {},
): EvalResult {
  const bars: EvalBar[] = BARS.map((bar) => {
    const value = values[bar.metric] ?? null;
    const ok =
      value === null ? null : bar.comparator === "min" ? value >= bar.threshold : value <= bar.threshold;
    return {
      ...bar,
      value,
      status: ok === null ? "not_measured" : ok ? "pass" : "fail",
      delta: null,
      regressed: false,
    };
  });
  const passed = bars.every((b) => b.status !== "fail");
  return {
    id: `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    reference_set_version: "b5f4499df5a5",
    config_version_ids: { intake_agent: "11111111-1111-5111-8111-111111111111" },
    model_digests: { intake_agent: ["sha256:abc"] },
    prompt_versions: { intake_agent: 1 },
    scores: {
      overall: { ...values },
      per_agent: {
        intake_agent: { extraction_recall: values.extraction_recall ?? null },
        clarification_agent: {
          gap_recall: values.gap_recall ?? null,
          irrelevant_gaps: values.irrelevant_gaps ?? null,
        },
        engineering_agent: { evidence_support: null },
        red_team_agent: { evidence_support: values.evidence_support ?? null },
      },
    },
    bars,
    failures: [],
    opportunity_count: 10,
    draft_count: 10,
    pending_count: 4,
    tokens: 123456,
    gpu_seconds: 812.4,
    cost: { amount_minor: 1234, currency: "EUR" },
    passed,
    accepted: passed,
    created_by: "eval_harness",
    created_at: `2026-10-${String(10 + n).padStart(2, "0")}T09:00:00Z`,
    ...overrides,
  };
}
