import type { components } from "@/lib/api/client";
import { signedHours } from "@/lib/effort-comparison";

export type EvalResult = components["schemas"]["EvalResult"];
export type EvalBar = components["schemas"]["EvalBar"];
export type BarStatus = EvalBar["status"];

export const EMPTY_STATE = "No evaluation results yet. Run `make eval` to create the first one.";
export const NO_PREVIOUS = "This is the first result: there is nothing to compare it with.";

const STATUS_LABELS: Record<BarStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  not_measured: "Not measured",
};

export function statusLabel(status: BarStatus): string {
  return STATUS_LABELS[status];
}

/** A percentage to 0.1 ("91.0%"), or "—" when nothing was measured. */
export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(1)}%`;
}

/** "≥ 90%" or "≤ 20%". */
export function thresholdLabel(bar: Pick<EvalBar, "comparator" | "threshold">): string {
  return `${bar.comparator === "min" ? "≥" : "≤"} ${bar.threshold}%`;
}

/** A signed change in points with a real minus sign ("+1.5", "−7.0", "0.0"), "—" for none. */
export function signedPoints(value: number | null | undefined): string {
  return signedHours(value ?? null);
}

/** `intake_agent` → "Intake Agent", `red_team_agent` → "Red Team Agent", `pm_agent` → "PM Agent". */
export function agentName(agentId: string): string {
  return agentId
    .split("_")
    .map((word) => (word === "pm" ? "PM" : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(" ");
}

/** `value` against the bar's threshold; `not_measured` when there is none. */
export function meets(
  bar: Pick<EvalBar, "comparator" | "threshold">,
  value: number | null | undefined,
): BarStatus {
  if (value === null || value === undefined) return "not_measured";
  const ok = bar.comparator === "min" ? value >= bar.threshold : value <= bar.threshold;
  return ok ? "pass" : "fail";
}

export interface AgentBarRow {
  agentId: string;
  bar: EvalBar;
  value: number | null;
  status: BarStatus;
}

/** Each Agent's value for each bar it owns, judged against the bar's threshold, by agent. */
export function agentRows(result: EvalResult): AgentBarRow[] {
  const rows: AgentBarRow[] = [];
  for (const bar of result.bars) {
    for (const agentId of bar.agent_ids) {
      const value = result.scores.per_agent[agentId]?.[bar.metric] ?? null;
      rows.push({ agentId, bar, value, status: meets(bar, value) });
    }
  }
  return rows.sort((a, b) => a.agentId.localeCompare(b.agentId));
}

export interface DiffRow {
  metric: string;
  label: string;
  previous: number | null;
  current: number | null;
  delta: number | null;
  changed: boolean;
}

/** The bars' values against the previous result's (whatever its outcome). */
export function diffRows(current: EvalResult, previous: EvalResult): DiffRow[] {
  return current.bars.map((bar) => {
    const before = previous.bars.find((b) => b.metric === bar.metric)?.value ?? null;
    const now = bar.value ?? null;
    const delta = before === null || now === null ? null : Math.round((now - before) * 10) / 10;
    return {
      metric: bar.metric,
      label: bar.label,
      previous: before,
      current: now,
      delta,
      changed: before !== now,
    };
  });
}

/** Minor units as a decimal amount with its currency ("12.34 EUR", "1234 JPY"), scaled by
 * the currency's own number of fraction digits. */
export function formatCost(cost: EvalResult["cost"]): string {
  let digits = 2;
  try {
    digits = new Intl.NumberFormat("en-GB", { style: "currency", currency: cost.currency })
      .resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    // An unknown code: keep two digits.
  }
  return `${(cost.amount_minor / 10 ** digits).toFixed(digits)} ${cost.currency}`;
}

/** "2026-10-13 14:05 UTC". */
export function formatWhen(iso: string): string {
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

/** "1 Opportunity", "3 Opportunities". */
function opportunities(count: number): string {
  return `${count} ${count === 1 ? "Opportunity" : "Opportunities"}`;
}

/** "Run 2026-10-13 21:37 UTC · reference set 6fe2d288d456 · 1 Opportunity · 68 evidence pairs
 * pending review". The reference set version is cut to its first 12 characters. */
export function runSummary(result: EvalResult): string {
  const pairs = result.pending_count === 1 ? "pair" : "pairs";
  return [
    `Run ${formatWhen(result.created_at)}`,
    `reference set ${result.reference_set_version.slice(0, 12)}`,
    opportunities(result.opportunity_count),
    `${result.pending_count.toLocaleString("en-GB")} evidence ${pairs} pending review`,
  ].join(" · ");
}
