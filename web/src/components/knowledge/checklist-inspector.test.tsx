import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Checklist } from "@/lib/checklists";
import { axeViolations } from "@/test/axe";
import {
  checklist,
  item,
  PACKAGE_ID,
  TYPE_ID,
  VERSION_1,
  withDraft,
} from "@/test/checklist-fixtures";

import { ShellProviders } from "../shell/shell-context";
import { ChecklistInspector } from "./checklist-inspector";

const actions = vi.hoisted(() => ({
  createChecklist: vi.fn(),
  loadChecklist: vi.fn(),
  loadChecklistVersion: vi.fn(),
  loadChecklists: vi.fn(),
  openDraft: vi.fn(),
  publishChecklist: vi.fn(),
  retireChecklist: vi.fn(),
  saveDraft: vi.fn(),
}));
vi.mock("@/app/knowledge/checklists/actions", () => actions);
vi.mock("@/app/opportunities/actions", () => ({
  loadOpportunity: vi.fn(),
  updateOpportunity: vi.fn(),
  loadSources: vi.fn(),
  retryParse: vi.fn(),
}));

const CATALOGUE = [
  { id: TYPE_ID, kind: "integration_type" as const, name: "SAP IDoc" },
  { id: PACKAGE_ID, kind: "work_package" as const, name: "Data migration" },
];
const PUBLISHED = checklist(1);
const DRAFTING = withDraft(PUBLISHED);

function renderInspector(c: Checklist, mayAuthor: boolean, onChange = vi.fn()) {
  const utils = render(
    <ShellProviders singleKeyShortcuts>
      <ChecklistInspector
        checklist={c}
        catalogue={CATALOGUE}
        mayAuthor={mayAuthor}
        onChange={onChange}
      />
    </ShellProviders>,
  );
  return { onChange, user: userEvent.setup(), ...utils };
}

function itemRows(): HTMLElement[] {
  return screen.getAllByRole("listitem").filter((li) => li.hasAttribute("data-item-id"));
}

beforeEach(() => {
  for (const fn of Object.values(actions)) fn.mockReset();
  actions.loadChecklist.mockResolvedValue({
    kind: "ok",
    checklist: PUBLISHED,
    versions: [VERSION_1],
  });
});

