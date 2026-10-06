import { beforeEach, describe, expect, it, vi } from "vitest";

import { entry } from "@/test/catalogue-fixtures";

const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PATCH: vi.fn(),
}));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));

import { createEntry, editEntry, loadEntry, reactivateEntry, retireEntry } from "./actions";

const ENTRY = entry(1);
const ID = ENTRY.id;
const status = (code: number) => new Response(null, { status: code });
const VERSION = {
  version: 1,
  name: "n",
  definition: "d",
  changed_by_id: "u",
  changed_by_name: "[ADMIN]",
  changed_at: "2026-10-06T10:00:00Z",
};

beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  api.PATCH.mockReset();
});

describe("createEntry", () => {
  it("posts the entry and returns the stored one", async () => {
    api.POST.mockResolvedValue({ data: ENTRY, response: status(201) });
    const body = { kind: "work_package", code: "C", name: "N", definition: "D" };
    expect(await createEntry(body)).toEqual({ kind: "ok", entry: ENTRY });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/catalogue/entries", { body });
  });

  it("passes the duplicate sentence through", async () => {
    const detail = "An active Integration Type with this name already exists";
    api.POST.mockResolvedValue({ error: { code: "catalogue_duplicate", detail }, response: status(409) });
    expect(
      await createEntry({ kind: "integration_type", code: "C", name: "N", definition: "D" }),
    ).toEqual({ kind: "duplicate", detail });
  });

  it("rejects malformed input without calling the API", async () => {
    expect(await createEntry({ kind: "other", code: "C", name: "N", definition: "D" })).toEqual({
      kind: "error",
    });
    expect(await createEntry(null)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("editEntry", () => {
  it("patches with the row version as If-Match", async () => {
    api.PATCH.mockResolvedValue({ data: ENTRY, response: status(200) });
    await editEntry({ entryId: ID, rowVersion: 3, definition: "New" });
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/catalogue/entries/{entry_id}", {
      params: { path: { entry_id: ID }, header: { "If-Match": '"3"' } },
      body: { name: undefined, definition: "New" },
    });
  });

  it("on 412 reports who saved the latest version and writes nothing else", async () => {
    api.PATCH.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue({
      data: { ...ENTRY, items: [{ ...VERSION, changed_by_name: "[OTHER]" }] },
      response: status(200),
    });
    const result = await editEntry({ entryId: ID, rowVersion: 3, name: "x" });
    expect(result).toEqual({ kind: "stale", changedBy: "[OTHER]" });
    expect(api.PATCH).toHaveBeenCalledTimes(1);
  });

  it("maps 403 and 404", async () => {
    api.PATCH.mockResolvedValueOnce({ response: status(403) });
    expect(await editEntry({ entryId: ID, rowVersion: 1, name: "x" })).toEqual({
      kind: "forbidden",
    });
    api.PATCH.mockResolvedValueOnce({ response: status(404) });
    expect(await editEntry({ entryId: ID, rowVersion: 1, name: "x" })).toEqual({
      kind: "not-found",
    });
  });

  it("rejects a bad id or row version", async () => {
    expect(await editEntry({ entryId: "nope", rowVersion: 1 })).toEqual({ kind: "error" });
    expect(await editEntry({ entryId: ID, rowVersion: -1 })).toEqual({ kind: "error" });
    expect(api.PATCH).not.toHaveBeenCalled();
  });
});

describe("retireEntry and reactivateEntry", () => {
  it("retire sends the reason and If-Match", async () => {
    api.POST.mockResolvedValue({ data: ENTRY, response: status(200) });
    await retireEntry({ entryId: ID, rowVersion: 2, reason: "Old" });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/catalogue/entries/{entry_id}/retire", {
      params: { path: { entry_id: ID }, header: { "If-Match": '"2"' } },
      body: { reason: "Old" },
    });
  });

  it("a blank reason (422) comes back as invalid with the sentence", async () => {
    api.POST.mockResolvedValue({
      error: { code: "validation_error", detail: "The reason is required." },
      response: status(422),
    });
    expect(await retireEntry({ entryId: ID, rowVersion: 2, reason: " " })).toEqual({
      kind: "invalid",
      detail: "The reason is required.",
    });
  });

  it("reactivate posts with If-Match and reports a duplicate", async () => {
    api.POST.mockResolvedValue({
      error: { detail: "An active Work Package with this name already exists" },
      response: status(409),
    });
    expect(await reactivateEntry({ entryId: ID, rowVersion: 4 })).toEqual({
      kind: "duplicate",
      detail: "An active Work Package with this name already exists",
    });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/catalogue/entries/{entry_id}/reactivate", {
      params: { path: { entry_id: ID }, header: { "If-Match": '"4"' } },
    });
  });
});

describe("loadEntry", () => {
  it("loads the entry with its versions", async () => {
    api.GET.mockImplementation(async (path: string) =>
      path.endsWith("/versions")
        ? { data: { items: [VERSION] }, response: status(200) }
        : { data: ENTRY, response: status(200) },
    );
    expect(await loadEntry(ID)).toEqual({ kind: "ok", entry: ENTRY, versions: [VERSION] });
  });

  it("treats a non-UUID as not found and a 403 as forbidden", async () => {
    expect(await loadEntry("nope")).toEqual({ kind: "not-found" });
    api.GET.mockResolvedValue({ response: status(403) });
    expect(await loadEntry(ID)).toEqual({ kind: "forbidden" });
  });
});
