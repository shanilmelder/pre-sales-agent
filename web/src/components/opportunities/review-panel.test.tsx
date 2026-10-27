import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewPanel } from "@/lib/reviews";
import { axeViolations } from "@/test/axe";
import {
  ANA,
  CY,
  OWNER,
  challengeSuggestions,
  challengeView,
  REVIEW_ID,
  REVIEW_OPP,
  recorded,
  reviewDecision,
  reviewPanel,
  reviewRequest,
  reviewedAssessment,
} from "@/test/review-fixtures";

const actions = vi.hoisted(() => ({
  decideReviewRequest: vi.fn(),
  loadReviewPanel: vi.fn(),
  replyToReviewRequest: vi.fn(),
  createEstimateVersion: vi.fn(),
  loadEvidenceOptions: vi.fn(),
  loadVersionApprovers: vi.fn(),
  setEstimateBaseline: vi.fn(),
  addSource: vi.fn(),
  addTextSource: vi.fn(),
  loadChallengeSuggestions: vi.fn(),
  raiseChallenge: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => actions);
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
    back: vi.fn(),
    refresh: vi.fn(),
  }),
  usePathname: () => `/opportunities/${REVIEW_OPP}/estimate`,
}));

import { ShellProviders } from "../shell/shell-context";
import { ReviewPanelLoader, ReviewPanelView, type PanelLayout } from "./review-panel";

function renderPanel(
  panel: ReviewPanel = reviewPanel(),
  { layout = "inspector" as PanelLayout, onReload = vi.fn(), onDecided = vi.fn() } = {},
) {
  const user = userEvent.setup();
  const utils = render(
    <ShellProviders singleKeyShortcuts={false}>
      <ReviewPanelView
        opportunityId={REVIEW_OPP}
        panel={panel}
        layout={layout}
        onReload={onReload}
        onDecided={onDecided}
      />
    </ShellProviders>,
  );
  return { user, onReload, onDecided, ...utils };
}

const actionsGroup = () => screen.queryByRole("group", { name: "Review decision" });
const button = (name: string) => screen.getByRole("button", { name });

beforeEach(() => {
  actions.decideReviewRequest.mockReset();
  actions.loadReviewPanel.mockReset();
  actions.replyToReviewRequest.mockReset();
  actions.createEstimateVersion.mockReset();
  actions.loadEvidenceOptions.mockReset();
  actions.loadEvidenceOptions.mockResolvedValue({ kind: "ok", items: [] });
  actions.loadChallengeSuggestions.mockReset();
  actions.raiseChallenge.mockReset();
});

