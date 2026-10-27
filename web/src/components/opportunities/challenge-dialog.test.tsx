import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { axeViolations } from "@/test/axe";
import {
  CHALLENGE_ID,
  REVIEW_OPP,
  RUN_ID,
  challengeSuggestions,
  challengeView,
} from "@/test/review-fixtures";

const actions = vi.hoisted(() => ({
  loadChallengeSuggestions: vi.fn(),
  loadChallenge: vi.fn(),
  raiseChallenge: vi.fn(),
  confirmChallenge: vi.fn(),
  declineChallenge: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => actions);
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), back: vi.fn() }),
  usePathname: () => `/opportunities/${REVIEW_OPP}/assessments`,
}));

import { ShellProviders } from "../shell/shell-context";
import {
  ChallengeButton,
  ChallengeDialog,
  ChallengeForm,
  type ChallengeMode,
} from "./challenge-dialog";

const FINDING = { kind: "finding" as const, id: "00000000-0000-7000-8000-0000000000f9" };

function renderDialog(mode: ChallengeMode, onDone = vi.fn()) {
  const user = userEvent.setup();
  const utils = render(
    <ShellProviders singleKeyShortcuts={false}>
      <ChallengeDialog
        opportunityId={REVIEW_OPP}
        mode={mode}
        open
        onOpenChange={vi.fn()}
        onDone={onDone}
      />
    </ShellProviders>,
  );
  return { user, onDone, ...utils };
}

function renderInline(mode: ChallengeMode, onDone = vi.fn()) {
  const user = userEvent.setup();
  const utils = render(
    <ShellProviders singleKeyShortcuts={false}>
      <ChallengeForm opportunityId={REVIEW_OPP} mode={mode} layout="inline" onDone={onDone} />
    </ShellProviders>,
  );
  return { user, onDone, ...utils };
}

function expectPillsWithIcons(root: ParentNode) {
  for (const pill of root.querySelectorAll("[data-slot=pill]")) {
    expect(pill.querySelector("svg")).not.toBeNull();
    expect(pill.textContent).not.toBe("");
  }
}

const card = (root: HTMLElement, name: RegExp) => within(root).getByRole("button", { name });

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
});

describe("ChallengeDialog, reviewer raising", () => {
  it("shows display-only suggestions and Raise Challenge disabled until a reason", async () => {
    actions.loadChallengeSuggestions.mockResolvedValue({
      kind: "ok",
      value: challengeSuggestions({ title: "Challenge Finding: [FINDING]" }),
    });
    const { user } = renderDialog({ kind: "raise", target: FINDING });

    const dialog = await screen.findByRole("dialog", { name: "Challenge Finding: [FINDING]" });
    const reason = within(dialog).getByLabelText("Reason (required)");
    expect(reason.getAttribute("placeholder")).toBe("State what looks wrong and why.");
    expect(within(dialog).getByRole("heading", { name: "Assessments to rerun" })).toBeTruthy();
    const engineering = card(dialog, /Engineering Agent/);
    expect(engineering.getAttribute("aria-pressed")).toBe("true");
    expect(engineering.getAttribute("aria-disabled")).toBe("true");
    expect(engineering.textContent).toContain("Holds the challenged Finding");
    expect(engineering.textContent).toContain("Suggested");
    const pm = card(dialog, /PM Agent/);
    expect(pm.getAttribute("aria-pressed")).toBe("false");
    expect(pm.textContent).toContain("Optional");
    // Display-only: a click does not tick it.
    await user.click(pm);
    expect(pm.getAttribute("aria-pressed")).toBe("false");
    expect(within(dialog).getByText("Critic and Red Team always rerun")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "A rerun creates a new Estimate Version and shows the delta. Conflict detection, " +
          "Critic and Red Team run again.",
      ),
    ).toBeTruthy();
    const raise = within(dialog).getByRole("button", { name: "Raise Challenge" });
    expect(raise.hasAttribute("disabled")).toBe(true);
    await user.type(reason, "   ");
    expect(raise.hasAttribute("disabled")).toBe(true);
    await user.type(reason, "Retry budget missing");
    expect(raise.hasAttribute("disabled")).toBe(false);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(await axeViolations(dialog)).toEqual([]);
  });

  it("raises and shows the Challenge awaiting confirmation", async () => {
    actions.loadChallengeSuggestions.mockResolvedValue({
      kind: "ok",
      value: challengeSuggestions(),
    });
    actions.raiseChallenge.mockResolvedValue({
      kind: "ok",
      value: challengeView({ can_confirm: false, can_decline: false }),
    });
    const { user, onDone } = renderDialog({ kind: "raise", target: FINDING });
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Reason (required)"), "Too low");
    await user.click(within(dialog).getByRole("button", { name: "Raise Challenge" }));

    expect(actions.raiseChallenge).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      targetKind: "finding",
      targetId: FINDING.id,
      reason: "Too low",
    });
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(within(dialog).getByText("Awaiting confirmation")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeTruthy();
    expectPillsWithIcons(dialog);
  });
});

