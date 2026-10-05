import { describe, expect, it } from "vitest";

import type { AgentAssessment, AssessmentAgent } from "./assessments";
import {
  agentColumn,
  compareEffort,
  comparisonHours,
  estimateColumnNote,
  estimateTotalNote,
  excerpt,
  leftOutNote,
  signedHours,
} from "./effort-comparison";
import type { EstimateVersion } from "./estimates";

const R1 = { id: "r1", text: "First requirement" };
const R2 = { id: "r2", text: "Second requirement" };
const R3 = { id: "r3", text: "Third requirement" };
const OLD = "r-old";

function chip(id: string) {
  return { id, version: 1, label: "R?", excerpt: "" };
}

/** One agent's slot with effort `[requirementId, hours]` (null: no Assessment). */
function slot(
  agent: AssessmentAgent,
  effort: [string, number][] | null,
): AgentAssessment {
  return {
    agent,
    assessment:
      effort === null
        ? null
        : ({
            effort: effort.map(([id, hours]) => ({ requirement: chip(id), hours, basis: "b" })),
          } as never),
  };
}

function agents(
  engineering: [string, number][] | null,
  pm: [string, number][] | null,
  security: [string, number][] | null,
) {
  return [
    slot("engineering_agent", engineering),
    slot("pm_agent", pm),
    slot("security_agent", security),
  ];
}

/** An Estimate version with lines `[effortHours, requirementIds]`. */
function estimate(lines: [number, string[]][]): EstimateVersion {
  return {
    sections: [
      {
        section: "functional",
        lines: lines.map(([effort_hours, ids]) => ({
          effort_hours,
          requirements: ids.map(chip),
        })),
      },
    ],
  } as never;
}

