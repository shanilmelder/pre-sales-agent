import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ActualsImportResult,
  ApplyActualsImportResult,
  LatestActualsImportResult,
} from "@/app/opportunities/actions";
import type { ActualsImportView, ActualsView, ImportRowView } from "@/lib/actuals";
import { axeViolations } from "@/test/axe";

const uploadActualsImport = vi.hoisted(() =>
  vi.fn<(form: unknown) => Promise<ActualsImportResult>>(),
);
const loadLatestActualsImport = vi.hoisted(() =>
  vi.fn<(id: unknown) => Promise<LatestActualsImportResult>>(),
);
const loadActualsImport = vi.hoisted(() =>
  vi.fn<(id: unknown, importId: unknown) => Promise<ActualsImportResult>>(),
);
const retryActualsImport = vi.hoisted(() =>
  vi.fn<(id: unknown, importId: unknown) => Promise<ActualsImportResult>>(),
);
const applyActualsImport = vi.hoisted(() =>
  vi.fn<(input: unknown) => Promise<ApplyActualsImportResult>>(),
);
vi.mock("@/app/opportunities/actions", () => ({
  uploadActualsImport,
  loadLatestActualsImport,
  loadActualsImport,
  retryActualsImport,
  applyActualsImport,
  loadSources: vi.fn(),
  retryParse: vi.fn(),
}));

// Fast polls, and a poll window each test can close.
const poll = vi.hoisted(() => ({ limit: 15 * 60 * 1000 }));
vi.mock("@/lib/sources", async (original) => ({
  ...(await original<typeof import("@/lib/sources")>()),
  PARSE_POLL_MS: 10,
  get PARSE_POLL_LIMIT_MS() {
    return poll.limit;
  },
}));

import { ShellProviders } from "../shell/shell-context";
import { ActualsImport } from "./actuals-import";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const IMPORT_ID = "00000000-0000-7000-8000-0000000000f1";
const CAUSES: ActualsView["causes"] = [
  { value: "estimation_error", label: "Estimation error", unplanned: false },
  { value: "scope_change", label: "Scope change", unplanned: true },
];

function row(overrides: Partial<ImportRowView> & { row: number }): ImportRowView {
  return {
    status: "create",
    line_id: "00000000-0000-7000-8000-0000000000b1",
    line_label: "L1",
    line_title: "WMS to SAP EWM interface",
    estimate_hours: 36,
    kind: "final",
    effort_hours: 36,
    variance_cause: null,
    correction_reason: null,
    reason_missing: false,
    problems: [],
    ...overrides,
  };
}

function imported(overrides: Partial<ActualsImportView> = {}): ActualsImportView {
  return {
    id: IMPORT_ID,
    filename: "actuals.xlsx",
    size_bytes: 9000,
    file_kind: "xlsx",
    status: "parsed",
    error_code: null,
    error_message: null,
    uploaded_by_name: "Dana Delivery",
    created_at: "2026-10-27T10:00:00Z",
    estimate_version: 3,
    rows: [
      row({ row: 2 }),
      row({ row: 3, line_label: "L2", line_title: "CRM data migration", effort_hours: 18 }),
      row({
        row: 4,
        status: "invalid",
        line_id: null,
        line_label: null,
        line_title: null,
        problems: ["Row 4: line ID not in Baseline v3"],
      }),
      row({ row: 5, status: "skipped", effort_hours: null }),
    ],
    counts: { create: 2, correct: 0, invalid: 1, skipped: 1 },
    repeat_applied_at: null,
    repeat_message: null,
    applied_at: null,
    applied: null,
    row_version: 4,
    ...overrides,
  };
}

const onApplied = vi.fn();

function renderImport() {
  return render(
    <ShellProviders singleKeyShortcuts>
      <ActualsImport opportunityId={OPP_ID} causes={CAUSES} onApplied={onApplied} />
    </ShellProviders>,
  );
}

async function openDialog(latest: ActualsImportView | null) {
  loadLatestActualsImport.mockResolvedValue({ kind: "ok", latest });
  const user = userEvent.setup();
  renderImport();
  await user.click(screen.getByRole("button", { name: "Import from file" }));
  const dialog = await screen.findByRole("dialog");
  await waitFor(() => expect(loadLatestActualsImport).toHaveBeenCalledWith(OPP_ID));
  return { user, dialog };
}

const QUEUED = () => imported({ status: "queued", rows: [], counts: null });

