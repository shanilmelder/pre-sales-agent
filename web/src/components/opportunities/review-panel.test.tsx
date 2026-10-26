import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ReviewPanel } from "@/lib/reviews";
import { axeViolations } from "@/test/axe";
import {
  ANA,
  CY,
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
}));
vi.mock("@/app/opportunities/actions", () => actions);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
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
    const challenge = button("Challenge");
    expect(challenge.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText("Challenge arrives with Story 9.5")).toBeTruthy();
    expect(button("Approve").getAttribute("aria-disabled")).toBeNull();
    for (const pill of container.querySelectorAll("[data-slot=pill]")) {
      expect(pill.querySelector("svg")).not.toBeNull();
      expect(pill.textContent).not.toBe("");
    }
    expect(await axeViolations(container)).toEqual([]);
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