describe("compareEffort", () => {
  it("Full: agents add up and the difference is Estimate − Agents total", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents([["r1", 20]], [["r1", 10]], [["r1", 4]]),
      estimate: estimate([[30, ["r1"]]]),
    });
    expect(c.rows).toHaveLength(1);
    const row = c.rows[0];
    expect(row.label).toBe("R1");
    expect(row.excerpt).toBe("First requirement");
    expect(row.agents).toEqual({ engineering_agent: 20, pm_agent: 10, security_agent: 4 });
    expect(row.agentsTotal).toBe(34);
    expect(row.estimate).toBe(30);
    expect(row.difference).toBe(-4);
    expect(c.totals.agentsTotal).toBe(34);
    expect(c.totals.estimate).toBe(30);
    expect(c.totals.difference).toBe(-4);
    expect(c.unlinkedHours).toBe(0);
    expect(c.leftOut).toBe(0);
    expect(c.empty).toBe(false);
  });

  it("Shared line: split equally between the active Requirements it covers", () => {
    const c = compareEffort({
      requirements: [R1, R2],
      assessments: agents(null, null, null),
      estimate: estimate([
        [40, ["r1", "r2"]],
        [10, ["r2"]],
      ]),
    });
    expect(c.rows.map((r) => r.estimate)).toEqual([20, 30]);
    expect(c.totals.estimate).toBe(50);
  });

  it("a line's superseded Requirements don't take a share", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents(null, null, null),
      estimate: estimate([[40, ["r1", OLD]]]),
    });
    expect(c.rows[0].estimate).toBe(40);
    expect(c.unlinkedHours).toBe(0);
  });

  it("Unlinked line: only in the not-linked figure", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents(null, null, null),
      estimate: estimate([
        [12, []],
        [5, [OLD]],
        [8, ["r1"]],
      ]),
    });
    expect(c.rows[0].estimate).toBe(8);
    expect(c.totals.estimate).toBe(8);
    expect(c.unlinkedHours).toBe(17);
  });

  it("Missing agent: its cell is null and the total is of the other two", () => {
    const c = compareEffort({
      requirements: [R1, R2],
      assessments: agents(
        [
          ["r1", 8],
          ["r2", 6],
        ],
        [
          ["r1", 2],
          ["r2", 3],
        ],
        [["r1", 1]],
      ),
      estimate: null,
    });
    expect(c.rows[1].agents.security_agent).toBeNull();
    expect(c.rows[1].agentsTotal).toBe(9);
    expect(c.totals.agents).toEqual({ engineering_agent: 14, pm_agent: 5, security_agent: 1 });
    expect(c.totals.agentsTotal).toBe(20);
  });

  it("No Estimate: Estimate and Difference are null, agents' totals shown", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents([["r1", 5]], null, null),
      estimate: null,
    });
    expect(c.rows[0].estimate).toBeNull();
    expect(c.rows[0].difference).toBeNull();
    expect(c.totals.estimate).toBeNull();
    expect(c.totals.difference).toBeNull();
    expect(c.totals.agentsTotal).toBe(5);
    expect(c.unlinkedHours).toBeNull();
    expect(c.hasEstimate).toBe(false);
    expect(c.empty).toBe(false);
  });

  it("No Assessments: agent columns null, Estimate filled", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents(null, null, null),
      estimate: estimate([[12, ["r1"]]]),
    });
    expect(c.rows[0].agents).toEqual({
      engineering_agent: null,
      pm_agent: null,
      security_agent: null,
    });
    expect(c.rows[0].agentsTotal).toBeNull();
    expect(c.rows[0].estimate).toBe(12);
    expect(c.rows[0].difference).toBeNull();
    expect(c.totals.difference).toBeNull();
    expect(c.empty).toBe(false);
  });

  it("a Requirement the Estimate doesn't cover is allocated 0 h", () => {
    const c = compareEffort({
      requirements: [R1, R2],
      assessments: agents([["r2", 6]], null, null),
      estimate: estimate([[10, ["r1"]]]),
    });
    expect(c.rows[1].estimate).toBe(0);
    expect(c.rows[1].difference).toBe(-6);
    // The totals Difference is the shown Estimate total − the shown Agents total.
    expect(c.totals.estimate).toBe(10);
    expect(c.totals.agentsTotal).toBe(6);
    expect(c.totals.difference).toBe(4);
  });

  it("Superseded: rows citing inactive Requirements are left out and counted", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents(
        [
          ["r1", 5],
          [OLD, 9],
        ],
        null,
        null,
      ),
      estimate: null,
    });
    expect(c.rows).toHaveLength(1);
    expect(c.totals.agentsTotal).toBe(5);
    expect(c.leftOut).toBe(1);
  });

  it("Empty: no agent effort and no Estimate", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents(null, [], null),
      estimate: null,
    });
    expect(c.empty).toBe(true);
  });

  it("only superseded agent effort and no Estimate is still empty", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents([[OLD, 3]], null, null),
      estimate: null,
    });
    expect(c.empty).toBe(true);
    expect(c.leftOut).toBe(1);
  });

  it("rows follow Requirement order, labelled R1…Rn", () => {
    const c = compareEffort({
      requirements: [R3, R1, R2],
      assessments: agents([["r2", 1]], null, null),
      estimate: null,
    });
    expect(c.rows.map((r) => [r.id, r.label])).toEqual([
      ["r3", "R1"],
      ["r1", "R2"],
      ["r2", "R3"],
    ]);
  });

  it("rounds to a tenth without floating noise", () => {
    const c = compareEffort({
      requirements: [R1, R2, R3],
      assessments: agents([["r1", 0.1]], [["r1", 0.2]], null),
      estimate: estimate([[40, ["r1", "r2", "r3"]]]),
    });
    expect(c.rows[0].agentsTotal).toBe(0.3);
    expect(c.rows.map((r) => r.estimate)).toEqual([13.3, 13.3, 13.3]);
    expect(c.totals.estimate).toBe(40);
    expect(c.rows[0].difference).toBe(13);
  });

  it("each Difference is computed from the shown (rounded) hours", () => {
    const c = compareEffort({
      requirements: [R1, R2],
      assessments: agents([["r1", 0.1]], null, null),
      estimate: estimate([[0.3, ["r1", "r2"]]]),
    });
    // 0.15 h shows as 0.2; 0.2 − 0.1 = 0.1 (not 0.15 − 0.1 = 0.05 → 0.0).
    expect(c.rows[0].estimate).toBe(0.2);
    expect(c.rows[0].difference).toBe(0.1);
  });

  it("the totals Difference is null when either total is", () => {
    expect(
      compareEffort({
        requirements: [R1],
        assessments: agents([["r1", 5]], null, null),
        estimate: null,
      }).totals.difference,
    ).toBeNull();
    expect(
      compareEffort({
        requirements: [R1],
        assessments: agents(null, null, null),
        estimate: estimate([[5, ["r1"]]]),
      }).totals.difference,
    ).toBeNull();
  });

  it("names the Estimate version and its effort total, linked or not", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: agents(null, null, null),
      estimate: { ...estimate([[30, ["r1"]], [12, []]]), version: 2 },
    });
    expect(c.estimateVersion).toBe(2);
    expect(c.estimateEffortTotal).toBe(42);
    expect(c.unlinkedHours).toBe(12);
    const none = compareEffort({
      requirements: [R1],
      assessments: agents([["r1", 1]], null, null),
      estimate: null,
    });
    expect(none.estimateVersion).toBeNull();
    expect(none.estimateEffortTotal).toBeNull();
  });

  it("ignores an agent this build doesn't know", () => {
    const c = compareEffort({
      requirements: [R1],
      assessments: [slot("research_agent" as AssessmentAgent, [["r1", 5]])],
      estimate: null,
    });
    expect(c.rows[0].agentsTotal).toBeNull();
    expect(c.empty).toBe(true);
  });
});

describe("formatting", () => {
  it("hours to 0.1 or a dash", () => {
    expect(comparisonHours(12)).toBe("12.0");
    expect(comparisonHours(null)).toBe("—");
  });

  it("signed differences", () => {
    expect(signedHours(-4)).toBe("−4.0");
    expect(signedHours(4)).toBe("+4.0");
    expect(signedHours(0)).toBe("0.0");
    expect(signedHours(null)).toBe("—");
  });

  it("the left-out note", () => {
    expect(leftOutNote(1)).toBe(
      "1 effort row for Requirements no longer active is not shown",
    );
    expect(leftOutNote(3)).toBe(
      "3 effort rows for Requirements no longer active are not shown",
    );
  });

  it("the Estimate notes", () => {
    expect(estimateColumnNote(2)).toBe(
      "Estimate v2. A line covering several Requirements is shared equally between them.",
    );
    expect(estimateTotalNote(42, 12)).toBe(
      "Estimate effort: 42.0 h in total (12.0 h not linked to a Requirement)",
    );
  });

  it("agent columns", () => {
    expect(agentColumn("engineering_agent")).toBe("Engineering");
    expect(agentColumn("pm_agent")).toBe("PM");
    expect(agentColumn("security_agent")).toBe("Security");
  });

  it("excerpts like the server", () => {
    expect(excerpt("  a\n b  ")).toBe("a b");
    const long = `${"word ".repeat(40)}end`;
    const cut = excerpt(long);
    expect(Array.from(cut).length).toBeLessThanOrEqual(140);
    expect(cut.endsWith("…")).toBe(true);
    expect(cut).not.toContain(" …");
  });
});