beforeEach(() => {
  vi.clearAllMocks();
  poll.limit = 15 * 60 * 1000;
  loadActualsImport.mockResolvedValue({ kind: "ok", imported: QUEUED() });
});

describe("ActualsImport", () => {
  it("offers Download template and Choose file in the mockup's dialog", async () => {
    const { dialog } = await openDialog(null);
    expect(within(dialog).getByRole("heading", { name: "Import Actuals from a file" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Download template" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Choose file" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Confirm" }).getAttribute("aria-disabled")).toBe(
      "true",
    );
    expect(await axeViolations(document.body)).toEqual([]);
  });

  it("uploads the chosen file and shows the reading status", async () => {
    uploadActualsImport.mockResolvedValue({
      kind: "ok",
      imported: imported({ status: "queued", rows: [], counts: null }),
    });
    const { user, dialog } = await openDialog(null);
    const file = new File(["x"], "actuals.csv", { type: "text/csv" });
    await user.upload(screen.getByTestId("actuals-file-input"), file);
    await waitFor(() => expect(uploadActualsImport).toHaveBeenCalled());
    const form = uploadActualsImport.mock.calls[0]![0] as FormData;
    expect(form.get("opportunityId")).toBe(OPP_ID);
    expect((form.get("file") as File).name).toBe("actuals.csv");
    expect(await within(dialog).findByText("Queued")).toBeTruthy();
  });

  it("shows a rejected upload's reason", async () => {
    uploadActualsImport.mockResolvedValue({
      kind: "rejected",
      reason: "Rejected: the content doesn't match .xlsx",
    });
    const { user, dialog } = await openDialog(null);
    await user.upload(screen.getByTestId("actuals-file-input"), new File(["x"], "a.xlsx"));
    expect(await within(dialog).findByText("Rejected: the content doesn't match .xlsx")).toBeTruthy();
  });

  it("Parse failed: a red pill, the reason and Retry", async () => {
    retryActualsImport.mockResolvedValue({
      kind: "ok",
      imported: imported({ status: "queued", rows: [], counts: null }),
    });
    const { user, dialog } = await openDialog(
      imported({
        status: "failed",
        error_code: "unreadable",
        error_message: "The file couldn't be read. Save it again as .xlsx or .csv.",
        rows: [],
        counts: null,
      }),
    );
    const pill = await within(dialog).findByText("Parse failed");
    expect(pill.closest("[data-tone]")?.getAttribute("data-tone")).toBe("blocker");
    expect(
      within(dialog).getByText("The file couldn't be read. Save it again as .xlsx or .csv."),
    ).toBeTruthy();
    await user.click(within(dialog).getByRole("button", { name: "Retry: actuals.xlsx" }));
    expect(retryActualsImport).toHaveBeenCalledWith(OPP_ID, IMPORT_ID);
    expect(await within(dialog).findByText("Queued")).toBeTruthy();
    expect(await axeViolations(document.body)).toEqual([]);
  });

  it("blocks Confirm while a row is invalid, then applies with it excluded", async () => {
    applyActualsImport.mockResolvedValue({
      kind: "ok",
      applied: {
        imported: imported({
          status: "applied",
          applied: { created: 2, corrected: 0, excluded: 1, skipped: 1 },
        }),
        actuals: { row_version: 6 } as ActualsView,
      },
    });
    const { user, dialog } = await openDialog(imported());
    expect(await within(dialog).findByText("Row 4: line ID not in Baseline v3")).toBeTruthy();
    expect(within(dialog).getByText("2 to create · 0 to correct · 1 invalid · 1 skipped")).toBeTruthy();
    const confirm = within(dialog).getByRole("button", { name: "Confirm" });
    expect(confirm.getAttribute("aria-disabled")).toBe("true");
    expect(within(dialog).getByText("1 row is invalid. Fix it in the file or exclude it.")).toBeTruthy();
    await user.click(confirm);
    expect(applyActualsImport).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("checkbox", { name: "Import row 4" }));
    expect(confirm.getAttribute("aria-disabled")).toBeNull();
    await user.click(confirm);
    expect(applyActualsImport).toHaveBeenCalledWith({
      opportunityId: OPP_ID,
      importId: IMPORT_ID,
      rowVersion: 4,
      excludedRows: [4],
      reason: undefined,
      confirmRepeat: false,
    });
    await waitFor(() => expect(onApplied).toHaveBeenCalledWith({ row_version: 6 }));
    expect(await axeViolations(document.body)).toEqual([]);
  });

  it("a correction needs the batch reason", async () => {
    const { user, dialog } = await openDialog(
      imported({
        rows: [row({ row: 2, status: "correct", reason_missing: true })],
        counts: { create: 0, correct: 1, invalid: 0, skipped: 0 },
      }),
    );
    expect(await within(dialog).findByText("Row 2: correction reason missing")).toBeTruthy();
    const confirm = within(dialog).getByRole("button", { name: "Confirm" });
    expect(confirm.getAttribute("aria-disabled")).toBe("true");
    await user.type(within(dialog).getByLabelText("Reason for the corrections"), "Timesheets");
    expect(within(dialog).queryByText("Row 2: correction reason missing")).toBeNull();
    expect(confirm.getAttribute("aria-disabled")).toBeNull();
  });

  it("a repeated file needs the tick", async () => {
    const { user, dialog } = await openDialog(
      imported({
        rows: [row({ row: 2 })],
        counts: { create: 1, correct: 0, invalid: 0, skipped: 0 },
        repeat_applied_at: "2026-10-14T09:00:00Z",
        repeat_message: "This file was already imported on 14 Oct",
      }),
    );
    expect(await within(dialog).findByText("This file was already imported on 14 Oct")).toBeTruthy();
    const confirm = within(dialog).getByRole("button", { name: "Confirm" });
    expect(confirm.getAttribute("aria-disabled")).toBe("true");
    await user.click(within(dialog).getByRole("checkbox", { name: "Import it again" }));
    expect(confirm.getAttribute("aria-disabled")).toBeNull();
  });

  it("a stale preview is refreshed", async () => {
    applyActualsImport.mockResolvedValue({ kind: "stale" });
    loadActualsImport.mockResolvedValue({ kind: "ok", imported: imported({ row_version: 7 }) });
    const { user, dialog } = await openDialog(imported({ rows: [row({ row: 2 })] }));
    await user.click(await within(dialog).findByRole("button", { name: "Confirm" }));
    expect(await within(dialog).findByText(/Actuals changed since the preview/)).toBeTruthy();
    expect(loadActualsImport).toHaveBeenCalledWith(OPP_ID, IMPORT_ID);
    expect(onApplied).not.toHaveBeenCalled();
  });

  it("a parsed file that can't be imported any more says why, with Confirm blocked", async () => {
    const { dialog } = await openDialog(imported({ estimate_version: null, rows: [], counts: null }));
    const why = await within(dialog).findByText(
      "Delivery is closed or there is no Baseline, so this file can't be imported.",
    );
    expect(within(dialog).queryByText(/Every row is blank/)).toBeNull();
    expect(within(dialog).queryByRole("heading", { name: "Preview" })).toBeNull();
    const confirm = within(dialog).getByRole("button", { name: "Confirm" });
    expect(confirm.getAttribute("aria-disabled")).toBe("true");
    expect(confirm.getAttribute("aria-describedby")).toBe(why.id);
  });

  it("a failed poll offers Check again, which reloads and polls again", async () => {
    loadActualsImport.mockResolvedValueOnce({ kind: "error" });
    const { user, dialog } = await openDialog(QUEUED());
    expect(
      await within(dialog).findByText("Still reading the file. Check again in a moment."),
    ).toBeTruthy();
    loadActualsImport.mockResolvedValue({ kind: "ok", imported: imported() });
    await user.click(within(dialog).getByRole("button", { name: "Check again" }));
    expect(await within(dialog).findByRole("heading", { name: "Preview" })).toBeTruthy();
    expect(within(dialog).queryByText(/Still reading the file/)).toBeNull();
    expect(loadActualsImport).toHaveBeenLastCalledWith(OPP_ID, IMPORT_ID);
  });

  it("stops polling when the window passes, and Check again restarts it", async () => {
    poll.limit = -1;
    const { user, dialog } = await openDialog(QUEUED());
    expect(
      await within(dialog).findByText("Still reading the file. Check again in a moment."),
    ).toBeTruthy();
    expect(loadActualsImport).not.toHaveBeenCalled();
    poll.limit = 15 * 60 * 1000;
    loadActualsImport.mockResolvedValue({ kind: "ok", imported: imported() });
    await user.click(within(dialog).getByRole("button", { name: "Check again" }));
    expect(await within(dialog).findByRole("heading", { name: "Preview" })).toBeTruthy();
    expect(await axeViolations(document.body)).toEqual([]);
  });
});
