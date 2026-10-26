import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AssessmentsView } from "@/lib/assessments";
import type { ConflictsView } from "@/lib/conflicts";
import type { EstimateView } from "@/lib/estimates";
import type { GapList } from "@/lib/gaps";
import type { OverviewReads } from "@/lib/overview";
import type { RequirementList } from "@/lib/requirements";
import type { Source } from "@/lib/sources";
import type { Blocker, SubmissionBlockersView } from "@/lib/submission";
import { axeViolations } from "@/test/axe";

const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh, push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/app/opportunities/actions", () => ({ submitEstimateVersion: vi.fn() }));

import { ShellProviders } from "../shell/shell-context";
import { OverviewLiveRefresh, OVERVIEW_REFRESH_DEBOUNCE_MS } from "./overview-live-refresh";
import { OverviewSummary } from "./overview-summary";
import { SubmissionProvider } from "./submission-context";

class FakeSource {
  static last: FakeSource | null = null;
  readonly listeners = new Map<string, ((event: Event) => void)[]>();
  constructor(readonly url: string) {
    FakeSource.last = this;
  }
  addEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {}
  emit(type: string, data?: Record<string, unknown>) {
    const event =
      data === undefined ? new Event(type) : new MessageEvent(type, { data: JSON.stringify(data) });
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

let n = 0;
function uid(): string {
  n += 1;
  return `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`;
}

function blocker(kind: Blocker["kind"]): Blocker {
  const id = uid();
  return { kind, subject_id: id, title: `${kind} ${id}`, detail: "detail", href: `/x#${id}` };
}

function view(kinds: Blocker["kind"][]): SubmissionBlockersView {
  return {
    to_submit: kinds.map(blocker),
    to_baseline: [],
    version: {
      id: uid(),
      version: 3,
      status: "draft",
      row_version: 1,
      created_at: "2026-10-04T10:00:00Z",
      submitted_at: null,
    },
    can_submit: true,
  };
}

function reads(): OverviewReads {
  const source = { id: uid(), parse: { status: "parsed", error_code: null } } as unknown as Source;
  const req = (confirmed: boolean) => ({
    id: uid(),
    confirmed_at: confirmed ? "2026-10-05T09:00:00Z" : null,
  });
  const gap = (impact: string) => ({ id: uid(), title: `Gap ${impact}`, impact, status: "open" });
  return {
    sources: Array.from({ length: 6 }, () => source),
    requirements: {
      items: [...Array.from({ length: 9 }, () => req(true)), req(false), req(false), req(false)],
      extraction: { status: "succeeded", error_code: null, source_count: 6 },
      can_start_extraction: false,
      can_edit_requirements: false,
    } as unknown as RequirementList,
    gaps: {
      items: [gap("high"), gap("high"), gap("medium")],
      detection: { status: "succeeded", error_code: null },
      can_start_detection: false,
      can_edit_questions: false,
    } as unknown as GapList,
    estimate: {
      version: {
        version: 3,
        status: "draft",
        uncovered_count: 0,
        source_run: 2,
        counts: { total: 3, accepted: 1, not_accepted: 2 },
        totals: { total_hours: 278, role_hours: { engineer: 225.4, project_manager: 52.6, qa: 0 } },
        assumptions: { conditions: [], contingencies: [], contingency_hours: 0 },
      },
      draft: null,
    } as unknown as EstimateView,
    assessments: {
      run: null,
      can_start: false,
      assessments: [{ agent: "engineering_agent", assessment: null }],
    } as unknown as AssessmentsView,
    redTeam: { review: null, run: null, can_start: false, blocking_count: 0 },
    trace: [],
    conflicts: {
      conflicts: [
        { id: uid(), type: "effort", status: "open", requirement: null, escalated_to: null },
        { id: uid(), type: "scope", status: "open", requirement: null, escalated_to: null },
      ],
      open_count: 2,
      reviewers: [],
    } as unknown as ConflictsView,
    blockers: null,
  };
}

const TABS: Record<string, string> = {
  "Sources added": "sources",
  "Requirements extracted": "requirements",
  "Requirements confirmed": "requirements",
  "Gaps answered": "gaps",
  "Assessments run": "assessments",
  "Conflicts resolved": "conflicts",
  "Estimate accepted": "estimate",
  "Review and Baseline": "estimate",
};

function renderOverview(
  id: string,
  initial: SubmissionBlockersView | null,
  load?: (id: string) => Promise<SubmissionBlockersView | null>,
  data: OverviewReads = reads(),
) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <SubmissionProvider opportunityId={id} initial={initial} load={load}>
        <OverviewLiveRefresh opportunityId={id} />
        <OverviewSummary
          opportunityId={id}
          data={data}
          proposalDate="2026-11-06"
          today="2026-10-26"
        />
      </SubmissionProvider>
    </ShellProviders>,
  );
}

