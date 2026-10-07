import { beforeEach, describe, expect, it, vi } from "vitest";

import { source } from "@/test/knowledge-fixtures";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));

import {
  addVersion,
  editSource,
  loadSources,
  markReviewed,
  registerSource,
  retireSource,
  retryParse,
} from "./actions";

const SOURCE = source(1);
const ID = SOURCE.id;
const TAG = "00000000-0000-7000-8000-000000000001";
const status = (code: number) => new Response(null, { status: code });

beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
  api.PATCH.mockReset();
});

function form(fields: Record<string, string | File | string[]>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(fields)) {
    if (Array.isArray(value)) for (const v of value) data.append(key, v);
    else data.append(key, value);
  }
  return data;
}

describe("loadSources", () => {
  it("reads every Source, retired ones too", async () => {
    api.GET.mockResolvedValue({ data: { items: [SOURCE], stale_months: 12 }, response: status(200) });
    expect(await loadSources()).toEqual({ kind: "ok", sources: [SOURCE], staleMonths: 12 });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/knowledge/sources", {
      params: { query: { include_retired: true } },
    });
  });

  it("is an error when the API fails", async () => {
    api.GET.mockResolvedValue({ error: {}, response: status(500) });
    expect(await loadSources()).toEqual({ kind: "error" });
  });
});

describe("registerSource", () => {
  const file = new File(["# hi"], "guide.md");
  const fields = { file, title: "T", product: "P", productVersion: "1", tagId: [TAG] };

  it("sends the fields as query parameters and the file as the body", async () => {
    api.POST.mockResolvedValue({ data: SOURCE, response: status(201) });
    expect(await registerSource(form(fields))).toEqual({ kind: "ok", source: SOURCE });
    const [path, options] = api.POST.mock.calls[0] as [string, Record<string, unknown>];
    expect(path).toBe("/api/v1/knowledge/sources");
    expect(options.params).toEqual({
      query: {
        title: "T",
        product: "P",
        product_version: "1",
        integration_type_ids: [TAG],
        owner_id: null,
      },
    });
  });

  it("passes the API's rejection sentence through", async () => {
    const detail = "Rejected: .exe files aren't allowed";
    api.POST.mockResolvedValue({
      error: { code: "file_type_not_allowed", detail },
      response: status(422),
    });
    expect(await registerSource(form(fields))).toEqual({ kind: "rejected", reason: detail });
  });

  it("maps a retired tag to an invalid field and 403 to forbidden", async () => {
    const detail = "A retired or unknown Integration Type can't be chosen.";
    api.POST.mockResolvedValue({ error: { detail }, response: status(422) });
    expect(await registerSource(form(fields))).toEqual({ kind: "invalid", detail });
    api.POST.mockResolvedValue({ error: {}, response: status(403) });
    expect(await registerSource(form(fields))).toEqual({ kind: "forbidden" });
  });

  it("rejects malformed input without calling the API", async () => {
    expect(await registerSource(null)).toEqual({ kind: "error" });
    expect(await registerSource(form({ title: "T", product: "P", productVersion: "1" }))).toEqual({
      kind: "error",
    });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("writes", () => {
  it("send the row version as If-Match and map 412 and 409", async () => {
    api.POST.mockResolvedValue({ data: SOURCE, response: status(200) });
    expect(await markReviewed({ sourceId: ID, rowVersion: 3 })).toEqual({
      kind: "ok",
      source: SOURCE,
    });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/knowledge/sources/{source_id}/review", {
      params: { path: { source_id: ID }, header: { "If-Match": '"3"' } },
    });
    api.POST.mockResolvedValue({ error: {}, response: status(412) });
    expect(await markReviewed({ sourceId: ID, rowVersion: 3 })).toEqual({ kind: "stale" });
    api.POST.mockResolvedValue({ error: {}, response: status(409) });
    expect(await retireSource({ sourceId: ID, rowVersion: 3, reason: "x" })).toEqual({
      kind: "conflict",
    });
  });

  it("patches the changed fields", async () => {
    api.PATCH.mockResolvedValue({ data: SOURCE, response: status(200) });
    await editSource({ sourceId: ID, rowVersion: 1, integrationTypeIds: [TAG] });
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/knowledge/sources/{source_id}", {
      params: { path: { source_id: ID }, header: { "If-Match": '"1"' } },
      body: {
        title: undefined,
        product: undefined,
        owner_id: undefined,
        integration_type_ids: [TAG],
      },
    });
    expect(await editSource({ sourceId: "nope", rowVersion: 1 })).toEqual({ kind: "error" });
  });

  it("retries a parse and uploads a version", async () => {
    api.POST.mockResolvedValue({ data: SOURCE, response: status(202) });
    expect(await retryParse(ID)).toEqual({ kind: "ok", source: SOURCE });
    api.POST.mockResolvedValue({ data: SOURCE, response: status(201) });
    const result = await addVersion(
      form({ file: new File(["x"], "a.md"), sourceId: ID, rowVersion: "2", productVersion: "3" }),
    );
    expect(result).toEqual({ kind: "ok", source: SOURCE });
    const [, options] = api.POST.mock.calls.at(-1) as [string, Record<string, unknown>];
    expect(options.params).toEqual({
      path: { source_id: ID },
      query: { product_version: "3" },
      header: { "If-Match": '"2"' },
    });
  });
});
