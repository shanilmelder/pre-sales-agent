import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  AcceptAllAssumptionsResult,
  AssumptionAcceptInput,
  AssumptionAcceptResult,
  StartEstimateDraftResult,
} from "@/app/opportunities/actions";
import type { EstimateResult } from "@/app/opportunities/data";
import type { Assumption, EstimateLine, EstimateVersion, EstimateView } from "@/lib/estimates";
import { axeViolations } from "@/test/axe";

const startEstimateDraft = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<StartEstimateDraftResult>>(),
);
const loadEstimate = vi.hoisted(() => vi.fn<(opportunityId: string) => Promise<EstimateResult>>());
const acceptAssumption = vi.hoisted(() =>
  vi.fn<(input: AssumptionAcceptInput) => Promise<AssumptionAcceptResult>>(),
);
const acceptAllAssumptions = vi.hoisted(() =>
  vi.fn<(opportunityId: string) => Promise<AcceptAllAssumptionsResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  startEstimateDraft,
  loadEstimate,
  acceptAssumption,
  acceptAllAssumptions,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/opportunities/x/estimate",
}));

import { RightPane } from "../shell/right-pane";
import { ShellProviders } from "../shell/shell-context";
import { EstimateSection } from "./estimate-grid";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const LINE_ID = "00000000-0000-7000-8000-0000000000d2";

function line(contingency: number): EstimateLine {
  return {
    id: LINE_ID,
    position: 1,
    section: "integration",
    title: "[LINE]",
    basis: "[BASIS]",
    role_mix: { engineer: 60, project_manager: 20, qa: 20 },
    effort_hours: 10,
    contingency_hours: contingency,
    total_hours: 10 + contingency,
    role_hours: { engineer: 6, project_manager: 2, qa: 2 },
    requirements: [],
  };
}

function assumption(
  n: number,
  kind: "condition" | "contingency",
  options: { hours?: number; line?: boolean; accepted?: boolean; carriedFrom?: number } = {},
): Assumption {
  return {
    id: `00000000-0000-7000-8000-0000000000a${n}`,
    kind,
    wording: `[WORDING ${n}]`,
    amount_hours: kind === "contingency" ? (options.hours ?? 8) : null,
    line: options.line ? { id: LINE_ID, title: "[LINE]" } : null,
    origin_kind: "gap",
    origin: {
      id: `00000000-0000-7000-8000-0000000000e${n}`,
      title: `[GAP ${n}]`,
      category: "integration_details",
      impact: "high",
      why_it_matters: `[WHY ${n}]`,
      status: options.accepted ? "converted" : "open",
    },
    accepted_by: options.accepted ? { id: "u1", name: "[NAME]" } : null,
    accepted_at: options.accepted ? "2026-10-05T09:00:00Z" : null,
    row_version: options.accepted ? 2 : 1,
    carried_from_version: options.carriedFrom ?? null,
  };
}

function version(
  items: Assumption[],
  overrides: Partial<EstimateVersion> = {},
  unallocated = 12,
): EstimateVersion {
  const conditions = items.filter((a) => a.kind === "condition");
  const contingencies = items.filter((a) => a.kind === "contingency");
  const linked = contingencies
    .filter((a) => a.line)
    .reduce((sum, a) => sum + (a.amount_hours ?? 0), 0);
  const accepted = items.filter((a) => a.accepted_at).length;
  const totals = {
    effort_hours: 10,
    contingency_hours: linked + unallocated,
    total_hours: 10 + linked + unallocated,
    role_hours: { engineer: 6, project_manager: 2, qa: 2 },
  };
  return {
    id: "00000000-0000-7000-8000-0000000000d1",
    version: 1,
    status: "draft",
    template_version: "demo-1",
    roles: ["engineer", "project_manager", "qa"],
    uncovered_count: 0,
    dropped_count: 0,
    row_version: 1,
    created_at: "2026-10-05T09:00:00Z",
    sections: [
      {
        section: "integration",
        lines: [line(linked)],
        subtotal: {
          ...totals,
          contingency_hours: linked,
          total_hours: 10 + linked,
        },
      },
    ],
    totals,
    proposal_status: "succeeded",
    assumptions: {
      conditions,
      contingencies,
      contingency_hours: contingencies.reduce((sum, a) => sum + (a.amount_hours ?? 0), 0),
    },
    counts: {
      total: items.length,
      accepted,
      not_accepted: items.length - accepted,
    },
    unconverted_gaps: [],
    unallocated_contingency_hours: unallocated,
    ...overrides,
  };
}

