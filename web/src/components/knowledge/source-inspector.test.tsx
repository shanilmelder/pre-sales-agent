import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeSource } from "@/lib/knowledge-sources";
import { axeViolations } from "@/test/axe";
import { source } from "@/test/knowledge-fixtures";

import { ShellProviders } from "../shell/shell-context";
import { SourceInspector } from "./source-inspector";

const actions = vi.hoisted(() => ({
  addVersion: vi.fn(),
  editSource: vi.fn(),
  loadSource: vi.fn(),
  loadText: vi.fn(),
  markReviewed: vi.fn(),
  retireSource: vi.fn(),
  retryParse: vi.fn(),
}));
vi.mock("@/app/knowledge/actions", () => actions);
vi.mock("@/app/opportunities/actions", () => ({ loadOpportunity: vi.fn(), updateOpportunity: vi.fn() }));

const STALE = source(1, { stale: true, last_reviewed_on: "2025-01-01" });
const VERSION = {
  version: 1,
  product_version: "2.1",
  filename: "guide-1.pdf",
  size_bytes: 2048,
  uploaded_by: STALE.uploaded_by,
  uploaded_at: "2026-09-01T10:00:00Z",
  parse: { status: "parsed", error_code: null },
  char_count: 10,
};
const OWNER = { id: STALE.owner.id, roles: ["engineering_reviewer"] as const };
const STRANGER = { id: "someone-else", roles: ["engineering_reviewer"] as const };
const ADMIN = { id: "admin", roles: ["platform_administrator"] as const };

function renderInspector(
  me: { id: string; roles: readonly string[] },
  s: KnowledgeSource = STALE,
  onChange = vi.fn(),
) {
  const utils = render(
    <ShellProviders singleKeyShortcuts>
      <SourceInspector
        source={s}
        me={me as never}
        integrationTypes={[{ id: "t1", name: "SAP IDoc" }]}
        onChange={onChange}
      />
    </ShellProviders>,
  );
  return { onChange, user: userEvent.setup(), ...utils };
}

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
  actions.loadSource.mockResolvedValue({ kind: "ok", source: STALE, versions: [VERSION] });
});

describe("SourceInspector", () => {
  it("hides every action from someone who is neither the owner nor an administrator", async () => {
    renderInspector(STRANGER);
    await screen.findByText("v1", { exact: false });
    for (const name of ["Mark reviewed", "Upload new version", "Retire", "Save tags"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByRole("button", { name: "Edit title" })).toBeNull();
    // Reading stays open, with the Stale label and a download for every version.
    expect(screen.getByText("Stale")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Download version 1/ }).getAttribute("href")).toBe(
      `/api/knowledge/sources/${STALE.id}/versions/1/download`,
    );
  });

  it("shows the actions to the owner and to administrators", async () => {
    for (const me of [OWNER, ADMIN]) {
      const { unmount } = renderInspector(me);
      await screen.findByText("v1", { exact: false });
      expect(screen.getByRole("button", { name: "Mark reviewed" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Upload new version" })).toBeTruthy();
      expect(screen.getByRole("button", { name: "Retire" })).toBeTruthy();
      unmount();
    }
  });

  it("Mark reviewed sends the row version and reports the stored Source", async () => {
    const reviewed = { ...STALE, stale: false, row_version: 2, last_reviewed_on: "2026-10-07" };
    actions.markReviewed.mockResolvedValue({ kind: "ok", source: reviewed });
    const { user, onChange } = renderInspector(OWNER);
    await user.click(screen.getByRole("button", { name: "Mark reviewed" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(reviewed));
    expect(actions.markReviewed).toHaveBeenCalledWith({ sourceId: STALE.id, rowVersion: 1 });
  });

  it("a 412 shows who to reload from and overwrites nothing", async () => {
    actions.markReviewed.mockResolvedValue({ kind: "stale" });
    const { user, onChange } = renderInspector(OWNER);
    await user.click(screen.getByRole("button", { name: "Mark reviewed" }));
    expect(await screen.findByText(/Changed by someone else/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload" })).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows a failed parse with its reason and Retry for those who may write", async () => {
    const failed: KnowledgeSource = {
      ...STALE,
      parse: { status: "failed", error_code: "unreadable" },
    };
    actions.retryParse.mockResolvedValue({ kind: "ok", source: STALE });
    const { user } = renderInspector(OWNER, failed);
    expect(screen.getByText("Parse failed")).toBeTruthy();
    expect(screen.getByText("The file couldn't be read")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(actions.retryParse).toHaveBeenCalledWith(STALE.id);
  });

  it("labels a retired Integration Type tag and a retired Source", async () => {
    const retired: KnowledgeSource = {
      ...STALE,
      retired: true,
      status: "retired",
      retired_reason: "Superseded",
      integration_types: [{ id: "old", code: "X", name: "Old type", retired: true }],
    };
    renderInspector(ADMIN, retired);
    await screen.findByText("v1", { exact: false });
    expect(screen.getAllByText("Retired").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Retired: Superseded")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Mark reviewed" })).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderInspector(OWNER);
    await screen.findByText("v1", { exact: false });
    expect(await axeViolations(container)).toEqual([]);
  });
});
