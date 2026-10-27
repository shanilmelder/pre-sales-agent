import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Blocker, SubmissionBlockersView } from "@/lib/submission";
import { axeViolations } from "@/test/axe";

const refresh = vi.hoisted(() => vi.fn());
const submitEstimateVersion = vi.hoisted(() => vi.fn());
const loadVersionApprovers = vi.hoisted(() => vi.fn());
const setEstimateBaseline = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh, push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));
vi.mock("@/app/opportunities/actions", () => ({
  submitEstimateVersion,
  loadVersionApprovers,
  setEstimateBaseline,
}));

import { ShellProviders } from "../shell/shell-context";
import { SubmissionBlockersCard, SubmissionHeaderActions } from "./submission";
import { SubmissionProvider } from "./submission-context";

class FakeSource {
  static last: FakeSource | null = null;
  readonly listeners = new Map<string, (() => void)[]>();
  constructor(readonly url: string) {
    FakeSource.last = this;
  }
  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }
  close() {}
  emit(type: string) {
    for (const listener of this.listeners.get(type) ?? []) listener();
  }
}

let n = 0;
/** A fresh Opportunity id per test: the event stream is shared per id. */
function oppId(): string {
  n += 1;
  return `00000000-0000-7000-8000-${String(n).padStart(12, "0")}`;
}

function blocker(kind: Blocker["kind"], title: string, id = title): Blocker {
  return { kind, subject_id: id, title, detail: `${title} detail`, href: `/x/${kind}#${id}` };
}

function view(
  toSubmit: Blocker[],
  { canSubmit = true, status = "draft" as "draft" | "submitted", noVersion = false } = {},
): SubmissionBlockersView {
  return {
    to_submit: toSubmit,
    to_baseline: [],
    version: noVersion
      ? null
      : {
          id: "00000000-0000-7000-8000-0000000000e3",
          version: 3,
          status,
          row_version: 2,
          created_at: "2026-10-04T10:00:00Z",
          submitted_at: status === "submitted" ? "2026-10-14T09:00:00Z" : null,
        },
    can_submit: canSubmit,
    is_baseline: false,
    can_set_baseline: false,
  };
}

const MIXED = [
  blocker("gap", "[GAP 1]"),
  blocker("gap", "[GAP 2]"),
  blocker("assumption", "[ASSUMPTION]"),
  blocker("conflict", "[CONFLICT]"),
  blocker("finding", "[FINDING]"),
  blocker("uncovered_requirement", "R7 not covered"),
];

function renderAll(
  id: string,
  initial: SubmissionBlockersView | null,
  load?: (id: string) => Promise<SubmissionBlockersView | null>,
) {
  return render(
    <ShellProviders singleKeyShortcuts>
      <SubmissionProvider opportunityId={id} initial={initial} load={load}>
        <SubmissionHeaderActions />
        <SubmissionBlockersCard opportunityId={id} initial={null} />
      </SubmissionProvider>
    </ShellProviders>,
  );
}

const card = () => screen.getByRole("region", { name: "Submission blockers" });

