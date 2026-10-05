// Effort comparison (Story 5.3, demo slice): the specialist agents' hours per active
// Requirement next to the Estimate's hours for it. Display arithmetic only: it never changes
// the Estimate, whose own totals stay server-calculated. Safe on server and client.
import {
  AGENTS,
  agentLabel,
  type AgentAssessment,
  type AssessmentAgent,
} from "@/lib/assessments";
import type { EstimateVersion } from "@/lib/estimates";
import type { Requirement } from "@/lib/requirements";

/** The section heading. */
export const EFFORT_COMPARISON = "Effort comparison";

/** The header note. */
export const ADDS_UP_NOTE =
  "Engineering, PM and Security size different work, so their hours add up.";

/** The note under the Estimate (allocated) column. */
export const SHARED_LINE_NOTE =
  "A line covering several Requirements is shared equally between them.";

/** The empty-state sentence. */
export const NO_EFFORT_TO_COMPARE = "No effort to compare yet.";

/** Shown when the Estimate read failed (the table renders without its columns). */
export const ESTIMATE_NOT_LOADED =
  "The Estimate could not be loaded, so its hours are not shown.";

/** Shown when the Requirements or Assessments read failed. */
export const COMPARISON_NOT_LOADED =
  "The Effort comparison could not be loaded. Try again in a moment.";

export const ESTIMATE_ALLOCATED = "Estimate (allocated)";
export const AGENTS_TOTAL = "Agents total";
export const DIFFERENCE = "Difference";
export const NOT_LINKED = "Not linked to a Requirement";

/** "Estimate v2. A line covering several Requirements is shared equally between them." */
export function estimateColumnNote(version: number | null): string {
  return version === null ? SHARED_LINE_NOTE : `Estimate v${version}. ${SHARED_LINE_NOTE}`;
}

/** "Estimate effort: 42.0 h in total (12.0 h not linked to a Requirement)". */
export function estimateTotalNote(total: number, unlinked: number): string {
  return `Estimate effort: ${total.toFixed(1)} h in total (${unlinked.toFixed(1)} h not linked to a Requirement)`;
}

/** "1 effort row for Requirements no longer active is not shown", "3 effort rows … are …". */
export function leftOutNote(n: number): string {
  return n === 1
    ? "1 effort row for Requirements no longer active is not shown"
    : `${n} effort rows for Requirements no longer active are not shown`;
}

/** An agent's column heading: "Engineering", "PM", "Security". */
export function agentColumn(agent: AssessmentAgent): string {
  return agentLabel(agent).replace(/ Agent$/, "");
}

/** Hours to 0.1 for display, or "—" when there are none. */
export function comparisonHours(value: number | null): string {
  return value === null ? "—" : value.toFixed(1);
}