describe("ChecklistInspector", () => {
  it("shows a reader the published items with no authoring controls", async () => {
    renderInspector(DRAFTING, false);
    await screen.findByText("Version 1");
    for (const name of ["Edit", "Publish", "Retire", "Add item", "Edit name"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByText("Question 1?")).toBeTruthy();
    const mandatory = screen.getAllByText("Mandatory")[0]!;
    expect(mandatory.closest("[data-label=mandatory]")?.querySelector("svg")).toBeTruthy();
  });

  it("lets an author start a draft from a published Checklist", async () => {
    actions.openDraft.mockResolvedValue({ kind: "ok", checklist: DRAFTING });
    const { user, onChange } = renderInspector(PUBLISHED, true);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(DRAFTING));
    expect(actions.openDraft).toHaveBeenCalledWith({ checklistId: PUBLISHED.id, rowVersion: 2 });
  });

  it("saves an item's text on blur with the whole draft and the row version", async () => {
    actions.saveDraft.mockResolvedValue({ kind: "ok", checklist: DRAFTING });
    const { user } = renderInspector(DRAFTING, true);
    const text = within(itemRows()[1]!).getByLabelText("Question");
    await user.clear(text);
    await user.type(text, "Reworded?");
    fireEvent.blur(text);
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalledTimes(1));
    const sent = actions.saveDraft.mock.calls[0]![0] as {
      rowVersion: number;
      draft: { items: { id: string; text: string }[] };
    };
    expect(sent.rowVersion).toBe(2);
    expect(sent.draft.items.map((i) => [i.id, i.text])).toEqual([
      [item(1).id, "Question 1?"],
      [item(2).id, "Reworded?"],
    ]);
  });

  it("marks an item mandatory with the label and saves it", async () => {
    actions.saveDraft.mockResolvedValue({ kind: "ok", checklist: DRAFTING });
    const { user } = renderInspector(DRAFTING, true);
    const [first, second] = itemRows();
    const label = within(first!).getByText("Mandatory");
    expect(label.closest("[data-label=mandatory]")?.querySelector("svg")).toBeTruthy();
    expect(within(second!).queryByText("Mandatory")).toBeNull();
    await user.click(within(second!).getByRole("checkbox", { name: /Mandatory/ }));
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalled());
    const sent = actions.saveDraft.mock.calls[0]![0] as {
      draft: { items: { mandatory: boolean }[] };
    };
    expect(sent.draft.items[1]!.mandatory).toBe(true);
  });

  it("keeps Publish disabled, with the reason, until the draft is publishable", async () => {
    const blocked = withDraft(checklist(1, { current_version: null, items: [] }), {
      items: [],
      publishable: false,
      publish_problem: "A Checklist needs a scope tag and an item before it can be published.",
    });
    const { user } = renderInspector(blocked, true);
    const publish = screen.getByRole("button", { name: "Publish" });
    expect(publish.getAttribute("aria-disabled")).toBe("true");
    expect(screen.getByText(/needs a scope tag and an item/)).toBeTruthy();
    await user.click(publish);
    expect(actions.publishChecklist).not.toHaveBeenCalled();
  });

  it("publishes a publishable draft", async () => {
    actions.publishChecklist.mockResolvedValue({
      kind: "ok",
      checklist: checklist(1, { current_version: 2 }),
    });
    const { user, onChange } = renderInspector(DRAFTING, true);
    const publish = screen.getByRole("button", { name: "Publish" });
    expect(publish.getAttribute("aria-disabled")).toBeNull();
    await user.click(publish);
    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(actions.publishChecklist).toHaveBeenCalledWith({
      checklistId: PUBLISHED.id,
      rowVersion: 2,
    });
  });

  it("shows the stale notice with Reload on 412 and overwrites nothing", async () => {
    actions.saveDraft.mockResolvedValue({ kind: "stale" });
    const { user, onChange } = renderInspector(DRAFTING, true);
    await user.selectOptions(screen.getByLabelText("Domain"), "general");
    expect(await screen.findByText(/Changed by someone else/)).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
    const reload = screen.getByRole("button", { name: "Reload" });
    await waitFor(() => expect(document.activeElement).toBe(reload));
    await user.click(reload);
    await waitFor(() => expect(onChange).toHaveBeenCalledWith(PUBLISHED));
    expect(screen.queryByRole("button", { name: "Reload" })).toBeNull();
  });

  it("lists versions with publisher and date and shows one read-only", async () => {
    actions.loadChecklistVersion.mockResolvedValue({
      kind: "ok",
      version: {
        checklist_id: PUBLISHED.id,
        version: 1,
        name: "Old name",
        domain: "security",
        products: ["AutoStore"],
        industry: null,
        integration_types: [],
        items: [item(5, { text: "Old question?" })],
        published_by: VERSION_1.published_by,
        published_at: VERSION_1.published_at,
      },
    });
    const { user } = renderInspector(PUBLISHED, false);
    expect(await screen.findByText(/\[PUBLISHER\] · 2 Oct 2026/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "View version 1" }));
    const shown = await screen.findByRole("region", { name: "Version 1 (read-only)" });
    expect(within(shown).getByText("Old question?")).toBeTruthy();
    expect(within(shown).queryByRole("textbox")).toBeNull();
    expect(actions.loadChecklistVersion).toHaveBeenCalledWith(PUBLISHED.id, 1);
  });

  it("retires with a reason", async () => {
    actions.retireChecklist.mockResolvedValue({
      kind: "ok",
      checklist: checklist(1, { retired: true, status: "retired", retired_reason: "Old" }),
    });
    const { user } = renderInspector(PUBLISHED, true);
    await user.click(screen.getByRole("button", { name: "Retire" }));
    await user.click(screen.getByRole("button", { name: "Confirm retire" }));
    expect(await screen.findByText("The reason is required.")).toBeTruthy();
    await user.type(screen.getByLabelText("Reason for retiring"), "Superseded");
    await user.click(screen.getByRole("button", { name: "Confirm retire" }));
    await waitFor(() =>
      expect(actions.retireChecklist).toHaveBeenCalledWith({
        checklistId: PUBLISHED.id,
        rowVersion: 2,
        reason: "Superseded",
      }),
    );
  });

  it("shows a retired affected area with the Retired label", () => {
    const retiredArea = withDraft(PUBLISHED, {
      items: [
        item(1, {
          affected_area: {
            id: "00000000-0000-7000-8000-000000000009",
            kind: "work_package",
            code: "OLD",
            name: "Old package",
            retired: true,
          },
        }),
      ],
    });
    renderInspector(retiredArea, true);
    const row = itemRows()[0]!;
    expect(within(row).getByRole("option", { name: "Old package (retired)" })).toBeTruthy();
    expect(within(row).getByText("Retired").closest("[data-label=retired]")).toBeTruthy();
  });

  type Sent = {
    rowVersion: number;
    draft: {
      integration_type_ids: string[];
      items: { id: string | null; text: string; mandatory: boolean }[];
    };
  };
  const sent = (call: number) => actions.saveDraft.mock.calls[call]![0] as Sent;

  it("moves an item up", async () => {
    actions.saveDraft.mockResolvedValue({ kind: "ok", checklist: DRAFTING });
    const { user } = renderInspector(DRAFTING, true);
    await user.click(screen.getByRole("button", { name: "Move item 2 up" }));
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalledTimes(1));
    expect(sent(0).draft.items.map((i) => i.id)).toEqual([item(2).id, item(1).id]);
  });

  it("removes an item", async () => {
    actions.saveDraft.mockResolvedValue({ kind: "ok", checklist: DRAFTING });
    const { user } = renderInspector(DRAFTING, true);
    await user.click(screen.getByRole("button", { name: "Remove item 1" }));
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalledTimes(1));
    expect(sent(0).draft.items.map((i) => i.id)).toEqual([item(2).id]);
  });

  it("adds a new item with no id", async () => {
    actions.saveDraft.mockResolvedValue({ kind: "ok", checklist: DRAFTING });
    const { user } = renderInspector(DRAFTING, true);
    await user.click(screen.getByRole("button", { name: "Add item" }));
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalledTimes(1));
    const items = sent(0).draft.items;
    expect(items).toHaveLength(3);
    expect(items[2]!.id).toBeNull();
  });

  it("unticks an Integration Type", async () => {
    actions.saveDraft.mockResolvedValue({ kind: "ok", checklist: DRAFTING });
    const { user } = renderInspector(DRAFTING, true);
    await user.click(screen.getByRole("checkbox", { name: "SAP IDoc" }));
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalledTimes(1));
    expect(sent(0).draft.integration_type_ids).toEqual([]);
  });

  it("queues a change made while a save is in flight and replays it on the new row version", async () => {
    let finish: (result: unknown) => void = () => {};
    const saved = withDraft({ ...PUBLISHED, row_version: 3 }, {
      items: [item(1, { mandatory: true }), item(2, { text: "Reworded?" })],
    });
    actions.saveDraft
      .mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)))
      .mockResolvedValueOnce({ kind: "ok", checklist: saved });
    actions.publishChecklist.mockResolvedValue({
      kind: "ok",
      checklist: checklist(1, { current_version: 2, row_version: 5 }),
    });
    const { user, onChange } = renderInspector(DRAFTING, true);
    const second = itemRows()[1]!;
    const text = within(second).getByLabelText("Question");
    await user.clear(text);
    await user.type(text, "Reworded?");
    // Clicking Mandatory blurs the text (its save starts) and then ticks the box while that
    // save is in flight; Publish follows straight away.
    await user.click(within(second).getByRole("checkbox", { name: /Mandatory/ }));
    await user.click(screen.getByRole("button", { name: "Publish" }));
    expect(actions.saveDraft).toHaveBeenCalledTimes(1);
    finish({ kind: "ok", checklist: saved });
    await waitFor(() => expect(actions.publishChecklist).toHaveBeenCalledTimes(1));
    expect(actions.saveDraft).toHaveBeenCalledTimes(2);
    expect(sent(0).draft.items[1]).toMatchObject({ text: "Reworded?", mandatory: false });
    expect(sent(1).rowVersion).toBe(3);
    expect(sent(1).draft.items[1]).toMatchObject({ text: "Reworded?", mandatory: true });
    // The queued Publish uses the row version the replayed save returned.
    const savedAgain = await actions.saveDraft.mock.results[1]!.value;
    expect(actions.publishChecklist).toHaveBeenCalledWith({
      checklistId: PUBLISHED.id,
      rowVersion: (savedAgain as { checklist: Checklist }).checklist.row_version,
    });
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(3));
  });

  it("discards queued changes when the save in flight comes back stale", async () => {
    let finish: (result: unknown) => void = () => {};
    actions.saveDraft.mockImplementationOnce(() => new Promise((resolve) => (finish = resolve)));
    const { user } = renderInspector(DRAFTING, true);
    await user.selectOptions(screen.getByLabelText("Domain"), "general");
    await waitFor(() => expect(actions.saveDraft).toHaveBeenCalledTimes(1));
    await user.click(screen.getByRole("button", { name: "Add item" }));
    finish({ kind: "stale" });
    expect(await screen.findByRole("button", { name: "Reload" })).toBeTruthy();
    expect(actions.saveDraft).toHaveBeenCalledTimes(1);
  });

  it("says when the version history can't be loaded", async () => {
    actions.loadChecklist.mockResolvedValue({ kind: "error" });
    renderInspector(PUBLISHED, false);
    expect(await screen.findByText("The version history could not be loaded.")).toBeTruthy();
  });

  it("loads the version history again only when a new version is published", async () => {
    const { rerender } = renderInspector(DRAFTING, true);
    await screen.findByText("Version 1");
    const again = (c: Checklist) =>
      rerender(
        <ShellProviders singleKeyShortcuts>
          <ChecklistInspector checklist={c} catalogue={CATALOGUE} mayAuthor onChange={vi.fn()} />
        </ShellProviders>,
      );
    again({ ...DRAFTING, row_version: 3 });
    expect(actions.loadChecklist).toHaveBeenCalledTimes(1);
    again(checklist(1, { current_version: 2, row_version: 4 }));
    await waitFor(() => expect(actions.loadChecklist).toHaveBeenCalledTimes(2));
  });

  it("has no axe violations, editing or reading", async () => {
    const { container, unmount } = renderInspector(DRAFTING, true);
    await screen.findByText("Version 1");
    expect(await axeViolations(container)).toEqual([]);
    unmount();
    const reader = renderInspector(PUBLISHED, false);
    await screen.findByText("Version 1");
    expect(await axeViolations(reader.container)).toEqual([]);
  });
});