describe("ReviewPanelView", () => {
  it("shows the header, the target and both action rows, with no violations", async () => {
    const { container } = renderPanel();
    expect(
      screen.getByText("Engineering review · From Owner Person · 24 Oct 2026"),
    ).toBeTruthy();
    expect(
      screen.getByRole("heading", { name: "Review request: Estimate v3, [OPPORTUNITY]" }),
    ).toBeTruthy();
    expect(screen.getByText("Please check the integration hours.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open in tab" }).getAttribute("href")).toBe(
      `/opportunities/${REVIEW_OPP}/estimate/reviews/${REVIEW_ID}`,
    );
    // The target: lines, totals, Assumptions, and the diff behind View diff.
    const lines = screen.getByRole("region", { name: "Estimate lines" });
    expect(within(lines).getByText("[LINE 1]")).toBeTruthy();
    expect(screen.getByText("56.0 h", { selector: "span.text-body-strong" })).toBeTruthy();
    const register = screen.getByRole("region", { name: "Assumptions Register" });
    expect(within(register).getByText("[CONTINGENCY]")).toBeTruthy();
    expect(screen.getByText("Compared with v2")).toBeTruthy();

    const group = actionsGroup()!;
    const names = within(group)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(names).toEqual([
      "Approve",
      "Reject",
      "Challenge",
      "Request evidence",
      "Request alternative",
      "Escalate",
    ]);
    // Story 9.5: Challenge opens the Challenge dialog.
    expect(button("Challenge").getAttribute("aria-disabled")).toBeNull();
    expect(button("Approve").getAttribute("aria-disabled")).toBeNull();
    for (const pill of container.querySelectorAll("[data-slot=pill]")) {
      expect(pill.querySelector("svg")).not.toBeNull();
      expect(pill.textContent).not.toBe("");
    }
    expect(await axeViolations(container)).toEqual([]);
  });

  it("Challenge opens the dialog: display-only cards, Raise Challenge after a reason", async () => {
    actions.loadChallengeSuggestions.mockResolvedValue({
      kind: "ok",
      value: challengeSuggestions(),
    });
    actions.raiseChallenge.mockResolvedValue({ kind: "ok", value: challengeView() });
    const { user, onReload } = renderPanel();

    await user.click(button("Challenge"));
    const dialog = await screen.findByRole("dialog", { name: "Challenge Estimate v3" });
    expect(actions.loadChallengeSuggestions).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      targetKind: "estimate_version",
      targetId: "00000000-0000-7000-8000-0000000000e3",
    });
    const card = within(dialog).getByRole("button", { name: /Engineering Agent/ });
    expect(card.getAttribute("aria-pressed")).toBe("true");
    expect(card.getAttribute("aria-disabled")).toBe("true");
    const raise = within(dialog).getByRole("button", { name: "Raise Challenge" });
    expect(raise.hasAttribute("disabled")).toBe(true);
    await user.type(within(dialog).getByLabelText("Reason (required)"), "L3 is too low");
    expect(raise.hasAttribute("disabled")).toBe(false);
    await user.click(raise);
    expect(actions.raiseChallenge).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      targetKind: "estimate_version",
      targetId: "00000000-0000-7000-8000-0000000000e3",
      reason: "L3 is too low",
      reviewRequestId: REVIEW_ID,
    });
    await waitFor(() => expect(onReload).toHaveBeenCalled());
  });

  it("View diff lists the changed lines and the total delta", async () => {
    const { user } = renderPanel();
    await user.click(button("View diff"));
    const diff = screen.getByRole("region", { name: "Version diff" });
    expect(within(diff).getByText("Compared with v2: total +12 h", { exact: false })).toBeTruthy();
    expect(diff.querySelector("[data-diff-change=changed]")?.textContent).toContain("+12 h");
    expect(button("Hide diff").getAttribute("aria-expanded")).toBe("true");
  });

  it("says First version when there is none before", () => {
    renderPanel(
      reviewPanel({
        diff: {
          version: 1,
          previous_version: null,
          first: true,
          lines: [],
          total_before: null,
          total_after: 56,
          total_delta: 0,
        },
      }),
    );
    expect(screen.getAllByText("First version").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "View diff" })).toBeNull();
  });

  it("a non-Approve action needs a reason before Confirm, and Cancel collapses it", async () => {
    const value = recorded(
      { decision: "rejected", label: "Rejected", reason: "No basis" },
      { status: "rejected" },
      "rejected",
    );
    actions.decideReviewRequest.mockResolvedValue({ kind: "ok", value });
    const { user, onDecided, container } = renderPanel();

    await user.click(button("Reject"));
    const reason = screen.getByLabelText("Reason for rejecting (required)");
    expect(document.activeElement).toBe(reason);
    expect((button("Confirm Reject") as HTMLButtonElement).disabled).toBe(true);
    expect(await axeViolations(container)).toEqual([]);
    await user.click(button("Cancel"));
    expect(screen.queryByLabelText("Reason for rejecting (required)")).toBeNull();

    await user.click(button("Reject"));
    await user.type(screen.getByLabelText("Reason for rejecting (required)"), "   ");
    expect((button("Confirm Reject") as HTMLButtonElement).disabled).toBe(true);
    await user.type(screen.getByLabelText("Reason for rejecting (required)"), "No basis");
    await user.click(button("Confirm Reject"));

    await waitFor(() => expect(onDecided).toHaveBeenCalledWith(value));
    expect(actions.decideReviewRequest).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      requestId: REVIEW_ID,
      rowVersion: 1,
      decision: "rejected",
      reason: "   No basis",
    });
    expect(await screen.findByText("Review rejected")).toBeTruthy();
  });

  it.each([
    ["Request evidence", "Reason for requesting evidence (required)", "Confirm Request evidence"],
    [
      "Request alternative",
      "Reason for requesting an alternative (required)",
      "Confirm Request alternative",
    ],
  ])("%s reveals its reason", async (action, label, confirm) => {
    const { user } = renderPanel();
    await user.click(button(action));
    expect(screen.getByLabelText(label)).toBeTruthy();
    expect(button(action).getAttribute("aria-pressed")).toBe("true");
    expect((button(confirm) as HTMLButtonElement).disabled).toBe(true);
  });

  it("Escalate needs a reason and a reviewer from the candidates", async () => {
    actions.decideReviewRequest.mockResolvedValue({
      kind: "ok",
      value: recorded(
        { decision: "escalated", label: "Escalated", escalated_to: CY },
        { reviewer: CY },
      ),
    });
    const { user, container } = renderPanel();
    await user.click(button("Escalate"));
    await user.type(screen.getByLabelText("Reason for escalating (required)"), "Needs Cy");
    expect((button("Confirm Escalate") as HTMLButtonElement).disabled).toBe(true);
    const select = screen.getByLabelText("Choose a reviewer");
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose a reviewer",
      "Cy Reviewer",
    ]);
    expect(await axeViolations(container)).toEqual([]);
    await user.selectOptions(select, CY.id);
    await user.click(button("Confirm Escalate"));
    await waitFor(() =>
      expect(actions.decideReviewRequest).toHaveBeenCalledWith(
        expect.objectContaining({ decision: "escalated", escalatedTo: CY.id }),
      ),
    );
    expect(await screen.findByText("Review escalated to Cy Reviewer")).toBeTruthy();
  });

  it("Approve records at once and announces the approved version", async () => {
    actions.decideReviewRequest.mockResolvedValue({
      kind: "ok",
      value: recorded(
        { decision: "approved", label: "Approved", reason: null },
        { status: "approved" },
        "approved",
      ),
    });
    const { user, onDecided } = renderPanel();
    await user.click(button("Approve"));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    expect(actions.decideReviewRequest).toHaveBeenCalledWith(
      expect.objectContaining({ decision: "approved", reason: "" }),
    );
    expect(await screen.findByText("Estimate v3 approved")).toBeTruthy();
  });

  it("locks Approve for the author, with the inline hint", async () => {
    const { user, container } = renderPanel(
      reviewPanel({
        can_approve: false,
        approve_blocked_reason: "You authored v3, so you can't approve it.",
      }),
    );
    const approve = button("Approve");
    expect(approve.getAttribute("aria-disabled")).toBe("true");
    const hint = screen.getByText("You authored v3, so you can't approve it.");
    expect(approve.getAttribute("aria-describedby")).toBe(hint.id);
    await user.click(approve);
    expect(actions.decideReviewRequest).not.toHaveBeenCalled();
    expect(button("Reject")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("is read only without can_decide, and shows the latest decision", async () => {
    const latest = reviewDecision();
    const { container } = renderPanel(
      reviewPanel({
        can_decide: false,
        can_approve: false,
        escalation_candidates: [],
        decisions: [latest],
        request: reviewRequest({ latest_decision: latest }),
      }),
    );
    expect(actionsGroup()).toBeNull();
    const entry = container.querySelector(`[data-decision-entry="${latest.id}"]`)!;
    expect(entry.textContent).toContain("Evidence requested");
    expect(entry.textContent).toContain(`${ANA.name} · Evidence requested · 25 Oct, 10:02`);
    expect(entry.textContent).toContain("[REASON]");
    expect(entry.querySelector("svg")).not.toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("greys a superseded panel with its link and no actions", async () => {
    const { container } = renderPanel(
      reviewPanel({ version_status: "superseded", superseded_by: 4 }),
    );
    expect(container.querySelector("[data-greyed]")).not.toBeNull();
    expect(container.querySelector(".opacity-60")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Superseded by v4" }).getAttribute("href")).toBe(
      `/opportunities/${REVIEW_OPP}/estimate`,
    );
    expect(actionsGroup()).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("a 412 shows who changed it, with Reload and View diff, and records nothing", async () => {
    actions.decideReviewRequest.mockResolvedValue({
      kind: "stale",
      detail: "Changed by Ana Reviewer since you opened it.",
    });
    const { user, onReload, onDecided, container } = renderPanel();
    await user.click(button("Approve"));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Changed by Ana Reviewer since you opened it.");
    expect(onDecided).not.toHaveBeenCalled();
    expect(await axeViolations(container)).toEqual([]);
    await user.click(within(alert).getByRole("button", { name: "View diff" }));
    expect(container.querySelector("[data-version-diff]")).not.toBeNull();
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    expect(onReload).toHaveBeenCalled();
  });

  it("shows another refusal's sentence inline", async () => {
    actions.decideReviewRequest.mockResolvedValue({
      kind: "forbidden",
      detail: "You authored v3, so you can't approve it.",
    });
    const { user } = renderPanel();
    await user.click(button("Approve"));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "You authored v3, so you can't approve it.",
    );
  });

  it("shows an Assessment's Findings with their Evidence chips", async () => {
    const { container } = renderPanel(
      reviewPanel({
        estimate: null,
        diff: null,
        assessment: reviewedAssessment(),
        request: reviewRequest({
          review_type: "security",
          target: {
            kind: "assessment",
            id: "00000000-0000-7000-8000-0000000005a2",
            version: 2,
            label: "Security Assessment v2",
          },
        }),
      }),
    );
    expect(
      screen.getByRole("heading", {
        name: "Review request: Security Assessment v2, [OPPORTUNITY]",
      }),
    ).toBeTruthy();
    expect(screen.getByText("Security Assessment v2", { selector: "span" })).toBeTruthy();
    const findings = screen.getByRole("region", { name: "Findings" });
    expect(within(findings).getByText("[FINDING]")).toBeTruthy();
    expect(within(findings).getByText("High")).toBeTruthy();
    expect(within(within(findings).getByRole("list", { name: "Evidence" })).getByText("R4")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("has no Open in tab on the full-width page", () => {
    renderPanel(reviewPanel(), { layout: "page" });
    expect(screen.queryByRole("link", { name: "Open in tab" })).toBeNull();
    expect(screen.getByRole("heading", { level: 2 })).toBeTruthy();
  });
});

describe("ReviewPanelLoader", () => {
  it("reads the panel and keeps the decision without a read", async () => {
    actions.loadReviewPanel.mockResolvedValue({ kind: "ok", panel: reviewPanel() });
    actions.decideReviewRequest.mockResolvedValue({
      kind: "ok",
      value: recorded(
        { decision: "approved", label: "Approved", reason: null },
        { status: "approved" },
        "approved",
      ),
    });
    const user = userEvent.setup();
    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ReviewPanelLoader opportunityId={REVIEW_OPP} requestId={REVIEW_ID} layout="inspector" />
      </ShellProviders>,
    );
    expect(screen.getByText("Loading the review…")).toBeTruthy();
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(actionsGroup()).toBeNull());
    expect(screen.getAllByText("Approved").length).toBeGreaterThan(0);
    expect(actions.loadReviewPanel).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      requestId: REVIEW_ID,
    });
  });

  function renderLoader() {
    actions.loadReviewPanel.mockResolvedValue({ kind: "ok", panel: reviewPanel() });
    const user = userEvent.setup();
    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ReviewPanelLoader opportunityId={REVIEW_OPP} requestId={REVIEW_ID} layout="inspector" />
      </ShellProviders>,
    );
    return user;
  }

  it("after an escalation the actions are gone (the request is someone else's)", async () => {
    actions.decideReviewRequest.mockResolvedValue({
      kind: "ok",
      value: recorded(
        { decision: "escalated", label: "Escalated", escalated_to: CY },
        { reviewer: CY },
      ),
    });
    const user = renderLoader();
    await user.click(await screen.findByRole("button", { name: "Escalate" }));
    await user.type(screen.getByLabelText("Reason for escalating (required)"), "Needs Cy");
    await user.selectOptions(screen.getByLabelText("Choose a reviewer"), CY.id);
    await user.click(button("Confirm Escalate"));
    await waitFor(() => expect(actionsGroup()).toBeNull());
    expect(screen.getByText("Reviewer: Cy Reviewer")).toBeTruthy();
  });

  it("after Request evidence, Approve sends the new row version", async () => {
    actions.decideReviewRequest
      .mockResolvedValueOnce({ kind: "ok", value: recorded({}, { row_version: 2 }) })
      .mockResolvedValueOnce({
        kind: "ok",
        value: recorded(
          { id: "00000000-0000-7000-8000-0000000000d2", decision: "approved", label: "Approved" },
          { status: "approved", row_version: 3 },
          "approved",
        ),
      });
    const user = renderLoader();
    await user.click(await screen.findByRole("button", { name: "Request evidence" }));
    await user.type(screen.getByLabelText("Reason for requesting evidence (required)"), "Why");
    await user.click(button("Confirm Request evidence"));
    await waitFor(() => expect(actions.decideReviewRequest).toHaveBeenCalledTimes(1));
    expect(actions.decideReviewRequest.mock.calls[0]![0].rowVersion).toBe(1);
    await user.click(await screen.findByRole("button", { name: "Approve" }));
    await waitFor(() => expect(actions.decideReviewRequest).toHaveBeenCalledTimes(2));
    expect(actions.decideReviewRequest.mock.calls[1]![0]).toEqual(
      expect.objectContaining({ decision: "approved", rowVersion: 2 }),
    );
  });

  it("switching actions clears the typed reason", async () => {
    const user = renderLoader();
    await user.click(await screen.findByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText("Reason for rejecting (required)"), "No basis");
    await user.click(button("Escalate"));
    expect(
      (screen.getByLabelText("Reason for escalating (required)") as HTMLTextAreaElement).value,
    ).toBe("");
  });

  it("shows the fallback when the panel can't be read", async () => {
    actions.loadReviewPanel.mockResolvedValue({ kind: "not-found" });
    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ReviewPanelLoader
          opportunityId={REVIEW_OPP}
          requestId={REVIEW_ID}
          layout="inbox"
          fallback={<p>[FALLBACK]</p>}
        />
      </ShellProviders>,
    );
    expect(await screen.findByText("[FALLBACK]")).toBeTruthy();
    await waitFor(() => expect(actions.loadReviewPanel).toHaveBeenCalled());
    expect(screen.queryByRole("group", { name: "Review decision" })).toBeNull();
  });

  it("says when a first read fails without a fallback", async () => {
    actions.loadReviewPanel.mockResolvedValue({ kind: "error" });
    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ReviewPanelLoader opportunityId={REVIEW_OPP} requestId={REVIEW_ID} layout="inspector" />
      </ShellProviders>,
    );
    expect(
      await screen.findByText("The review could not be loaded. Try again in a moment."),
    ).toBeTruthy();
  });
});

