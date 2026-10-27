import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Opportunity } from "@/lib/opportunities";
import { retentionLine } from "@/lib/outcome";
import { axeViolations } from "@/test/axe";

const actions = vi.hoisted(() => ({
  changeOutcome: vi.fn(),
  loadOpportunity: vi.fn(),
}));
vi.mock("@/app/opportunities/actions", () => actions);
const refresh = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn(), refresh }),
}));

import { ShellProviders } from "../shell/shell-context";
import { OutcomeCard } from "./outcome-card";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

const OPEN: Opportunity = {
  id: OPP_ID,
  title: "[TITLE]",
  customer_name: "[CUSTOMER]",
  products: ["AutoStore"],
  industry: "Retail",
  target_proposal_date: "2026-11-01",
  status: "baselined",
  owner: { id: "00000000-0000-7000-8000-0000000000a1", name: "[OWNER]" },
  collaborators: [],
  row_version: 4,
  created_at: "2026-10-04T10:00:00Z",
  last_changed_by: null,
  can_manage_collaborators: true,
  can_edit: true,
  can_add_sources: true,
  outcome: null,
  outcome_recorded_at: null,
  contract_end_date: null,
  retention_until: null,
  can_record_outcome: true,
  can_change_contract_end: false,
  can_reopen_outcome: false,
};

const LOST: Opportunity = {
  ...OPEN,
  status: "closed",
  row_version: 5,
  outcome: "lost",
  outcome_recorded_at: "2026-10-14T09:30:00Z",
  retention_until: "2029-10-14",
  can_record_outcome: false,
};

const WON: Opportunity = {
  ...OPEN,
  row_version: 5,
  outcome: "won",
  outcome_recorded_at: "2026-10-14T09:30:00Z",
  contract_end_date: "2028-06-30",
  retention_until: "2035-06-30",
  can_record_outcome: false,
};

function renderCard(opportunity: Opportunity) {
  const user = userEvent.setup();
  const utils = render(
    <ShellProviders singleKeyShortcuts={false}>
      <OutcomeCard initial={opportunity} />
    </ShellProviders>,
  );
  return { user, ...utils };
}

