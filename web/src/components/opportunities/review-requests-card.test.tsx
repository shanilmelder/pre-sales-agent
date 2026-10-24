import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RequestStatus, ReviewRequest } from "@/lib/reviews";
import { axeViolations } from "@/test/axe";

const cancelReviewRequest = vi.hoisted(() => vi.fn());
vi.mock("@/app/opportunities/actions", () => ({ cancelReviewRequest }));

import { LiveRegionProvider } from "../shell/live-region";
import { RequestStatusPill, ReviewRequestsCard } from "./review-requests-card";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const REASON = "Sent to the wrong reviewer";

function request(n: number, overrides: Partial<ReviewRequest> = {}): ReviewRequest {
  return {
    id: `00000000-0000-7000-8000-0000000000${String(n).padStart(2, "0")}`,
    review_type: "engineering",
    target: {
      kind: "estimate_version",
      id: "00000000-0000-7000-8000-0000000000e3",
      version: 3,
      label: "Estimate v3",
    },
    estimate_version_id: "00000000-0000-7000-8000-0000000000e3",
    estimate_version: 3,
    reviewer: { id: `00000000-0000-7000-8000-0000000000a${n}`, name: `Reviewer ${n}` },
    requested_by: { id: "00000000-0000-7000-8000-0000000000f1", name: "Owner Person" },
    message: null,
    status: "pending",
    cancel_reason: null,
    row_version: 1,
    created_at: "2026-10-24T09:00:00Z",
    updated_at: "2026-10-24T09:00:00Z",
    can_cancel: true,
    ...overrides,
  };
}

function renderCard(items: ReviewRequest[], onChanged = vi.fn()) {
  const result = render(
    <LiveRegionProvider>
      <ReviewRequestsCard opportunityId={OPP_ID} items={items} onChanged={onChanged} />
    </LiveRegionProvider>,
  );
  return { ...result, onChanged };
}

beforeEach(() => cancelReviewRequest.mockReset());
afterEach(() => window.history.replaceState(null, "", "/"));

describe("RequestStatusPill", () => {
  it("pairs every status with an icon and a label in the EXPERIENCE.md tone", () => {
    const statuses: RequestStatus[] = [
      "pending",
      "approved",
      "rejected",
      "challenged",
      "superseded",
      "cancelled",
    ];
    const { container } = render(
      <>
        {statuses.map((s) => (
          <RequestStatusPill key={s} status={s} />
        ))}
      </>,
    );
    const pills = Array.from(container.querySelectorAll("[data-request-status]"));
    expect(pills.map((p) => [p.textContent, p.getAttribute("data-tone")])).toEqual([
      ["Pending", "gap"],
      ["Approved", "resolved"],
      ["Rejected", "blocker"],
      ["Challenged", "gap"],
      ["Superseded", "neutral"],
      ["Cancelled", "neutral"],
    ]);
    for (const pill of pills) expect(pill.querySelector("svg")).not.toBeNull();
  });
});

describe("Review requests card (Story 9.1)", () => {
  it("says when no request was sent", async () => {
    const { container } = renderCard([]);
    const card = screen.getByRole("region", { name: "Review requests" });
    expect(within(card).getByText("No Review Request sent yet")).toBeTruthy();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("lists each request with reviewer, type, target, status, sent time and message", async () => {
    const { container } = renderCard([
      request(1, { message: "Please check the L3 hours." }),
      request(2, {
        review_type: "security",
        status: "cancelled",
        cancel_reason: REASON,
        can_cancel: false,
        target: {
          kind: "assessment",
          id: "00000000-0000-7000-8000-0000000000b1",
          version: 2,
          label: "Security Assessment v2",
        },
      }),
    ]);
    const rows = Array.from(container.querySelectorAll<HTMLElement>("[data-review-row]"));
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("Reviewer 1")).toBeTruthy();
    expect(within(rows[0]!).getByText("Engineering review · Estimate v3")).toBeTruthy();
    expect(within(rows[0]!).getByText("Pending")).toBeTruthy();
    expect(within(rows[0]!).getByText("Sent 24 Oct")).toBeTruthy();
    expect(within(rows[0]!).getByText("Please check the L3 hours.")).toBeTruthy();
    const cancel = within(rows[0]!).getByRole("button", { name: "Cancel request to Reviewer 1" });
    expect(cancel).toBeTruthy();
    expect(within(rows[1]!).getByText("Security review · Security Assessment v2")).toBeTruthy();
    expect(within(rows[1]!).getByText(`Cancelled: ${REASON}`)).toBeTruthy();
    expect(within(rows[1]!).queryByRole("button")).toBeNull();
    expect(await axeViolations(container)).toEqual([]);
  });

  it("cancels with a required reason, then announces and reads again", async () => {
    const user = userEvent.setup();
    cancelReviewRequest.mockResolvedValue({
      kind: "ok",
      value: request(1, { status: "cancelled" }),
    });
    const { onChanged, baseElement } = renderCard([request(1)]);

    await user.click(screen.getByRole("button", { name: "Cancel request to Reviewer 1" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Cancel the Engineering review request?",
    });
    await user.click(within(dialog).getByRole("button", { name: "Cancel request" }));
    expect(within(dialog).getByText("Give a reason of 1 to 1,000 characters.")).toBeTruthy();
    expect(cancelReviewRequest).not.toHaveBeenCalled();
    expect(await axeViolations(baseElement)).toEqual([]);

    await user.type(within(dialog).getByLabelText("Reason for cancelling"), `  ${REASON}  `);
    await user.click(within(dialog).getByRole("button", { name: "Cancel request" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(cancelReviewRequest).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      requestId: request(1).id,
      rowVersion: 1,
      reason: REASON,
    });
    expect(await screen.findByText("Review request cancelled")).toBeTruthy();
  });

  it("shows a stale cancel (412) inline", async () => {
    const user = userEvent.setup();
    cancelReviewRequest.mockResolvedValue({ kind: "stale" });
    renderCard([request(1)]);
    await user.click(screen.getByRole("button", { name: "Cancel request to Reviewer 1" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Reason for cancelling"), REASON);
    await user.click(within(dialog).getByRole("button", { name: "Cancel request" }));
    expect((await within(dialog).findByRole("alert")).textContent).toContain("(412)");
  });

  it("?review={id} scrolls to that row and highlights it", () => {
    const url = `/opportunities/${OPP_ID}/estimate?review=${request(2).id}`;
    window.history.replaceState(null, "", url);
    const { container } = renderCard([request(1), request(2)]);
    const rows = Array.from(container.querySelectorAll<HTMLElement>("[data-review-row]"));
    expect(rows[0]!.hasAttribute("data-highlighted")).toBe(false);
    expect(rows[1]!.hasAttribute("data-highlighted")).toBe(true);
    expect(document.activeElement).toBe(rows[1]);
  });
});