describe("ChallengeDialog, owner raising", () => {
  it("has editable cards and Rerun N Assessments, raising and confirming at once", async () => {
    actions.loadChallengeSuggestions.mockResolvedValue({
      kind: "ok",
      value: challengeSuggestions({ can_confirm: true }),
    });
    actions.raiseChallenge.mockResolvedValue({
      kind: "ok",
      value: challengeView({
        status: "reassessing",
        status_label: "Reassessing",
        confirmed: ["engineering_agent", "pm_agent"],
        workflow_run_id: RUN_ID,
        run_number: 4,
        can_confirm: false,
        can_decline: false,
      }),
    });
    const { user } = renderDialog({ kind: "raise", target: FINDING });
    const dialog = await screen.findByRole("dialog");

    const primary = within(dialog).getByRole("button", { name: "Rerun 1 Assessment" });
    expect(primary.hasAttribute("disabled")).toBe(true); // no reason yet
    const pm = card(dialog, /PM Agent/);
    expect(pm.getAttribute("aria-disabled")).toBeNull();
    await user.click(pm);
    expect(pm.getAttribute("aria-pressed")).toBe("true");
    const two = within(dialog).getByRole("button", { name: "Rerun 2 Assessments" });
    await user.click(card(dialog, /Engineering Agent/));
    await user.click(pm);
    expect(within(dialog).getByRole("button", { name: "Rerun 0 Assessments" })).toBeTruthy();
    await user.type(within(dialog).getByLabelText("Reason (required)"), "Too low");
    expect(
      within(dialog).getByRole("button", { name: "Rerun 0 Assessments" }).hasAttribute("disabled"),
    ).toBe(true);
    await user.click(card(dialog, /Engineering Agent/));
    await user.click(pm);
    expect(two.hasAttribute("disabled")).toBe(false);
    expect(await axeViolations(dialog)).toEqual([]);

    await user.click(two);
    expect(actions.raiseChallenge).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      targetKind: "finding",
      targetId: FINDING.id,
      reason: "Too low",
      confirmed: ["engineering_agent", "pm_agent"],
    });
    expect(await within(dialog).findByText("Reassessment started (run 4)")).toBeTruthy();
    const link = within(dialog).getByRole("link", { name: "Open Assessments" });
    expect(link.getAttribute("href")).toBe(`/opportunities/${REVIEW_OPP}/assessments`);
    expect(within(dialog).getByText("Reassessing")).toBeTruthy();
    expectPillsWithIcons(dialog);
  });
});