function card() {
  return screen.getByRole("region", { name: "Outcome" });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("retentionLine", () => {
  it("words the API's retention date", () => {
    expect(retentionLine(LOST)).toBe("Lost — data kept until 14 Oct 2029");
    expect(retentionLine(WON)).toBe("Won — data kept until contract end plus 7 years (30 Jun 2035)");
    expect(retentionLine(OPEN)).toBe("Open — data is kept while the Opportunity is open.");
  });
});

describe("OutcomeCard", () => {
  it("shows a lost Opportunity's rows and retention line", async () => {
    const { container } = renderCard(LOST);
    const region = card();
    expect(within(region).getByText("Lost").getAttribute("data-outcome")).toBe("lost");
    expect(within(region).getByText("14 Oct 2026")).toBeTruthy();
    expect(within(region).getByText("Lost — data kept until 14 Oct 2029")).toBeTruthy();
    expect(within(region).queryAllByRole("button")).toEqual([]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("shows a won Opportunity's contract end and the Head of Delivery's actions", async () => {
    const { container } = renderCard({
      ...WON,
      can_change_contract_end: true,
      can_reopen_outcome: true,
    });
    const region = card();
    expect(within(region).getByText("30 Jun 2028")).toBeTruthy();
    expect(
      within(region).getByText("Won — data kept until contract end plus 7 years (30 Jun 2035)"),
    ).toBeTruthy();
    expect(within(region).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Change contract end date",
      "Reopen",
    ]);
    expect(await axeViolations(container)).toEqual([]);
  });

  it("follows a newer server copy and ignores an older one", () => {
    const wrap = (opportunity: Opportunity) => (
      <ShellProviders singleKeyShortcuts={false}>
        <OutcomeCard initial={opportunity} />
      </ShellProviders>
    );
    const { rerender } = render(wrap(OPEN));
    expect(within(card()).getAllByRole("button").length).toBe(2);
    rerender(wrap(LOST));
    expect(within(card()).getByText("Lost — data kept until 14 Oct 2029")).toBeTruthy();
    expect(within(card()).queryAllByRole("button")).toEqual([]);
    rerender(wrap({ ...OPEN }));
    expect(within(card()).getByText("Lost — data kept until 14 Oct 2029")).toBeTruthy();
    expect(within(card()).queryAllByRole("button")).toEqual([]);
  });

  it("is read-only, with no actions, for a reviewer or sales representative", () => {
    renderCard({ ...OPEN, can_record_outcome: false });
    expect(within(card()).getByText("Open")).toBeTruthy();
    expect(within(card()).queryAllByRole("button")).toEqual([]);
  });

  it("offers Close as lost and Mark as won, the latter only with a Baseline", () => {
    renderCard({ ...OPEN, status: "intake" });
    const won = within(card()).getByRole("button", { name: "Mark as won" });
    expect((won as HTMLButtonElement).disabled).toBe(true);
    expect(within(card()).getByText("Mark as won once a Baseline is set.")).toBeTruthy();
    expect(
      (within(card()).getByRole("button", { name: "Close as lost" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  });

  it("closes as lost through the dialog, once a reason is given", async () => {
    actions.changeOutcome.mockResolvedValue({ kind: "ok", opportunity: LOST });
    const { user } = renderCard(OPEN);
    await user.click(within(card()).getByRole("button", { name: "Close as lost" }));
    const dialog = await screen.findByRole("dialog", { name: "Close as lost" });
    const submit = within(dialog).getByRole("button", { name: "Close as lost" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(await axeViolations(dialog)).toEqual([]);

    await user.type(within(dialog).getByLabelText("Reason (required)"), "   ");
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByLabelText("Reason (required)"), "Lost on price");
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await user.click(submit);

    expect(actions.changeOutcome).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      rowVersion: 4,
      command: "lost",
      reason: "   Lost on price",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(card()).getByText("Lost — data kept until 14 Oct 2029")).toBeTruthy();
    expect(refresh).toHaveBeenCalled();
  });

  it("marks as won with a contract end date", async () => {
    actions.changeOutcome.mockResolvedValue({ kind: "ok", opportunity: WON });
    const { user } = renderCard(OPEN);
    await user.click(within(card()).getByRole("button", { name: "Mark as won" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as won" });
    const submit = within(dialog).getByRole("button", { name: "Mark as won" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect(within(dialog).queryByLabelText("Reason (required)")).toBeNull();
    await user.type(within(dialog).getByLabelText("Contract end date"), "2028-06-30");
    await user.click(submit);
    expect(actions.changeOutcome).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      rowVersion: 4,
      command: "won",
      contractEndDate: "2028-06-30",
    });
    await waitFor(() =>
      expect(
        within(card()).getByText("Won — data kept until contract end plus 7 years (30 Jun 2035)"),
      ).toBeTruthy(),
    );
  });

  it("changes the contract end date and reopens with a reason", async () => {
    const hod = { ...WON, can_change_contract_end: true, can_reopen_outcome: true };
    actions.changeOutcome.mockResolvedValueOnce({
      kind: "ok",
      opportunity: { ...hod, row_version: 6, contract_end_date: "2029-12-31" },
    });
    const { user } = renderCard(hod);
    await user.click(within(card()).getByRole("button", { name: "Change contract end date" }));
    let dialog = await screen.findByRole("dialog", { name: "Change contract end date" });
    const date = within(dialog).getByLabelText("Contract end date") as HTMLInputElement;
    expect(date.value).toBe("2028-06-30");
    await user.clear(date);
    await user.type(date, "2029-12-31");
    const change = within(dialog).getByRole("button", { name: "Change date" });
    expect((change as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(dialog).getByLabelText("Reason (required)"), "Extended");
    await user.click(change);
    expect(actions.changeOutcome).toHaveBeenLastCalledWith({
      opportunityId: OPP_ID,
      rowVersion: 5,
      command: "contract_end",
      reason: "Extended",
      contractEndDate: "2029-12-31",
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    actions.changeOutcome.mockResolvedValueOnce({ kind: "ok", opportunity: OPEN });
    await user.click(within(card()).getByRole("button", { name: "Reopen" }));
    dialog = await screen.findByRole("dialog", { name: "Reopen Opportunity" });
    await user.type(within(dialog).getByLabelText("Reason (required)"), "Customer came back");
    await user.click(within(dialog).getByRole("button", { name: "Reopen" }));
    expect(actions.changeOutcome).toHaveBeenLastCalledWith({
      opportunityId: OPP_ID,
      rowVersion: 6,
      command: "reopen",
      reason: "Customer came back",
    });
    await waitFor(() => expect(within(card()).getByText("Open")).toBeTruthy());
  });

  it("on 412 shows who changed it, with Reload, and overwrites nothing", async () => {
    actions.changeOutcome.mockResolvedValue({ kind: "stale", changedBy: "[OTHER]" });
    actions.loadOpportunity.mockResolvedValue({ kind: "ok", opportunity: LOST });
    const { user } = renderCard(OPEN);
    await user.click(within(card()).getByRole("button", { name: "Close as lost" }));
    const dialog = await screen.findByRole("dialog", { name: "Close as lost" });
    await user.type(within(dialog).getByLabelText("Reason (required)"), "Lost on price");
    await user.click(within(dialog).getByRole("button", { name: "Close as lost" }));
    const alert = await within(dialog).findByRole("alert");
    expect(alert.textContent).toContain("Changed by [OTHER] since you opened it.");
    expect(
      (within(dialog).getByRole("button", { name: "Close as lost" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    await user.click(within(alert).getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(within(card()).getByText("Lost — data kept until 14 Oct 2029")).toBeTruthy();
    expect(actions.changeOutcome).toHaveBeenCalledTimes(1);
  });

  it("shows the API's sentence on a 409", async () => {
    actions.changeOutcome.mockResolvedValue({
      kind: "invalid",
      code: "baseline_required",
      detail: "An Opportunity can be marked won once it has a Baseline.",
    });
    const { user } = renderCard(OPEN);
    await user.click(within(card()).getByRole("button", { name: "Mark as won" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as won" });
    await user.type(within(dialog).getByLabelText("Contract end date"), "2028-06-30");
    await user.click(within(dialog).getByRole("button", { name: "Mark as won" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe(
      "An Opportunity can be marked won once it has a Baseline.",
    );
  });
});
