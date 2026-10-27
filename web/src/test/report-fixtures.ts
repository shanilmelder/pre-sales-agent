// Story 10.3: Estimate vs actual report fixtures in the API's shape.
import type {
  EstimateVsActualReport,
  GroupOpportunity,
  ReportVariance,
  VarianceGroup,
} from "@/lib/reports";

export function variance(percent: number | null, hours = 0): ReportVariance {
  const tone = percent === null ? "neutral" : percent > 10 ? "over" : percent < -5 ? "under" : "neutral";
  const direction = hours > 0 ? "over" : hours < 0 ? "under" : "on";
  const display = percent === null ? `${hours > 0 ? "+" : ""}${hours} h` : `${percent > 0 ? "+" : ""}${percent}%`;
  const width = percent === null ? 0 : Math.min(50, Math.abs(percent) * 0.6);
  return {
    hours,
    percent,
    direction,
    display,
    sr_label: direction === "on" ? "on estimate" : direction,
    tone,
    bar_left: percent !== null && percent < 0 ? 50 - width : 50,
    bar_width: width,
  };
}

export const ALPHA_ID = "0190a000-0000-7000-8000-000000000001";
export const BRAVO_ID = "0190a000-0000-7000-8000-000000000002";

export function opportunity(overrides: Partial<GroupOpportunity> = {}): GroupOpportunity {
  return {
    opportunity_id: ALPHA_ID,
    title: "Acme payments",
    estimate_version_id: "0190b000-0000-7000-8000-000000000001",
    estimate_version: 3,
    is_baseline: true,
    estimate_hours: 100,
    actual_hours: 120,
    variance: variance(20, 20),
    main_cause: { value: "integration_complexity", label: "Integration complexity" },
    failed_assumptions: 1,
    ...overrides,
  };
}

export function group(overrides: Partial<VarianceGroup> = {}): VarianceGroup {
  return {
    key: "rest_api",
    label: "REST API",
    opportunity_count: 1,
    estimate_hours: 100,
    actual_hours: 120,
    variance: variance(20, 20),
    main_cause: { value: "integration_complexity", label: "Integration complexity" },
    failed_assumptions: 1,
    opportunities: [opportunity()],
    ...overrides,
  };
}

/** Two groups: REST API +20 % (one Opportunity, v3, the Baseline) and SFTP −10 %. */
export function report(overrides: Partial<EstimateVsActualReport> = {}): EstimateVsActualReport {
  return {
    group_by: "integration_type",
    filters: {
      product: null,
      work_package_id: null,
      cause: null,
      closed_from: null,
      closed_to: null,
      include_milestones: false,
    },
    has_actuals: true,
    kpis: {
      closed_opportunities: 2,
      opportunities: 2,
      estimate_hours: 300,
      actual_hours: 300,
      variance: variance(0, 0),
      failed_assumptions: 3,
      failed_by_kind: [
        { kind: "condition", label: "Conditions", count: 2 },
        { kind: "contingency", label: "Contingencies", count: 1 },
      ],
    },
    groups: [
      group(),
      group({
        key: "sftp",
        label: "SFTP",
        estimate_hours: 200,
        actual_hours: 180,
        variance: variance(-10, -20),
        main_cause: null,
        failed_assumptions: 2,
        opportunities: [
          opportunity({
            opportunity_id: BRAVO_ID,
            title: "Bravo logistics",
            estimate_version_id: "0190b000-0000-7000-8000-000000000002",
            estimate_version: 1,
            is_baseline: false,
            estimate_hours: 200,
            actual_hours: 180,
            variance: variance(-10, -20),
            main_cause: null,
            failed_assumptions: 2,
          }),
        ],
      }),
    ],
    calibration: {
      threshold: 5,
      message:
        "Suggestions need at least 5 closed Opportunities per Integration Type. 0 of 2 types has that many.",
    },
    options: {
      products: ["Payments", "Logistics"],
      work_packages: [{ id: "0190c000-0000-7000-8000-000000000001", name: "Discovery" }],
      causes: [
        { value: "integration_complexity", label: "Integration complexity" },
        { value: "scope_change", label: "Scope change" },
      ],
    },
    ...overrides,
  };
}