/** A signed difference to 0.1 ("+4.0", "−4.0", "0.0"), or "—" when there is none. */
export function signedHours(value: number | null): string {
  if (value === null) return "—";
  if (value === 0) return "0.0";
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}`;
}

const EXCERPT_MAX = 140;

/** At most `limit` code points of `text` on one line, cut at whitespace where possible,
 * ending in `…` when cut (as the server cuts its Requirement excerpts). */
export function excerpt(text: string, limit = EXCERPT_MAX): string {
  const points = Array.from(text.split(/\s+/).filter(Boolean).join(" "));
  if (points.length <= limit) return points.join("");
  let cut = points.slice(0, limit - 1);
  const space = cut.lastIndexOf(" ");
  if (space >= Math.floor(limit / 2)) cut = cut.slice(0, space);
  return `${cut.join("").trimEnd()}…`;
}

/** Hours rounded to a tenth (never −0). */
function tenth(value: number): number {
  const rounded = Math.round(value * 10) / 10;
  return rounded === 0 ? 0 : rounded;
}

function add(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return a + b;
}

type AgentHours = Record<AssessmentAgent, number | null>;

export type ComparisonValues = {
  /** Each agent's hours ("—" when it has none). */
  agents: AgentHours;
  /** The sum of the agents' hours (null when none of them has any). */
  agentsTotal: number | null;
  /** The Estimate's hours allocated to it (0 when no line covers it; null when there is no
   * Estimate). */
  estimate: number | null;
  /** Estimate − Agents total from the shown (rounded) hours, only when both exist. */
  difference: number | null;
};

export type ComparisonRow = ComparisonValues & {
  id: string;
  label: string;
  excerpt: string;
};

export type EffortComparison = {
  /** One per active Requirement, in Requirement order. */
  rows: ComparisonRow[];
  totals: ComparisonValues;
  /** Estimate hours on lines covering no active Requirement (null without an Estimate). */
  unlinkedHours: number | null;
  /** Agent effort rows citing Requirements no longer active (left out). */
  leftOut: number;
  /** True when an Estimate version exists. */
  hasEstimate: boolean;
  /** The compared Estimate version's number (null without an Estimate). */
  estimateVersion: number | null;
  /** The Estimate's effort hours in total: allocated + not linked (null without one). */
  estimateEffortTotal: number | null;
  /** True when no agent has effort for an active Requirement and there is no Estimate. */
  empty: boolean;
};

function values(agents: AgentHours, estimate: number | null): ComparisonValues {
  const rounded = Object.fromEntries(
    Object.entries(agents).map(([k, v]) => [k, v === null ? null : tenth(v)]),
  ) as AgentHours;
  const sum = Object.values(agents).reduce<number | null>(add, null);
  const agentsTotal = sum === null ? null : tenth(sum);
  const shownEstimate = estimate === null ? null : tenth(estimate);
  return {
    agents: rounded,
    agentsTotal,
    estimate: shownEstimate,
    // From the shown values, so the Difference always equals what's on screen.
    difference:
      agentsTotal === null || shownEstimate === null ? null : tenth(shownEstimate - agentsTotal),
  };
}

function noHours(): AgentHours {
  return Object.fromEntries(AGENTS.map((a) => [a.value, null])) as AgentHours;
}

/** The comparison of the agents' current effort per active Requirement with the Estimate's
 * hours, each Estimate line's effort split equally among the active Requirements it covers.
 * `estimate` is the current Estimate version (null when there is none). */
export function compareEffort({
  requirements,
  assessments,
  estimate,
}: {
  requirements: readonly Pick<Requirement, "id" | "text">[];
  assessments: readonly AgentAssessment[];
  estimate: EstimateVersion | null;
}): EffortComparison {
  const active = new Set(requirements.map((r) => r.id));

  // The agents' hours per active Requirement.
  const agentHours = new Map<string, AgentHours>();
  for (const r of requirements) agentHours.set(r.id, noHours());
  let leftOut = 0;
  const known = new Set<string>(AGENTS.map((a) => a.value));
  for (const slot of assessments) {
    // An agent this build doesn't know has no column, so its hours are not added in.
    if (!known.has(slot.agent)) continue;
    for (const row of slot.assessment?.effort ?? []) {
      const byAgent = agentHours.get(row.requirement.id);
      if (!byAgent) {
        leftOut += 1;
        continue;
      }
      byAgent[slot.agent] = add(byAgent[slot.agent] ?? null, row.hours);
    }
  }

  // The Estimate's hours per active Requirement (even split of each line).
  const estimateHours = new Map<string, number>();
  let unlinked = 0;
  for (const section of estimate?.sections ?? []) {
    for (const line of section.lines) {
      const covered = [
        ...new Set(line.requirements.map((r) => r.id).filter((id) => active.has(id))),
      ];
      if (covered.length === 0) {
        unlinked += line.effort_hours;
        continue;
      }
      const share = line.effort_hours / covered.length;
      for (const id of covered) estimateHours.set(id, (estimateHours.get(id) ?? 0) + share);
    }
  }

  const rows: ComparisonRow[] = requirements.map((r, index) => ({
    id: r.id,
    label: `R${index + 1}`,
    excerpt: excerpt(r.text),
    ...values(
      agentHours.get(r.id) ?? noHours(),
      estimate ? (estimateHours.get(r.id) ?? 0) : null,
    ),
  }));

  // The totals sum each hours column (from the unrounded hours); the totals Difference is
  // the shown Estimate total − the shown Agents total.
  const totalAgents = noHours();
  for (const byAgent of agentHours.values()) {
    for (const a of AGENTS) totalAgents[a.value] = add(totalAgents[a.value], byAgent[a.value]);
  }
  const allocated = [...estimateHours.values()].reduce((sum, h) => sum + h, 0);
  const totals = values(totalAgents, estimate ? allocated : null);

  const anyAgent = Object.values(totalAgents).some((v) => v !== null);
  return {
    rows,
    totals,
    unlinkedHours: estimate ? tenth(unlinked) : null,
    leftOut,
    hasEstimate: estimate !== null,
    estimateVersion: estimate?.version ?? null,
    estimateEffortTotal: estimate ? tenth(allocated + unlinked) : null,
    empty: !anyAgent && estimate === null,
  };
}