describe("Submission blockers (Story 8.6)", () => {
  beforeEach(() => {
    refresh.mockReset();
    submitEstimateVersion.mockReset();
    vi.stubGlobal("EventSource", FakeSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("blocked: one row per kind with each subject linked, the pill, and the header", async () => {
    const id = oppId();
    const { container } = renderAll(id, view(MIXED));

    expect(within(card()).getByText("6 to submit · 0 to Baseline")).toBeTruthy();
    const rows = Array.from(card().querySelectorAll<HTMLElement>("[data-blocker]"));
    expect(rows.map((r) => r.getAttribute("data-blocker"))).toEqual([
      "gap",
      "assumption",
      "conflict",
      "finding",
      "uncovered_requirement",
    ]);
    expect(rows.map((r) => r.querySelector(".text-body-strong")?.textContent)).toEqual([
      "2 open Gaps",
      "1 Assumption not accepted",
      "1 open Conflict",
      "1 critical Finding",
      "1 Requirement not covered",
    ]);
    expect(rows[0]!.className).toContain("bg-blocker-tint");
    expect(within(rows[0]!).getByRole("link", { name: "[GAP 2]" }).getAttribute("href")).toBe(
      "/x/gap#[GAP 2]",
    );
    expect(within(rows[0]!).getByRole("link", { name: "Open Gaps" }).getAttribute("href")).toBe(
      `/opportunities/${id}/gaps`,
    );
    expect(within(rows[3]!).getByRole("link", { name: "Resolve" })).toBeTruthy();
    expect(within(card()).getByText("Blockers to submit · 6")).toBeTruthy();
    expect(within(card()).getByText("Blockers to Baseline · 0")).toBeTruthy();
    expect(within(card()).getByText("No Review Request sent yet")).toBeTruthy();

    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit.getAttribute("aria-disabled")).toBe("true");
    expect(submit.getAttribute("aria-describedby")).toBeTruthy();
    expect(screen.getByText("Resolve 6 blockers to submit")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Resolve 6 blockers" }).getAttribute("href")).toBe(
      `/opportunities/${id}/overview#overview-blockers`,
    );
    await userEvent.click(submit);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("ready: the centred check, Submit primary, Resolve hidden", async () => {
    const { container } = renderAll(oppId(), view([]));

    expect(within(card()).getByText("0 blockers")).toBeTruthy();
    expect(within(card()).getByText("0 blockers — ready to submit")).toBeTruthy();
    expect(
      within(card()).getByText("Both gates are clear. Submit is now the primary action."),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Submit" }).getAttribute("aria-disabled")).toBe(
      null,
    );
    expect(screen.queryByRole("link", { name: /^Resolve \d/ })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("who: no Submit or Resolve for a reader who may not submit, or a submitted version", () => {
    const first = renderAll(oppId(), view(MIXED, { canSubmit: false }));
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
    expect(screen.queryByRole("link", { name: /^Resolve \d/ })).toBeNull();
    expect(within(card()).getByText("6 to submit · 0 to Baseline")).toBeTruthy();
    first.unmount();
    renderAll(oppId(), view([], { status: "submitted" }));
    expect(screen.queryByRole("button", { name: "Submit" })).toBeNull();
  });

  it("submitted: the card says so with the date, and nothing blocks", async () => {
    const { container } = renderAll(oppId(), view([], { status: "submitted" }));
    expect(within(card()).getByText("Submitted v3, 14 Oct")).toBeTruthy();
    expect(within(card()).getByText("Submitted versions can't be edited.")).toBeTruthy();
    expect(within(card()).queryByText(/Blockers to submit/)).toBeNull();
    expect(within(card()).queryByText(/ready to submit/)).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("before any Estimate: nothing blocks yet; a failed read says so", () => {
    const first = renderAll(oppId(), view([], { noVersion: true }));
    expect(within(card()).getByText("0 blockers")).toBeTruthy();
    expect(
      within(card()).getByText("Nothing blocks yet. Blockers appear as the pipeline runs."),
    ).toBeTruthy();
    first.unmount();
    renderAll(oppId(), null);
    expect(
      within(card()).getByText(
        "The submission blockers could not be loaded. Try again in a moment.",
      ),
    ).toBeTruthy();
    expect(within(card()).queryByText("0 blockers")).toBeNull();
  });

  it("follows the event stream: the last blocker leaves and ready is announced", async () => {
    const id = oppId();
    const load = vi.fn(async () => view([]));
    renderAll(id, view([blocker("gap", "[GAP 1]")]), load);
    const source = FakeSource.last!;

    await act(async () => source.emit("estimates.assumption.accepted"));

    await waitFor(() =>
      expect(within(card()).getByText("0 blockers — ready to submit")).toBeTruthy(),
    );
    expect(load).toHaveBeenCalledWith(id);
    expect(screen.getByRole("button", { name: "Submit" }).getAttribute("aria-disabled")).toBe(
      null,
    );
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("0 blockers — ready to submit"),
    );
  });

  it("a Review Request frame reads the blockers again (Story 9.1)", async () => {
    const id = oppId();
    const load = vi.fn(async () => view([]));
    renderAll(id, view([]), load);
    await act(async () => FakeSource.last!.emit("reviews.review_request.created"));
    await waitFor(() => expect(load).toHaveBeenCalledWith(id));
  });

  it("a new blocker is announced with the count", async () => {
    const load = vi.fn(async () => view(MIXED.slice(0, 3)));
    renderAll(oppId(), view([]), load);
    await act(async () => FakeSource.last!.emit("gaps.changed"));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("3 blockers before you can submit"),
    );
  });

  it("confirm dialog: Submit Estimate v3? and submitting refreshes", async () => {
    const id = oppId();
    submitEstimateVersion.mockResolvedValue({
      kind: "ok",
      version: {
        id: "00000000-0000-7000-8000-0000000000e3",
        version: 3,
        status: "submitted",
        row_version: 3,
        superseded_count: 0,
      },
    });
    const load = vi.fn(async () => view([], { status: "submitted" }));
    renderAll(id, view([]), load);

    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    const dialog = screen.getByRole("dialog", { name: "Submit Estimate v3?" });
    expect(within(dialog).getByText("Submitted versions can't be edited.")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(await axeViolations(document.body)).toEqual([]);
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit" }));

    expect(submitEstimateVersion).toHaveBeenCalledWith({
      opportunityId: id,
      versionId: "00000000-0000-7000-8000-0000000000e3",
      rowVersion: 2,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(refresh).toHaveBeenCalled();
    expect(load).toHaveBeenCalled();
    // A submitted version offers no Submit.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Submit" })).toBeNull());
  });

  it("a 409 lists the blockers inline and reads them again", async () => {
    submitEstimateVersion.mockResolvedValue({
      kind: "blocked",
      blockers: { to_submit: [blocker("gap", "[REOPENED GAP]")], to_baseline: [] },
      detail: "Resolve 1 blocker before you can submit.",
    });
    const load = vi.fn(async () => view([blocker("gap", "[REOPENED GAP]")]));
    renderAll(oppId(), view([]), load);

    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toContain("Resolve 1 blocker before you can submit.");
    expect(within(alert).getByRole("link", { name: "[REOPENED GAP]" })).toBeTruthy();
    expect(load).toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });
});

describe("Blockers to Baseline (Story 9.1)", () => {
  beforeEach(() => vi.stubGlobal("EventSource", FakeSource));
  afterEach(() => vi.unstubAllGlobals());

  it("in review: each open Review Request is a row linking to it", async () => {
    const id = oppId();
    const base = view([], { status: "submitted" });
    const request: Blocker = {
      kind: "review_request",
      subject_id: "00000000-0000-7000-8000-0000000000d1",
      title: "Engineering review · Ana Ruiz · Pending",
      detail: "Sent 24 Oct · Please check the L3 hours.",
      href: `/opportunities/${id}/estimate?review=00000000-0000-7000-8000-0000000000d1`,
    };
    const { container } = renderAll(id, {
      ...base,
      version: { ...base.version!, status: "in_review" },
      to_baseline: [request],
    });

    expect(within(card()).getByText("0 to submit · 1 to Baseline")).toBeTruthy();
    expect(within(card()).getByText("Blockers to Baseline · 1")).toBeTruthy();
    const link = within(card()).getByRole("link", { name: request.title });
    expect(link.getAttribute("href")).toBe(request.href);
    expect(within(card()).getByText(request.detail)).toBeTruthy();
    expect(within(card()).queryByText(/Blockers to submit/)).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("submitted with no request: No Review Request sent yet", () => {
    renderAll(oppId(), view([], { status: "submitted" }));
    expect(within(card()).getByText("No Review Request sent yet")).toBeTruthy();
  });
});

// --- Story 9.7: the Baseline gate and Set Baseline -------------------------------------------

function sent(
  status: "submitted" | "in_review" | "approved" | "rejected",
  toBaseline: Blocker[],
  { isBaseline = false, canSet = true } = {},
): SubmissionBlockersView {
  return {
    ...view([], { status: "submitted" }),
    version: {
      id: "00000000-0000-7000-8000-0000000000e3",
      version: 3,
      status,
      row_version: 6,
      created_at: "2026-10-04T10:00:00Z",
      submitted_at: "2026-10-14T09:00:00Z",
    },
    to_baseline: toBaseline,
    is_baseline: isBaseline,
    can_set_baseline: canSet,
  };
}

const APPROVER = {
  name: "Ana Reviewer",
  review_type: "engineering" as const,
  status: "approved",
  decided_at: "2026-10-21T09:00:00Z",
  decision_id: "00000000-0000-7000-8000-0000000000d1",
};

describe("Set Baseline and the Baseline gate (Story 9.7)", () => {
  beforeEach(() => {
    refresh.mockReset();
    loadVersionApprovers.mockReset();
    setEstimateBaseline.mockReset();
    loadVersionApprovers.mockResolvedValue({ kind: "ok", approvers: [APPROVER] });
    vi.stubGlobal("EventSource", FakeSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("ready: 0 blockers to Baseline, and Set Baseline is the header's primary action", async () => {
    const { container } = renderAll(oppId(), sent("approved", []));

    expect(within(card()).getByText("0 blockers")).toBeTruthy();
    const ready = card().querySelector("[data-baseline-ready]")!;
    expect(ready.textContent).toContain("0 blockers to Baseline");
    expect(ready.textContent).toContain(
      "Every requested review approved. Set Baseline is now the primary action.",
    );
    expect(ready.querySelector("svg")).not.toBeNull();
    const set = screen.getByRole("button", { name: "Set Baseline" });
    expect(set.getAttribute("aria-disabled")).toBeNull();
    expect(set.className).toContain("bg-primary");
    expect(await axeViolations(container)).toEqual([]);
  });

  it("blocked: aria-disabled with the first blocker as its reason, and the rows", async () => {
    const id = oppId();
    const { container } = renderAll(
      id,
      sent("approved", [
        blocker("conflict", "[CONFLICT]"),
        blocker("no_review_request", "No Review Request sent yet", "v3"),
      ]),
    );

    const set = screen.getByRole("button", { name: "Set Baseline" });
    expect(set.getAttribute("aria-disabled")).toBe("true");
    const reason = document.getElementById(set.getAttribute("aria-describedby")!)!;
    expect(reason.textContent).toBe("[CONFLICT]");
    await userEvent.click(set);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(card()).getByText("Blockers to Baseline · 2")).toBeTruthy();
    const rows = Array.from(card().querySelectorAll<HTMLElement>("[data-blocker]"));
    expect(rows.map((r) => r.getAttribute("data-blocker"))).toEqual([
      "conflict",
      "no_review_request",
    ]);
    expect(within(rows[0]!).getByRole("link", { name: "[CONFLICT]" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("not approved yet: the reason says every review must approve it", () => {
    renderAll(oppId(), sent("in_review", []));
    const set = screen.getByRole("button", { name: "Set Baseline" });
    expect(set.getAttribute("aria-disabled")).toBe("true");
    expect(document.getElementById(set.getAttribute("aria-describedby")!)!.textContent).toBe(
      "Every requested review must approve v3 first.",
    );
  });

  it("a replaced Baseline, a superseded or a rejected version: a true reason", () => {
    const reasonOf = () => {
      const set = screen.getByRole("button", { name: "Set Baseline" });
      expect(set.getAttribute("aria-disabled")).toBe("true");
      return document.getElementById(set.getAttribute("aria-describedby")!)!.textContent;
    };
    const first = renderAll(oppId(), { ...sent("approved", []), baseline_version: 4 });
    expect(reasonOf()).toBe("Only a newer approved Estimate Version can replace the Baseline");
    first.unmount();
    const second = renderAll(oppId(), {
      ...sent("approved", []),
      version: { ...sent("approved", []).version!, status: "superseded" },
    });
    expect(reasonOf()).toBe("v3 is superseded and can't become the Baseline.");
    second.unmount();
    renderAll(oppId(), sent("rejected", [blocker("review_request", "[REQ]")]));
    expect(reasonOf()).toBe("v3 was rejected in review.");
  });

  it("who: no Set Baseline for a reader who may not set it", () => {
    renderAll(oppId(), sent("approved", [], { canSet: false }));
    expect(screen.queryByRole("button", { name: "Set Baseline" })).toBeNull();
  });

  it("the Baseline: the marker in the card, the gate reads it, no Set Baseline", async () => {
    const { container } = renderAll(oppId(), sent("approved", [], { isBaseline: true }));
    const marker = card().querySelector("[data-baseline-pill]")!;
    expect(marker.textContent).toBe("Baseline");
    expect(marker.querySelector("svg")).not.toBeNull();
    expect(within(card()).getByText("Estimate v3 is the Baseline")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Set Baseline" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the dialog: approvers, the warning, and on confirm the announcement and refreshes", async () => {
    const id = oppId();
    setEstimateBaseline.mockResolvedValue({
      kind: "ok",
      baseline: {
        version_id: "00000000-0000-7000-8000-0000000000e3",
        version: 3,
        set_at: "2026-10-26T09:00:00Z",
        set_by_name: "Owner Person",
        previous_version_id: null,
        previous_version: null,
      },
    });
    const load = vi.fn(async () => sent("approved", [], { isBaseline: true }));
    renderAll(id, sent("approved", []), load);

    await userEvent.click(screen.getByRole("button", { name: "Set Baseline" }));
    const dialog = screen.getByRole("dialog", { name: "Set Baseline for Estimate v3?" });
    expect(within(dialog).getByText("Approvers")).toBeTruthy();
    expect(await within(dialog).findByText("Ana Reviewer · Engineering review")).toBeTruthy();
    expect(within(dialog).getByText("Approved 21 Oct 2026")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "This cannot be undone. A Baseline is replaced only by a newer approved version.",
      ),
    ).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(loadVersionApprovers).toHaveBeenCalledWith({
      opportunityId: id,
      versionId: "00000000-0000-7000-8000-0000000000e3",
    });
    expect(await axeViolations(document.body)).toEqual([]);

    await userEvent.click(within(dialog).getByRole("button", { name: "Set Baseline" }));

    expect(setEstimateBaseline).toHaveBeenCalledWith({
      opportunityId: id,
      versionId: "00000000-0000-7000-8000-0000000000e3",
      rowVersion: 6,
    });
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("Estimate v3 is now the Baseline"),
    );
    expect(refresh).toHaveBeenCalled();
    await waitFor(() => expect(load).toHaveBeenCalledWith(id));
    await waitFor(() =>
      expect(within(card()).getByText("Estimate v3 is the Baseline")).toBeTruthy(),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("a 409 lists the blockers inline", async () => {
    setEstimateBaseline.mockResolvedValue({
      kind: "blocked",
      blockers: [blocker("conflict", "[NEW CONFLICT]")],
      detail: "Resolve 1 blocker before you can set the Baseline.",
    });
    renderAll(oppId(), sent("approved", []), vi.fn(async () => sent("approved", [])));

    await userEvent.click(screen.getByRole("button", { name: "Set Baseline" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set Baseline" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toContain("Resolve 1 blocker before you can set the Baseline.");
    expect(within(alert).getByRole("link", { name: "[NEW CONFLICT]" })).toBeTruthy();
    expect(await axeViolations(document.body)).toEqual([]);
  });

  it("a 412 says it changed since you opened it, with Reload", async () => {
    setEstimateBaseline.mockResolvedValue({ kind: "stale" });
    renderAll(oppId(), sent("approved", []), vi.fn(async () => sent("approved", [])));

    await userEvent.click(screen.getByRole("button", { name: "Set Baseline" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set Baseline" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toContain("Changed since you opened it.");
    expect(await axeViolations(document.body)).toEqual([]);
    await userEvent.click(within(alert).getByRole("button", { name: "Reload" }));
    expect(refresh).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
