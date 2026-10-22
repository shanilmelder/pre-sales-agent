import { beforeEach, describe, expect, it, vi } from "vitest";

import { draftInput } from "@/lib/checklists";
import { checklist, withDraft } from "@/test/checklist-fixtures";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PUT: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));

import {
  createChecklist,
  loadChecklists,
  loadChecklistVersion,
  openDraft,
  publishChecklist,
  retireChecklist,
  saveDraft,
} from "./actions";

const CHECKLIST = withDraft(checklist(1));
const ID = CHECKLIST.id;
const DRAFT = draftInput(CHECKLIST.draft!);
const status = (code: number) => new Response(null, { status: code });

beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  api.PUT.mockReset();
});

describe("loadChecklists", () => {
  it("reads every Checklist, retired ones too", async () => {
    api.GET.mockResolvedValue({ data: { items: [CHECKLIST] }, response: status(200) });
    expect(await loadChecklists()).toEqual({ kind: "ok", checklists: [CHECKLIST] });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/knowledge/checklists", {
      params: { query: { include_retired: true } },
    });
  });

  it("is an error when the API fails", async () => {
    api.GET.mockResolvedValue({ error: {}, response: status(500) });
    expect(await loadChecklists()).toEqual({ kind: "error" });
  });
});

describe("saveDraft", () => {
  it("puts the whole draft with the row version as If-Match", async () => {
    api.PUT.mockResolvedValue({ data: CHECKLIST, response: status(200) });
    const result = await saveDraft({ checklistId: ID, rowVersion: 2, draft: DRAFT });
    expect(result).toEqual({ kind: "ok", checklist: CHECKLIST });
    expect(api.PUT).toHaveBeenCalledWith("/api/v1/knowledge/checklists/{checklist_id}/draft", {
      params: { path: { checklist_id: ID }, header: { "If-Match": '"2"' } },
      body: DRAFT,
    });
  });

  it("maps 412 to stale, 422 to the API's sentence, 409 to the conflict code and 403", async () => {
    api.PUT.mockResolvedValueOnce({ error: {}, response: status(412) });
    expect(await saveDraft({ checklistId: ID, rowVersion: 2, draft: DRAFT })).toEqual({
      kind: "stale",
    });
    api.PUT.mockResolvedValueOnce({
      error: { detail: "A retired or unknown Integration Type can't be chosen." },
      response: status(422),
    });
    expect(await saveDraft({ checklistId: ID, rowVersion: 2, draft: DRAFT })).toEqual({
      kind: "invalid",
      detail: "A retired or unknown Integration Type can't be chosen.",
    });
    api.PUT.mockResolvedValueOnce({ error: { code: "checklist_no_draft" }, response: status(409) });
    expect(await saveDraft({ checklistId: ID, rowVersion: 2, draft: DRAFT })).toEqual({
      kind: "conflict",
      code: "checklist_no_draft",
    });
    api.PUT.mockResolvedValueOnce({ error: {}, response: status(403) });
    expect(await saveDraft({ checklistId: ID, rowVersion: 2, draft: DRAFT })).toEqual({
      kind: "forbidden",
    });
  });

  it("refuses a malformed request without calling the API", async () => {
    for (const input of [
      null,
      { checklistId: "nope", rowVersion: 2, draft: DRAFT },
      { checklistId: ID, rowVersion: -1, draft: DRAFT },
      { checklistId: ID, rowVersion: 2, draft: { ...DRAFT, items: [{ id: "x" }] } },
      { checklistId: ID, rowVersion: 2, draft: { ...DRAFT, integration_type_ids: ["bad"] } },
    ]) {
      expect(await saveDraft(input)).toEqual({ kind: "error" });
    }
    expect(api.PUT).not.toHaveBeenCalled();
  });
});

describe("the other writes", () => {
  it("open, publish and retire send If-Match", async () => {
    api.POST.mockResolvedValue({ data: CHECKLIST, response: status(200) });
    await openDraft({ checklistId: ID, rowVersion: 3 });
    await publishChecklist({ checklistId: ID, rowVersion: 4 });
    await retireChecklist({ checklistId: ID, rowVersion: 5, reason: "Old" });
    expect(api.POST.mock.calls).toEqual([
      [
        "/api/v1/knowledge/checklists/{checklist_id}/draft",
        { params: { path: { checklist_id: ID }, header: { "If-Match": '"3"' } } },
      ],
      [
        "/api/v1/knowledge/checklists/{checklist_id}/publish",
        { params: { path: { checklist_id: ID }, header: { "If-Match": '"4"' } } },
      ],
      [
        "/api/v1/knowledge/checklists/{checklist_id}/retire",
        {
          params: { path: { checklist_id: ID }, header: { "If-Match": '"5"' } },
          body: { reason: "Old" },
        },
      ],
    ]);
  });

  it("creates with a name and a domain", async () => {
    api.POST.mockResolvedValue({ data: CHECKLIST, response: status(201) });
    expect(await createChecklist({ name: "New", domain: "security" })).toEqual({
      kind: "ok",
      checklist: CHECKLIST,
    });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/knowledge/checklists", {
      body: { name: "New", domain: "security" },
    });
  });

  it("reads one version, 404 as not found", async () => {
    api.GET.mockResolvedValue({ error: {}, response: status(404) });
    expect(await loadChecklistVersion(ID, 9)).toEqual({ kind: "not-found" });
    expect(await loadChecklistVersion(ID, 0)).toEqual({ kind: "not-found" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });
});
