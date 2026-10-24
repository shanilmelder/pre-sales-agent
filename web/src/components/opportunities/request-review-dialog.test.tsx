import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SearchResult } from "@/app/opportunities/actions";
import type { AssessmentOption } from "@/lib/reviews";
import { axeViolations } from "@/test/axe";

const requestReview = vi.hoisted(() => vi.fn());
const searchReviewerCandidates = vi.hoisted(() =>
  vi.fn<(input: { reviewType: string; q: string }) => Promise<SearchResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({ requestReview, searchReviewerCandidates }));

import { LiveRegionProvider } from "../shell/live-region";
import { RequestReviewDialog } from "./request-review-dialog";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const VERSION = { id: "00000000-0000-7000-8000-0000000000e3", version: 3, row_version: 4 };
const ANA = { id: "00000000-0000-7000-8000-0000000000a1", name: "Ana Ruiz", email: "ana@ex.test" };
const BEN = { id: "00000000-0000-7000-8000-0000000000a2", name: "Ben Ode", email: "ben@ex.test" };
const CY = { id: "00000000-0000-7000-8000-0000000000a3", name: "Cy Sec", email: "cy@ex.test" };
const ASSESSMENTS: AssessmentOption[] = [
  {
    id: "00000000-0000-7000-8000-0000000000b1",
    agent: "engineering_agent",
    version: 2,
    label: "Engineering Assessment v2",
  },
  {
    id: "00000000-0000-7000-8000-0000000000b2",
    agent: "security_agent",
    version: 1,
    label: "Security Assessment v1",
  },
];

function renderDialog(onSent = vi.fn()) {
  const result = render(
    <LiveRegionProvider>
      <RequestReviewDialog
        opportunityId={OPP_ID}
        version={VERSION}
        assessments={ASSESSMENTS}
        onSent={onSent}
      />
    </LiveRegionProvider>,
  );
  return { ...result, onSent };
}

beforeEach(() => {
  requestReview.mockReset();
  searchReviewerCandidates.mockReset();
  searchReviewerCandidates.mockImplementation(async ({ reviewType }) => ({
    kind: "ok",
    users: reviewType === "security" ? [CY] : [ANA, BEN],
  }));
});

describe("Request review (Story 9.1)", () => {
  it("opens the 520px dialog with the type, reviewers, Assessments and message", async () => {
    const user = userEvent.setup();
    const { baseElement } = renderDialog();

    await user.click(screen.getByRole("button", { name: "Request review" }));
    const dialog = await screen.findByRole("dialog", { name: "Request review of Estimate v3" });
    expect(within(dialog).getByRole("radio", { name: "Engineering" })).toHaveProperty(
      "checked",
      true,
    );
    expect(within(dialog).getByRole("radio", { name: "PM" })).toBeTruthy();
    expect(within(dialog).getByRole("radio", { name: "Security" })).toBeTruthy();
    const cards = within(dialog).getAllByRole("button", { pressed: false });
    expect(cards.map((c) => c.textContent)).toEqual([
      "Engineering Assessment v2",
      "Security Assessment v1",
    ]);
    expect(
      within(dialog).getByText("Leave all unticked to review the whole Estimate Version."),
    ).toBeTruthy();
    expect(within(dialog).getByLabelText("Message (optional)")).toBeTruthy();
    const send = within(dialog).getByRole("button", { name: "Send requests" });
    expect(send).toHaveProperty("disabled", true);
    expect(await axeViolations(baseElement)).toEqual([]);
  });

  it("sends one request per reviewer and picked Assessment, then announces", async () => {
    const user = userEvent.setup();
    requestReview.mockResolvedValue({
      kind: "ok",
      value: { items: [], version_status: "in_review", version_row_version: 5 },
    });
    const { onSent } = renderDialog();
    await user.click(screen.getByRole("button", { name: "Request review" }));
    const dialog = await screen.findByRole("dialog");

    await user.click(within(dialog).getByRole("button", { name: "Reviewers" }));
    await user.click(await screen.findByRole("option", { name: /Ana Ruiz/ }));
    await user.click(screen.getByRole("option", { name: /Ben Ode/ }));
    expect(screen.getByRole("option", { name: /Ana Ruiz/ }).getAttribute("aria-checked")).toBe(
      "true",
    );
    await user.keyboard("{Escape}");
    const chosen = within(dialog).getByRole("list", { name: "Chosen reviewers" });
    expect(within(chosen).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Ana Ruiz",
      "Ben Ode",
    ]);
    expect(within(dialog).getByRole("button", { name: "Send 2 requests" })).toBeTruthy();

    const card = within(dialog).getByRole("button", { name: "Security Assessment v1" });
    await user.click(card);
    expect(card.getAttribute("aria-pressed")).toBe("true");
    await user.type(within(dialog).getByLabelText("Message (optional)"), "Check L3");
    await user.click(within(dialog).getByRole("button", { name: "Send 2 requests" }));

    await waitFor(() => expect(onSent).toHaveBeenCalled());
    expect(requestReview).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      versionId: VERSION.id,
      rowVersion: 4,
      reviewType: "engineering",
      reviewerIds: [ANA.id, BEN.id],
      assessmentRefs: [{ id: ASSESSMENTS[1]!.id, version: 1 }],
      message: "Check L3",
    });
    expect(await screen.findByText("Review requested from 2 reviewers")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("reads the candidates again for a new type and drops the chosen reviewers", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(screen.getByRole("button", { name: "Request review" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reviewers" }));
    await user.click(await screen.findByRole("option", { name: /Ana Ruiz/ }));
    await user.keyboard("{Escape}");

    await user.click(within(dialog).getByRole("radio", { name: "Security" }));
    expect(within(dialog).queryByRole("list", { name: "Chosen reviewers" })).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Reviewers" }));
    expect(await screen.findByRole("option", { name: /Cy Sec/ })).toBeTruthy();
    expect(screen.queryByRole("option", { name: /Ana Ruiz/ })).toBeNull();
    expect(searchReviewerCandidates).toHaveBeenLastCalledWith(
      expect.objectContaining({ opportunityId: OPP_ID, reviewType: "security" }),
    );
  });

  it("shows a refused send inline and keeps the dialog open", async () => {
    const user = userEvent.setup();
    requestReview.mockResolvedValue({
      kind: "invalid",
      detail: "The author of v3 can't review it",
    });
    const { baseElement } = renderDialog();
    await user.click(screen.getByRole("button", { name: "Request review" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reviewers" }));
    await user.click(await screen.findByRole("option", { name: /Ana Ruiz/ }));
    await user.keyboard("{Escape}");
    await user.click(within(dialog).getByRole("button", { name: "Send 1 request" }));

    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toBe("The author of v3 can't review it");
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(await axeViolations(baseElement)).toEqual([]);
  });

  it("a stale version (412) says so inline", async () => {
    const user = userEvent.setup();
    requestReview.mockResolvedValue({ kind: "stale" });
    renderDialog();
    await user.click(screen.getByRole("button", { name: "Request review" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Reviewers" }));
    await user.click(await screen.findByRole("option", { name: /Ben Ode/ }));
    await user.keyboard("{Escape}");
    await user.click(within(dialog).getByRole("button", { name: "Send 1 request" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("(412)");
  });
});