describe("ChallengeForm, owner confirming from the Inbox", () => {
  const existing: ChallengeMode = { kind: "existing", challengeId: CHALLENGE_ID };

  it("shows the reason read-only, Engineering pre-ticked, and starts the run", async () => {
    actions.loadChallenge.mockResolvedValue({ kind: "ok", value: challengeView() });
    actions.confirmChallenge.mockResolvedValue({
      kind: "ok",
      value: challengeView({
        status: "reassessing",
        status_label: "Reassessing",
        confirmed: ["engineering_agent"],
        workflow_run_id: RUN_ID,
        run_number: 4,
        row_version: 2,
        can_confirm: false,
        can_decline: false,
      }),
    });
    const { user, onDone, container } = renderInline(existing);

    expect(
      await screen.findByRole("heading", { name: "Challenge Finding: [FINDING]" }),
    ).toBeTruthy();
    expect(screen.getByText("Reason from Ana Reviewer")).toBeTruthy();
    expect(screen.getByText("[REASON]").tagName).toBe("P");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(card(container as HTMLElement, /Engineering Agent/).getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(screen.getByText("Awaiting confirmation")).toBeTruthy();
    expectPillsWithIcons(container);
    expect(await axeViolations(container)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Rerun 1 Assessment" }));
    expect(actions.confirmChallenge).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      challengeId: CHALLENGE_ID,
      rowVersion: 1,
      confirmed: ["engineering_agent"],
    });
    expect(await screen.findByText("Reassessment started (run 4)")).toBeTruthy();
    expect(onDone).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Decline" })).toBeNull();
  });

  it("Decline reveals a required reason", async () => {
    actions.loadChallenge.mockResolvedValue({ kind: "ok", value: challengeView() });
    actions.declineChallenge.mockResolvedValue({
      kind: "ok",
      value: challengeView({
        status: "declined",
        status_label: "Declined",
        decline_reason: "Covered by R1",
        row_version: 2,
        can_confirm: false,
        can_decline: false,
      }),
    });
    const { user, container } = renderInline(existing);
    await user.click(await screen.findByRole("button", { name: "Decline" }));

    const confirm = screen.getByRole("button", { name: "Confirm decline" });
    expect(confirm.hasAttribute("disabled")).toBe(true);
    const reason = screen.getByLabelText("Reason for declining (required)");
    expect(document.activeElement).toBe(reason);
    expect(await axeViolations(container)).toEqual([]);
    await user.type(reason, "Covered by R1");
    await user.click(confirm);
    expect(actions.declineChallenge).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      challengeId: CHALLENGE_ID,
      rowVersion: 1,
      reason: "Covered by R1",
    });
    expect(await screen.findByText("Covered by R1")).toBeTruthy();
    expect(screen.getByText("Declined")).toBeTruthy();
    expectPillsWithIcons(container);
  });

  it("a superseded version blocks it and Raise on v4 starts a new Challenge", async () => {
    actions.loadChallenge.mockResolvedValue({
      kind: "ok",
      value: challengeView({
        target: {
          kind: "estimate_version",
          id: "00000000-0000-7000-8000-0000000000e3",
          version: 3,
          label: "Estimate v3",
        },
        title: "Challenge Estimate v3",
        superseded_by: 4,
        superseded_by_id: "00000000-0000-7000-8000-0000000000e4",
      }),
    });
    actions.loadChallengeSuggestions.mockResolvedValue({
      kind: "ok",
      value: challengeSuggestions({
        title: "Challenge Estimate v4",
        estimate_version: 4,
        can_confirm: true,
      }),
    });
    const { user, container } = renderInline(existing);

    expect(
      await screen.findByText(
        "v3 is superseded by v4. Raise the Challenge again on v4 if it still applies.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Rerun/ })).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Raise on v4" }));

    expect(await screen.findByRole("heading", { name: "Challenge Estimate v4" })).toBeTruthy();
    expect(actions.loadChallengeSuggestions).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      targetKind: "estimate_version",
      targetId: "00000000-0000-7000-8000-0000000000e4",
    });
    expect((screen.getByLabelText("Reason (required)") as HTMLTextAreaElement).value).toBe(
      "[REASON]",
    );
  });

  it("a 412 shows the inline alert with Reload", async () => {
    actions.loadChallenge.mockResolvedValue({ kind: "ok", value: challengeView() });
    actions.confirmChallenge.mockResolvedValue({ kind: "stale" });
    const { user, container } = renderInline(existing);
    await user.click(await screen.findByRole("button", { name: "Rerun 1 Assessment" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Changed since you opened it.");
    expect(await axeViolations(container)).toEqual([]);
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(actions.loadChallenge).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("a 409 shows the API's sentence", async () => {
    actions.loadChallenge.mockResolvedValue({ kind: "ok", value: challengeView() });
    actions.confirmChallenge.mockResolvedValue({
      kind: "invalid",
      detail: "An assessment is already running for this Opportunity.",
      code: "assessment_in_progress",
    });
    const { user } = renderInline(existing);
    await user.click(await screen.findByRole("button", { name: "Rerun 1 Assessment" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "An assessment is already running for this Opportunity.",
    );
  });

  it("says when the Challenge can't be loaded", async () => {
    actions.loadChallenge.mockResolvedValue({ kind: "not-found" });
    renderInline(existing);
    expect((await screen.findByRole("alert")).textContent).toBe(
      "The Challenge could not be loaded. Try again in a moment.",
    );
  });
});

describe("ChallengeButton", () => {
  it("opens the dialog on its target", async () => {
    actions.loadChallengeSuggestions.mockResolvedValue({
      kind: "ok",
      value: challengeSuggestions({ title: "Challenge Engineering Assessment v2" }),
    });
    const user = userEvent.setup();
    render(
      <ShellProviders singleKeyShortcuts={false}>
        <ChallengeButton
          opportunityId={REVIEW_OPP}
          target={{ kind: "assessment", id: "00000000-0000-7000-8000-0000000000aa" }}
        />
      </ShellProviders>,
    );
    await user.click(screen.getByRole("button", { name: "Challenge" }));
    expect(
      await screen.findByRole("dialog", { name: "Challenge Engineering Assessment v2" }),
    ).toBeTruthy();
    expect(actions.loadChallengeSuggestions).toHaveBeenCalledWith({
      opportunityId: REVIEW_OPP,
      targetKind: "assessment",
      targetId: "00000000-0000-7000-8000-0000000000aa",
    });
  });
});