// --- the author's side (Story 9.4) ----------------------------------------------------------

const V4 = { id: "00000000-0000-7000-8000-0000000000e4", version: 4 };

function authorPanel(overrides: Partial<ReviewPanel> = {}): ReviewPanel {
  const asked = reviewDecision();
  return reviewPanel({
    request: reviewRequest({ latest_decision: asked, row_version: 2 }),
    decisions: [asked],
    can_decide: false,
    can_approve: false,
    escalation_candidates: [],
    is_author: true,
    can_reply: true,
    ...overrides,
  });
}

function expectIconAndText(container: HTMLElement) {
  const rows = container.querySelectorAll("[data-outcome]");
  expect(rows.length).toBeGreaterThan(0);
  for (const row of rows) {
    expect(row.querySelector("svg")).not.toBeNull();
    expect(row.textContent).not.toBe("");
  }
}

describe("ReviewPanelView, the author's side", () => {
  it("replies with Evidence: the composer, the outcomes, and no reviewer actions", async () => {
    const reply = {
      id: "00000000-0000-7000-8000-0000000000f2",
      message: "See R4",
      evidence: [],
      alternative: null,
      replied_by: OWNER,
      replied_at: "2026-10-25T11:00:00Z",
    };
    actions.replyToReviewRequest.mockResolvedValue({
      kind: "ok",
      value: { reply, request: reviewRequest({ row_version: 3 }) },
    });
    const onReplied = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <ShellProviders singleKeyShortcuts={false}>
        <ReviewPanelView
          opportunityId={REVIEW_OPP}
          panel={authorPanel()}
          layout="inbox"
          onReload={vi.fn()}
          onDecided={vi.fn()}
          onReplied={onReplied}
        />
      </ShellProviders>,
    );

    expect(actionsGroup()).toBeNull();
    const outcomes = screen.getByRole("region", { name: "Review outcomes" });
    expect(within(outcomes).getByText("Ana Reviewer")).toBeTruthy();
    expect(within(outcomes).getByText(/Evidence requested/)).toBeTruthy();
    expectIconAndText(container);
    expect(button("Reply").hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: "Link as alternative" })).toBeNull();
    expect(button("Add Source")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.type(screen.getByLabelText("Reply to Ana Reviewer (required)"), "  See R4 ");
    await user.click(button("Reply"));

    expect(actions.replyToReviewRequest).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      requestId: REVIEW_ID,
      rowVersion: 2,
      message: "  See R4 ",
      evidence: [],
    });
    await waitFor(() => expect(onReplied).toHaveBeenCalled());
  });

  it("links the draft as the alternative when asked for one", async () => {
    const asked = reviewDecision({
      decision: "alternative_requested",
      label: "Alternative requested",
    });
    actions.replyToReviewRequest.mockResolvedValue({ kind: "error" });
    const { user, container } = renderPanel(
      authorPanel({
        decisions: [asked],
        request: reviewRequest({ latest_decision: asked, row_version: 2 }),
        can_link_alternative: true,
        alternative_draft: V4,
      }),
    );
    const link = button("Link as alternative");
    expect(link.getAttribute("aria-pressed")).toBe("false");
    await user.click(link);
    expect(link.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByLabelText("Alternative draft")).toBeTruthy();
    expect(screen.getByRole("option", { name: "Draft v4" })).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);

    await user.type(screen.getByLabelText("Reply to Ana Reviewer (required)"), "v4 splits L1");
    await user.click(button("Reply"));
    expect(actions.replyToReviewRequest.mock.calls[0]![0].alternativeVersionId).toBe(V4.id);
    expect(await screen.findByRole("alert")).toBeTruthy();
  });

  it("shows who an escalation went to, with the reason", async () => {
    const escalated = reviewDecision({
      decision: "escalated",
      label: "Escalated",
      reason: "[WHY]",
      escalated_to: CY,
    });
    const { container } = renderPanel(
      authorPanel({
        decisions: [escalated],
        request: reviewRequest({ latest_decision: escalated, reviewer: CY }),
        can_reply: false,
        escalated_to: CY,
      }),
    );
    expect(container.querySelector("[data-escalated-to]")?.textContent).toBe(
      "Escalated to Cy Reviewer",
    );
    expect(screen.getAllByText("[WHY]").length).toBeGreaterThan(0);
    expect(screen.queryByRole("group", { name: "Reply" })).toBeNull();
    expect(actionsGroup()).toBeNull();
    expectIconAndText(container);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("on an approved version offers Set Baseline beside the sentence (Story 9.7)", async () => {
    const approved = reviewDecision({ decision: "approved", label: "Approved", reason: null });
    actions.loadVersionApprovers.mockResolvedValue({
      kind: "ok",
      approvers: [
        {
          name: "Ana Reviewer",
          review_type: "engineering",
          status: "approved",
          decided_at: "2026-10-21T09:00:00Z",
          decision_id: "00000000-0000-7000-8000-0000000000d1",
        },
      ],
    });
    actions.setEstimateBaseline.mockResolvedValue({
      kind: "ok",
      baseline: {
        version_id: "v3",
        version: 3,
        set_at: "2026-10-26T09:00:00Z",
        set_by_name: "Owner Person",
        previous_version_id: null,
        previous_version: null,
      },
    });
    const gate = {
      version_id: "00000000-0000-7000-8000-0000000000e3",
      version: 3,
      status: "approved" as const,
      row_version: 5,
      is_baseline: false,
      to_baseline: [],
      can_set_baseline: true,
    };
    const { user, container, onReload } = renderPanel(
      authorPanel({
        decisions: [approved],
        request: reviewRequest({ latest_decision: approved, status: "approved" }),
        version_status: "approved",
        can_reply: false,
        version_gate: gate,
      }),
    );
    expect(screen.getByText("All requested reviews approved. Baseline can be set.")).toBeTruthy();
    expectIconAndText(container);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Set Baseline" }));
    const dialog = await screen.findByRole("dialog", { name: "Set Baseline for Estimate v3?" });
    expect(await within(dialog).findByText("Ana Reviewer · Engineering review")).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Set Baseline" }));
    await waitFor(() => expect(onReload).toHaveBeenCalled());
    expect(actions.setEstimateBaseline).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      versionId: gate.version_id,
      rowVersion: 5,
    });
  });

  it("on the Baseline version shows the marker and no Set Baseline", async () => {
    const approved = reviewDecision({ decision: "approved", label: "Approved", reason: null });
    const { container } = renderPanel(
      authorPanel({
        decisions: [approved],
        request: reviewRequest({ latest_decision: approved, status: "approved" }),
        version_status: "approved",
        can_reply: false,
        version_gate: {
          version_id: "00000000-0000-7000-8000-0000000000e3",
          version: 3,
          status: "approved",
          row_version: 5,
          is_baseline: true,
          to_baseline: [],
          can_set_baseline: true,
        },
      }),
    );
    const marker = container.querySelector("[data-baseline-pill]");
    expect(marker?.textContent).toBe("v3 · Baseline");
    expect(marker?.querySelector("svg")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /Set Baseline/ })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("on a rejected version offers New version", async () => {
    const rejected = reviewDecision({ decision: "rejected", label: "Rejected", reason: "[WHY]" });
    actions.createEstimateVersion.mockResolvedValue({
      kind: "ok",
      value: { ...V4, status: "draft", row_version: 1, base_version_id: "b", base_version: 3 },
    });
    const { user, onReload, container } = renderPanel(
      authorPanel({
        decisions: [rejected],
        request: reviewRequest({ latest_decision: rejected, status: "rejected" }),
        version_status: "rejected",
        can_reply: false,
        can_create_version: true,
      }),
    );
    expect(await axeViolations(container)).toEqual([]);
    await user.click(button("New version"));
    expect(actions.createEstimateVersion).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      versionId: reviewRequest().estimate_version_id,
    });
    await waitFor(() => expect(onReload).toHaveBeenCalled());
  });

  it("greys a superseded request with no actions", async () => {
    const { container } = renderPanel(
      authorPanel({
        request: reviewRequest({ status: "superseded", latest_decision: reviewDecision() }),
        version_status: "superseded",
        superseded_by: 4,
        can_reply: false,
      }),
    );
    expect(container.querySelector("[data-greyed]")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Superseded by v4" })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Reply" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New version" })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("ReviewPanelView, the reviewer's side (Story 9.4)", () => {
  it("shows the replies with their Evidence and the request this is the alternative to", async () => {
    const original = "00000000-0000-7000-8000-0000000000c0";
    const { container } = renderPanel(
      reviewPanel({
        decisions: [reviewDecision()],
        replies: [
          {
            id: "00000000-0000-7000-8000-0000000000f3",
            message: "[REPLY]",
            evidence: [{ kind: "requirement", id: "e", version: 1, label: "R4" }],
            alternative: null,
            replied_by: OWNER,
            replied_at: "2026-10-25T11:00:00Z",
          },
        ],
        linked_request: { id: original, version_number: 3 },
      }),
    );
    expect(
      screen.getByRole("link", { name: "Alternative to the v3 request" }).getAttribute("href"),
    ).toBe(`/opportunities/${REVIEW_OPP}/estimate/reviews/${original}`);
    const outcomes = screen.getByRole("region", { name: "Review outcomes" });
    expect(within(outcomes).getByText("[REPLY]")).toBeTruthy();
    expect(within(outcomes).getByText("R4")).toBeTruthy();
    expect(actionsGroup()).not.toBeNull();
    expectIconAndText(container);
    expect(await axeViolations(container)).toEqual([]);
  });
});

describe("Story 9.4 review follow-ups", () => {
  it("after a request for an alternative, New version sits next to Reply", async () => {
    const asked = reviewDecision({
      decision: "alternative_requested",
      label: "Alternative requested",
    });
    const { container } = renderPanel(
      authorPanel({
        decisions: [asked],
        request: reviewRequest({ latest_decision: asked }),
        can_create_version: true,
      }),
    );
    const composer = screen.getByRole("group", { name: "Reply" });
    expect(within(composer).getByRole("button", { name: "New version" })).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "New version" })).toHaveLength(1);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("the loader shows the reply, and a second reply sends the recorded row version", async () => {
    const reply = (id: string, message: string) => ({
      id,
      message,
      evidence: [],
      alternative: null,
      replied_by: OWNER,
      replied_at: "2026-10-25T11:00:00Z",
    });
    actions.replyToReviewRequest
      .mockResolvedValueOnce({
        kind: "ok",
        value: {
          reply: reply("00000000-0000-7000-8000-0000000000f4", "[FIRST]"),
          request: reviewRequest({ row_version: 7, latest_decision: reviewDecision() }),
        },
      })
      .mockResolvedValueOnce({ kind: "error" });
    const user = userEvent.setup();
    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ReviewPanelLoader
          opportunityId={REVIEW_OPP}
          requestId={REVIEW_ID}
          layout="inspector"
          initial={authorPanel()}
          live={false}
        />
      </ShellProviders>,
    );
    const field = () => screen.getByLabelText("Reply to Ana Reviewer (required)");

    await user.type(field(), "First reply");
    await user.click(button("Reply"));
    const outcomes = screen.getByRole("region", { name: "Review outcomes" });
    expect(await within(outcomes).findByText("[FIRST]")).toBeTruthy();

    await user.type(field(), "Second reply");
    await user.click(button("Reply"));
    expect(actions.replyToReviewRequest.mock.calls[1]![0].rowVersion).toBe(7);
  });
});
