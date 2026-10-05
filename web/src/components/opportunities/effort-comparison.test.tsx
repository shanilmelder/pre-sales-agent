import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { AgentAssessment, AssessmentAgent } from "@/lib/assessments";
import type { EstimateVersion } from "@/lib/estimates";
import type { Requirement } from "@/lib/requirements";
import { axeViolations } from "@/test/axe";

import { EffortComparisonSection } from "./effort-comparison";

const REQUIREMENTS = [
  { id: "r1", text: "[REQ ONE]" },
  { id: "r2", text: "[REQ TWO]" },
] as Requirement[];

function slot(agent: AssessmentAgent, effort: [string, number][] | null): AgentAssessment {
  return {
    agent,
    assessment:
      effort === null
        ? null
        : ({
            effort: effort.map(([id, hours]) => ({
              requirement: { id, version: 1, label: "R1", excerpt: "" },
              hours,
              basis: "b",
            })),
          } as never),
  };
}

const FULL_AGENTS = [
  slot("engineering_agent", [
    ["r1", 20],
    ["r2", 6],
  ]),
  slot("pm_agent", [
    ["r1", 10],
    ["r2", 2],
  ]),
  slot("security_agent", [["r1", 4]]),
];

function estimate(lines: [number, string[]][]): EstimateVersion {
  return {
    version: 3,
    sections: [
      {
        section: "functional",
        lines: lines.map(([effort_hours, ids]) => ({
          effort_hours,
          requirements: ids.map((id) => ({ id, version: 1, label: "R1", excerpt: "" })),
        })),
      },
    ],
  } as never;
}

const cells = (row: HTMLElement) =>
  within(row)
    .getAllByRole("cell")
    .map((c) => c.textContent);

describe("EffortComparisonSection", () => {
  it("Full: hours per Requirement, totals, notes, accessible and keyboard reachable", async () => {
    const { container } = render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={FULL_AGENTS}
        estimate={estimate([
          [40, ["r1", "r2"]],
          [10, ["r1"]],
          [12, []],
        ])}
      />,
    );
    expect(screen.getByRole("heading", { level: 3, name: "Effort comparison" })).toBeTruthy();
    const table = screen.getByRole("table", { name: "Effort comparison by Requirement, in hours" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual([
      "Requirement",
      "Engineering",
      "PM",
      "Security",
      "Agents total",
      "Estimate (allocated)",
      "Difference",
    ]);
    const r1 = screen.getByRole("row", { name: /R1 \[REQ ONE\]/ });
    expect(within(r1).getByRole("rowheader").textContent).toBe("R1 [REQ ONE]");
    expect(cells(r1)).toEqual(["20.0", "10.0", "4.0", "34.0", "30.0", "−4.0"]);
    const r2 = screen.getByRole("row", { name: /R2 \[REQ TWO\]/ });
    expect(cells(r2)).toEqual(["6.0", "2.0", "—", "8.0", "20.0", "+12.0"]);
    const total = screen.getByRole("row", { name: /^Total/ });
    expect(cells(total)).toEqual(["26.0", "12.0", "4.0", "42.0", "50.0", "+8.0"]);
    expect(
      screen.getByText("Estimate effort: 62.0 h in total (12.0 h not linked to a Requirement)"),
    ).toBeTruthy();
    expect(within(total).getByText("Not linked to a Requirement: 12.0 h")).toBeTruthy();
    expect(
      screen.getByText(
        "Engineering, PM and Security size different work, so their hours add up. Estimate v3. A line covering several Requirements is shared equally between them.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();

    await userEvent.tab();
    expect(document.activeElement).toBe(
      screen.getByRole("region", { name: "Effort comparison by Requirement, in hours" }),
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("No Estimate: Estimate and Difference are dashes", () => {
    render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={FULL_AGENTS}
        estimate={null}
      />,
    );
    expect(cells(screen.getByRole("row", { name: /R1/ }))).toEqual([
      "20.0",
      "10.0",
      "4.0",
      "34.0",
      "—",
      "—",
    ]);
    expect(cells(screen.getByRole("row", { name: /^Total/ }))).toEqual([
      "26.0",
      "12.0",
      "4.0",
      "42.0",
      "—",
      "—",
    ]);
    expect(screen.queryByText(/Not linked/)).toBeNull();
  });

  it("No Assessments: agent columns are dashes, the Estimate is filled", () => {
    render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={[
          slot("engineering_agent", null),
          slot("pm_agent", null),
          slot("security_agent", null),
        ]}
        estimate={estimate([[30, ["r1"]]])}
      />,
    );
    expect(cells(screen.getByRole("row", { name: /R1/ }))).toEqual([
      "—",
      "—",
      "—",
      "—",
      "30.0",
      "—",
    ]);
  });

  it("Superseded: the row is left out and the note says so", () => {
    render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={[slot("engineering_agent", [["r-old", 5], ["r1", 3]])]}
        estimate={null}
      />,
    );
    expect(screen.getAllByRole("row")).toHaveLength(4); // header, R1, R2, total
    expect(
      screen.getByText("1 effort row for Requirements no longer active is not shown"),
    ).toBeTruthy();
  });

  it("Empty: neither agent effort nor an Estimate", async () => {
    const { container } = render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={[slot("engineering_agent", null)]}
        estimate={null}
      />,
    );
    expect(screen.getByText("No effort to compare yet.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Partial failure: no Estimate columns, and it says the Estimate could not be loaded", async () => {
    const { container } = render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={FULL_AGENTS}
        estimate="error"
      />,
    );
    expect(
      screen.getByText("The Estimate could not be loaded, so its hours are not shown."),
    ).toBeTruthy();
    expect(
      screen.getAllByRole("columnheader").map((h) => h.textContent),
    ).toEqual(["Requirement", "Engineering", "PM", "Security", "Agents total"]);
    expect(cells(screen.getByRole("row", { name: /R1/ }))).toEqual([
      "20.0",
      "10.0",
      "4.0",
      "34.0",
    ]);
    expect(screen.queryByText(/shared equally/)).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Empty with superseded agent effort: only the empty sentence", () => {
    render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={[slot("engineering_agent", [["r-old", 5]])]}
        estimate={null}
      />,
    );
    expect(screen.getByText("No effort to compare yet.")).toBeTruthy();
    expect(screen.queryByText(/no longer active/)).toBeNull();
  });

  it("a failed Estimate read with no agent effort is not called empty", () => {
    render(
      <EffortComparisonSection
        requirements={REQUIREMENTS}
        assessments={[slot("engineering_agent", null)]}
        estimate="error"
      />,
    );
    expect(screen.queryByText("No effort to compare yet.")).toBeNull();
    expect(
      screen.getByText("The Estimate could not be loaded, so its hours are not shown."),
    ).toBeTruthy();
    expect(screen.getByRole("table")).toBeTruthy();
  });

  it("a failed Requirements or Assessments read says so", () => {
    render(
      <EffortComparisonSection requirements={null} assessments={FULL_AGENTS} estimate={null} />,
    );
    expect(
      screen.getByText("The Effort comparison could not be loaded. Try again in a moment."),
    ).toBeTruthy();
  });
});