const FOUR = [
  assumption(1, "condition", { accepted: true }),
  assumption(2, "contingency", { hours: 8, line: true }),
  assumption(3, "condition"),
  assumption(4, "contingency", { hours: 12 }),
];

function view(v: EstimateVersion, canAccept = true): EstimateView {
  return {
    version: v,
    draft: { status: "succeeded", error_code: null },
    can_start_draft: canAccept,
    can_accept_assumptions: canAccept,
  };
}

function renderSection(initial: EstimateView) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <EstimateSection opportunityId={OPP_ID} initial={initial} />
      <RightPane />
    </ShellProviders>,
  );
}

const register = () => screen.getByTestId("assumptions-register");
const row = (n: number) =>
  register().querySelector<HTMLElement>(`[data-assumption-id$="a${n}"]`) as HTMLElement;

beforeEach(() => {
  startEstimateDraft.mockReset();
  loadEstimate.mockReset();
  acceptAssumption.mockReset();
  acceptAllAssumptions.mockReset();
});

describe("the Assumptions Register", () => {
  it("groups Conditions and Contingencies with counts, hours, origins and blocker rows", async () => {
    const { container } = renderSection(view(version(FOUR)));

    const reg = register();
    expect(within(reg).getByText("4 · 1 accepted · 3 not accepted")).toBeTruthy();
    expect(within(reg).getByRole("button", { name: "Accept all (3)" })).toBeTruthy();
    const conditions = within(reg).getByRole("region", { name: /Conditions/ });
    const contingencies = within(reg).getByRole("region", {
      name: /Contingencies/,
    });
    expect(within(conditions).getAllByRole("listitem")).toHaveLength(2);
    expect(within(contingencies).getAllByRole("listitem")).toHaveLength(2);
    expect(within(contingencies).getByRole("heading").textContent).toBe("Contingencies(2)20.0 h");

    // An accepted row names who accepted it; it is no blocker.
    expect(row(1).hasAttribute("data-blocker")).toBe(false);
    expect(within(row(1)).getByText("Accepted by [NAME], 5 Oct 2026")).toBeTruthy();
    expect(within(row(1)).queryByRole("button", { name: /^Accept/ })).toBeNull();
    // An unaccepted row is a blocker row: tint, bar and a label, with Accept.
    expect(row(2).hasAttribute("data-blocker")).toBe(true);
    expect(row(2).className).toContain("bg-blocker-tint");
    expect(row(2).className).toContain("shadow-[inset_2px_0_0_var(--blocker)]");
    expect(within(row(2)).getByText("Not accepted")).toBeTruthy();
    expect(within(row(2)).getByRole("button", { name: "Accept: [WORDING 2]" })).toBeTruthy();
    expect(within(row(2)).getByText("8.0 h")).toBeTruthy();
    expect(within(row(2)).getByText("Line: [LINE]")).toBeTruthy();
    expect(within(row(4)).queryByText(/^Line:/)).toBeNull();
    expect(within(row(3)).queryByText(/ h$/)).toBeNull();
    expect(within(row(3)).getByRole("button", { name: "Gap: [GAP 3]" })).toBeTruthy();

    // The grid prices the Contingencies: the line's and the unallocated row.
    const grid = screen.getByRole("table");
    const unallocated = within(grid).getByRole("rowheader", {
      name: "Unallocated contingency",
    });
    expect(unallocated.closest("tr")?.textContent).toContain("12.0");
    expect(within(grid).getByRole("rowheader", { name: "Total" }).closest("tr")?.textContent).toBe(
      "Total10.020.030.0",
    );
    expect(await axeViolations(container)).toEqual([]);
  });

  it("marks an Assumption a re-draft carried forward, next to who accepted it", async () => {
    const carried = [
      assumption(1, "condition", { accepted: true, carriedFrom: 1 }),
      assumption(2, "contingency", { hours: 8, line: true, accepted: true, carriedFrom: 1 }),
      assumption(3, "condition"),
    ];
    const { container } = renderSection(view(version(carried, { version: 2 }, 0)));

    expect(within(row(1)).getByText("Carried from v1")).toBeTruthy();
    expect(within(row(1)).getByText("Accepted by [NAME], 5 Oct 2026")).toBeTruthy();
    expect(row(1).hasAttribute("data-blocker")).toBe(false);
    expect(within(row(2)).getByText("Carried from v1")).toBeTruthy();
    expect(within(row(2)).getByText("Line: [LINE]")).toBeTruthy();
    // A proposal of this version isn't carried, and is still accepted the usual way.
    expect(within(row(3)).queryByText(/^Carried from/)).toBeNull();
    expect(within(register()).getByRole("button", { name: "Accept all (1)" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Accept accepts with If-Match and the grid refreshes from the server", async () => {
    const user = userEvent.setup();
    const after = [
      FOUR[0],
      assumption(2, "contingency", { hours: 8, line: true, accepted: true }),
      FOUR[2],
      FOUR[3],
    ];
    acceptAssumption.mockResolvedValue({ kind: "ok", assumption: after[1] });
    loadEstimate.mockResolvedValue({
      kind: "ok",
      estimate: view(version(after, {}, 20)),
    });
    renderSection(view(version(FOUR)));

    await user.click(within(row(2)).getByRole("button", { name: "Accept: [WORDING 2]" }));

    expect(acceptAssumption).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      assumptionId: FOUR[1].id,
      rowVersion: 1,
    });
    await waitFor(() =>
      expect(within(register()).getByText("4 · 2 accepted · 2 not accepted")).toBeTruthy(),
    );
    expect(within(row(2)).getByText("Accepted by [NAME], 5 Oct 2026")).toBeTruthy();
    expect(within(register()).getByRole("button", { name: "Accept all (2)" })).toBeTruthy();
    const total = within(screen.getByRole("table")).getByRole("rowheader", {
      name: "Total",
    });
    expect(total.closest("tr")?.textContent).toBe("Total10.028.038.0");
  });

  it("Accept all accepts the rest and hides itself once none is left", async () => {
    const user = userEvent.setup();
    const all = FOUR.map((a, i) =>
      assumption(i + 1, a.kind, {
        hours: a.amount_hours ?? undefined,
        line: a.line !== null,
        accepted: true,
      }),
    );
    acceptAllAssumptions.mockResolvedValue({ kind: "ok", count: 3 });
    loadEstimate.mockResolvedValue({
      kind: "ok",
      estimate: view(version(all)),
    });
    renderSection(view(version(FOUR)));

    await user.click(within(register()).getByRole("button", { name: "Accept all (3)" }));

    expect(acceptAllAssumptions).toHaveBeenCalledWith(OPP_ID);
    await waitFor(() =>
      expect(within(register()).getByText("4 · 4 accepted · 0 not accepted")).toBeTruthy(),
    );
    expect(within(register()).queryByRole("button", { name: /Accept all/ })).toBeNull();
    expect(register().querySelectorAll("[data-blocker]")).toHaveLength(0);
  });

  it("on 412 says who changed it, with Reload", async () => {
    const user = userEvent.setup();
    acceptAssumption.mockResolvedValue({ kind: "stale", changedBy: "[OTHER]" });
    loadEstimate.mockResolvedValue({
      kind: "ok",
      estimate: view(version(FOUR)),
    });
    renderSection(view(version(FOUR)));

    await user.click(within(row(3)).getByRole("button", { name: "Accept: [WORDING 3]" }));

    expect(
      await within(register()).findByText("Changed by [OTHER] since you opened it."),
    ).toBeTruthy();
    await user.click(within(register()).getByRole("button", { name: "Reload" }));
    expect(loadEstimate).toHaveBeenCalledWith(OPP_ID);
    await waitFor(() => expect(within(register()).queryByText(/Changed by/)).toBeNull());
  });

  it("says when the Gap is no longer open", async () => {
    const user = userEvent.setup();
    acceptAssumption.mockResolvedValue({ kind: "gap-not-open" });
    renderSection(view(version(FOUR)));

    await user.click(within(row(3)).getByRole("button", { name: "Accept: [WORDING 3]" }));

    expect(await within(register()).findByText(/Its Gap is no longer open/)).toBeTruthy();
    expect(loadEstimate).not.toHaveBeenCalled();
  });

  it("is read-only for those who may not accept (sales representatives)", () => {
    renderSection(view(version(FOUR), false));
    expect(within(register()).getByText("4 · 1 accepted · 3 not accepted")).toBeTruthy();
    expect(within(register()).queryByRole("button", { name: /Accept/ })).toBeNull();
    expect(within(row(2)).getByText("Not accepted")).toBeTruthy();
  });

  it("the Gap chip opens the Gap in the inspector", async () => {
    const user = userEvent.setup();
    renderSection(view(version(FOUR)));

    await user.click(within(row(2)).getByRole("button", { name: "Gap: [GAP 2]" }));

    const pane = screen.getByRole("complementary", { name: "Details" });
    expect(within(pane).getByRole("heading", { name: "[GAP 2]" })).toBeTruthy();
    expect(within(pane).getByText("[WHY 2]")).toBeTruthy();
    expect(within(pane).getByText("Gap · Integration details")).toBeTruthy();
    expect(
      within(row(2)).getByRole("button", { name: "Gap: [GAP 2]" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("lists Unconverted Gaps and shows proposals in progress or failed", () => {
    const { unmount } = renderSection(
      view(
        version(FOUR.slice(0, 2), {
          unconverted_gaps: [
            {
              id: "00000000-0000-7000-8000-0000000000e9",
              title: "[GAP 9]",
              category: "data_volumes",
              impact: "medium",
            },
          ],
        }),
      ),
    );
    const note = within(register()).getByRole("note");
    expect(within(note).getByText("Unconverted Gaps (1)")).toBeTruthy();
    expect(within(note).getByText("[GAP 9]")).toBeTruthy();
    expect(within(note).getByText("Data volumes")).toBeTruthy();
    unmount();

    const { unmount: unmount2 } = renderSection(
      view(version([], { proposal_status: "running" }, 0)),
    );
    expect(within(register()).getByText("Proposing Assumptions")).toBeTruthy();
    expect(within(register()).getByText("0 · 0 accepted · 0 not accepted")).toBeTruthy();
    expect(screen.queryByRole("rowheader", { name: "Unallocated contingency" })).toBeNull();
    unmount2();

    renderSection(view(version([], { proposal_status: "failed" }, 0)));
    expect(within(register()).getByText("Assumptions couldn't be proposed.")).toBeTruthy();
  });

  it.each([
    ["failed", "Assumptions couldn't be proposed."],
    [null, "No Assumptions were proposed for this version."],
  ] as const)(
    "with proposals %s, Retry re-drafts the Estimate for a collaborator",
    async (status, sentence) => {
      const user = userEvent.setup();
      startEstimateDraft.mockResolvedValue({
        kind: "ok",
        draft: { status: "queued", error_code: null },
      });
      renderSection(view(version([], { proposal_status: status }, 0)));

      const note = within(register()).getByTestId("proposals-failed");
      expect(within(note).getByText(sentence)).toBeTruthy();
      await user.click(within(note).getByRole("button", { name: "Retry" }));

      expect(startEstimateDraft).toHaveBeenCalledWith(OPP_ID);
      expect(await screen.findByText("Drafting Estimate")).toBeTruthy();
      // While the re-draft runs, Retry isn't offered again.
      expect(within(register()).queryByRole("button", { name: "Retry" })).toBeNull();
    },
  );

  it("hides the proposals Retry from sales representatives", () => {
    renderSection(view(version([], { proposal_status: "failed" }, 0), false));
    const note = within(register()).getByTestId("proposals-failed");
    expect(within(note).getByText("Assumptions couldn't be proposed.")).toBeTruthy();
    expect(within(note).queryByRole("button")).toBeNull();
  });
});