const pipeline = () => screen.getByRole("region", { name: "Submission pipeline" });
const stepStates = () =>
  Array.from(pipeline().querySelectorAll("li[data-step-state]")).map((li) =>
    li.getAttribute("data-step-state"),
  );

describe("Overview recomposition (Story 8.9)", () => {
  beforeEach(() => {
    refresh.mockReset();
    vi.stubGlobal("EventSource", FakeSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("the pipeline: pills with icon and text, links to each tab, nothing disabled, axe", async () => {
    const id = uid();
    const { container } = renderOverview(
      id,
      view(["gap", "gap", "gap", "conflict", "conflict", "assumption", "assumption"]),
    );
    const steps = Array.from(pipeline().querySelectorAll<HTMLElement>("li[data-step-state]"));
    expect(steps).toHaveLength(8);
    for (const step of steps) {
      const link = within(step).getByRole("link");
      expect(link.getAttribute("href")).toBe(`/opportunities/${id}/${TABS[link.textContent!]}`);
      const pill = step.querySelector("[data-tone]")!;
      expect(pill.querySelector("svg")).toBeTruthy();
      expect(pill.textContent).toMatch(/^(Complete|In progress|Blocked|Pending)$/);
    }
    expect(stepStates()).toEqual([
      "complete",
      "complete",
      "in-progress",
      "blocked",
      "pending",
      "blocked",
      "blocked",
      "pending",
    ]);
    expect(within(pipeline()).getByText("Starts when blockers clear")).toBeTruthy();
    expect(within(pipeline()).getByText("2 of 8 steps complete · 3 steps blocked")).toBeTruthy();
    expect(container.querySelector("[aria-disabled]")).toBeNull();
    expect(screen.getByText("Blocks submit")).toBeTruthy();
    expect(screen.getByText("Estimate · v3 draft")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("without a provider, the server's blockers are read; a failed read is Pending", () => {
    const id = uid();
    const first = render(
      <ShellProviders singleKeyShortcuts>
        <OverviewSummary
          opportunityId={id}
          data={{ ...reads(), blockers: view(["gap"]) }}
          proposalDate="2026-11-06"
          today="2026-10-26"
        />
      </ShellProviders>,
    );
    expect(stepStates()[3]).toBe("blocked");
    expect(screen.getByText("Needs a decision")).toBeTruthy();
    first.unmount();
    render(
      <ShellProviders singleKeyShortcuts>
        <OverviewSummary
          opportunityId={id}
          data={reads()}
          proposalDate="2026-11-06"
          today="2026-10-26"
        />
      </ShellProviders>,
    );
    expect(stepStates().slice(3)).toEqual(["pending", "pending", "pending", "pending", "pending"]);
    expect(
      within(pipeline()).getAllByText(
        "The submission blockers could not be loaded. Try again in a moment.",
      ),
    ).toHaveLength(5);
  });

  it("a provider whose read failed falls back to the server's blockers", () => {
    render(
      <ShellProviders singleKeyShortcuts>
        <SubmissionProvider opportunityId={uid()} initial={null}>
          <OverviewSummary
            opportunityId={uid()}
            data={{ ...reads(), blockers: view(["gap"]) }}
            proposalDate="2026-11-06"
            today="2026-10-26"
          />
        </SubmissionProvider>
      </ShellProviders>,
    );
    expect(stepStates().slice(3)).toEqual([
      "blocked",
      "pending",
      "complete",
      "complete",
      "pending",
    ]);
    expect(
      within(pipeline()).queryByText(
        "The submission blockers could not be loaded. Try again in a moment.",
      ),
    ).toBeNull();
  });

  it("a blocker frame flips the Conflicts step live, with the card", async () => {
    const id = uid();
    const load = vi.fn(async () => view(["gap"]));
    renderOverview(id, view(["gap", "conflict"]), load);
    expect(stepStates()[5]).toBe("blocked");

    await act(async () => FakeSource.last!.emit("conflicts.changed"));

    await waitFor(() => expect(stepStates()[5]).toBe("complete"));
    expect(load).toHaveBeenCalledWith(id);
    const card = screen.getByRole("region", { name: "Submission blockers" });
    expect(within(card).getByText("1 to submit · 0 to Baseline")).toBeTruthy();
    expect(screen.queryByText("Blocks submit")).toBeNull();
  });

  it("the live refresh skips the connect callbacks and debounces router.refresh", async () => {
    vi.useFakeTimers();
    renderOverview(uid(), view([]));
    const source = FakeSource.last!;

    await act(async () => source.emit("open"));
    await act(async () => vi.advanceTimersByTime(OVERVIEW_REFRESH_DEBOUNCE_MS + 50));
    expect(refresh).not.toHaveBeenCalled();

    await act(async () => source.emit("gaps.changed"));
    await act(async () => source.emit("conflicts.changed"));
    await act(async () => source.emit("intake.source.parsed"));
    await act(async () => source.emit("reviews.review_request.created"));
    await act(async () => vi.advanceTimersByTime(OVERVIEW_REFRESH_DEBOUNCE_MS - 50));
    expect(refresh).not.toHaveBeenCalled();
    await act(async () => vi.advanceTimersByTime(100));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  const RUN_QUEUED = {
    event_type: "workflows.run.queued",
    subject_type: "workflows.run",
    subject_id: "00000000-0000-7000-8000-0000000000f1",
    subject_version: null,
    occurred_at: "2026-10-26T09:00:00Z",
    summary: "Assessments queued",
  };

  it.each<[string, Record<string, unknown> | undefined]>([
    ["workflows.run.queued", RUN_QUEUED],
    ["intake.source.parsed", undefined],
    ["gaps.changed", undefined],
    ["conflicts.changed", undefined],
    ["reviews.review_request.created", undefined],
    ["estimates.assumption.accepted", undefined],
  ])("a %s frame alone refreshes once", async (type, data) => {
    vi.useFakeTimers();
    renderOverview(uid(), view([]));
    const source = FakeSource.last!;
    await act(async () => source.emit("open"));
    await act(async () => source.emit(type, data));
    await act(async () => vi.advanceTimersByTime(OVERVIEW_REFRESH_DEBOUNCE_MS));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("each frame restarts the debounce", async () => {
    vi.useFakeTimers();
    renderOverview(uid(), view([]));
    const source = FakeSource.last!;
    await act(async () => source.emit("open"));
    await act(async () => source.emit("intake.source.parsed"));
    await act(async () => vi.advanceTimersByTime(200));
    await act(async () => source.emit("intake.source.parsed"));
    // 300 ms after the first frame: nothing yet.
    await act(async () => vi.advanceTimersByTime(100));
    expect(refresh).not.toHaveBeenCalled();
    // 300 ms after the second frame: one refresh.
    await act(async () => vi.advanceTimersByTime(200));
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
