import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Opportunity } from "@/lib/opportunities";

const api = vi.hoisted(() => ({
  GET: vi.fn(),
  POST: vi.fn(),
  PUT: vi.fn(),
  PATCH: vi.fn(),
  DELETE: vi.fn(),
}));
vi.mock("@/lib/api/server", () => ({ createServerApiClient: async () => api }));
vi.mock("server-only", () => ({}));

import {
  addSource,
  addTextSource,
  changeCollaborator,
  confirmAllRequirements,
  confirmRequirement,
  createOpportunity,
  editRequirement,
  getPassage,
  loadRequirements,
  loadSources,
  retryParse,
  searchUsers,
  startExtraction,
  updateOpportunity,
} from "./actions";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const USER_ID = "00000000-0000-7000-8000-000000000002";
const OPPORTUNITY: Opportunity = {
  id: OPP_ID,
  title: "[TITLE]",
  customer_name: "[CUSTOMER]",
  products: ["AutoStore"],
  industry: "Retail",
  target_proposal_date: "2026-11-01",
  status: "intake",
  owner: { id: USER_ID, name: "[OWNER]" },
  collaborators: [],
  row_version: 4,
  created_at: "2026-10-04T10:00:00Z",
  last_changed_by: "[OTHER]",
  can_manage_collaborators: true,
  can_edit: true,
  can_add_sources: true,
};
const INPUT = {
  title: "  ",
  customer_name: "[CUSTOMER]",
  products: ["AutoStore"],
  industry: "Retail",
  target_proposal_date: "2026-11-01",
};

const status = (code: number) => new Response(null, { status: code });

beforeEach(() => {
  for (const fn of Object.values(api)) fn.mockReset();
});

describe("createOpportunity", () => {
  it("posts the fields (blank title as null) and returns the new id", async () => {
    api.POST.mockResolvedValue({ data: OPPORTUNITY, response: status(201) });
    expect(await createOpportunity(INPUT)).toEqual({ kind: "ok", id: OPP_ID });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities", {
      body: { ...INPUT, title: null },
    });
  });

  it("maps a 422 to the fields the API named", async () => {
    api.POST.mockResolvedValue({
      error: {
        code: "validation_error",
        detail: "Invalid fields: body.products, body.target_proposal_date",
      },
      response: status(422),
    });
    expect(await createOpportunity(INPUT)).toEqual({
      kind: "invalid",
      fields: ["products", "target_proposal_date"],
    });
  });

  it("403 is forbidden; bad input and failures are errors", async () => {
    api.POST.mockResolvedValueOnce({ error: { code: "forbidden" }, response: status(403) });
    expect(await createOpportunity(INPUT)).toEqual({ kind: "forbidden" });
    expect(await createOpportunity({ ...INPUT, products: "AutoStore" })).toEqual({
      kind: "error",
    });
    api.POST.mockRejectedValueOnce(new Error("network"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(await createOpportunity(INPUT)).toEqual({ kind: "error" });
  });
});

describe("changeCollaborator", () => {
  const input = { opportunityId: OPP_ID, userId: USER_ID, add: true, rowVersion: 3 };
  const path = "/api/v1/opportunities/{opportunity_id}/collaborators/{user_id}";
  const init = {
    params: {
      path: { opportunity_id: OPP_ID, user_id: USER_ID },
      header: { "If-Match": '"3"' },
    },
  };

  it("adds with PUT and removes with DELETE, sending the row version as If-Match", async () => {
    api.PUT.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    api.DELETE.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    expect(await changeCollaborator(input)).toEqual({ kind: "ok", opportunity: OPPORTUNITY });
    expect(api.PUT).toHaveBeenCalledWith(path, init);
    await changeCollaborator({ ...input, add: false });
    expect(api.DELETE).toHaveBeenCalledWith(path, init);
  });

  it("on 412 reports who changed it last and does not retry", async () => {
    api.PUT.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    expect(await changeCollaborator(input)).toEqual({ kind: "stale", changedBy: "[OTHER]" });
    expect(api.PUT).toHaveBeenCalledTimes(1);
  });

  it("maps 422, 403 and 404", async () => {
    api.PUT.mockResolvedValueOnce({
      error: { code: "invalid_collaborator", detail: "The owner can't be added." },
      response: status(422),
    });
    expect(await changeCollaborator(input)).toEqual({
      kind: "invalid",
      detail: "The owner can't be added.",
    });
    api.PUT.mockResolvedValueOnce({ error: {}, response: status(403) });
    expect(await changeCollaborator(input)).toEqual({ kind: "forbidden" });
    api.PUT.mockResolvedValueOnce({ error: {}, response: status(404) });
    expect(await changeCollaborator(input)).toEqual({ kind: "not-found" });
  });

  it("rejects malformed input without calling the API", async () => {
    expect(await changeCollaborator({ ...input, userId: "x" })).toEqual({ kind: "error" });
    expect(await changeCollaborator({ ...input, rowVersion: -1 })).toEqual({ kind: "error" });
    expect(api.PUT).not.toHaveBeenCalled();
  });
});

describe("updateOpportunity", () => {
  const path = "/api/v1/opportunities/{opportunity_id}";
  const params = { path: { opportunity_id: OPP_ID }, header: { "If-Match": '"4"' } };
  const input = { opportunityId: OPP_ID, rowVersion: 4, title: "New" };

  it("patches only the given fields with the row version as If-Match", async () => {
    api.PATCH.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    expect(await updateOpportunity(input)).toEqual({ kind: "ok", opportunity: OPPORTUNITY });
    expect(api.PATCH).toHaveBeenLastCalledWith(path, { params, body: { title: "New" } });
    await updateOpportunity({
      opportunityId: OPP_ID,
      rowVersion: 4,
      target_proposal_date: "2026-12-24",
    });
    expect(api.PATCH).toHaveBeenLastCalledWith(path, {
      params,
      body: { target_proposal_date: "2026-12-24" },
    });
  });

  it("on 412 reports who changed it last and does not retry", async () => {
    api.PATCH.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue({ data: OPPORTUNITY, response: status(200) });
    expect(await updateOpportunity(input)).toEqual({ kind: "stale", changedBy: "[OTHER]" });
    expect(api.PATCH).toHaveBeenCalledTimes(1);
  });

  it("maps 422 to a readable reason, and 403, 404 and failures", async () => {
    const invalid = (detail: string) => ({
      error: { code: "validation_error", detail },
      response: status(422),
    });
    api.PATCH.mockResolvedValueOnce(invalid("The target proposal date can't be in the past."));
    expect(await updateOpportunity(input)).toEqual({
      kind: "invalid",
      detail: "The target proposal date can't be in the past.",
    });
    api.PATCH.mockResolvedValueOnce(invalid("Invalid fields: body.title"));
    expect(await updateOpportunity(input)).toEqual({
      kind: "invalid",
      detail: "The title can be at most 200 characters.",
    });
    api.PATCH.mockResolvedValueOnce(invalid("Invalid fields: body.target_proposal_date"));
    expect(await updateOpportunity(input)).toEqual({
      kind: "invalid",
      detail: "Enter a valid date.",
    });
    api.PATCH.mockResolvedValueOnce({ error: {}, response: status(403) });
    expect(await updateOpportunity(input)).toEqual({ kind: "forbidden" });
    api.PATCH.mockResolvedValueOnce({ error: {}, response: status(404) });
    expect(await updateOpportunity(input)).toEqual({ kind: "not-found" });
    api.PATCH.mockRejectedValueOnce(new Error("network"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(await updateOpportunity(input)).toEqual({ kind: "error" });
  });

  it("rejects malformed input without calling the API", async () => {
    const base = { opportunityId: OPP_ID, rowVersion: 4 };
    for (const bad of [
      base, // nothing to change
      { ...base, opportunityId: "x", title: "t" },
      { ...base, rowVersion: -1, title: "t" },
      { ...base, rowVersion: 1.5, title: "t" },
      { ...base, title: 3 },
      { ...base, target_proposal_date: "24/12/2026" },
      null,
    ]) {
      expect(await updateOpportunity(bad)).toEqual({ kind: "error" });
    }
    expect(api.PATCH).not.toHaveBeenCalled();
  });
});

describe("searchUsers", () => {
  it("skips queries shorter than two code points and cuts long ones by code point", async () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: status(200) });
    expect(await searchUsers(" a ")).toEqual({ kind: "ok", users: [] });
    expect(await searchUsers("😀")).toEqual({ kind: "ok", users: [] });
    expect(api.GET).not.toHaveBeenCalled();
    await searchUsers("😀".repeat(101));
    const sent: string = api.GET.mock.calls[0][1].params.query.q;
    expect(Array.from(sent)).toHaveLength(100);
    expect(sent).toBe("😀".repeat(100)); // no half surrogate pair at the end
  });

  it("searches by the trimmed query and skips blank ones", async () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: status(200) });
    expect(await searchUsers("  ")).toEqual({ kind: "ok", users: [] });
    expect(api.GET).not.toHaveBeenCalled();
    await searchUsers(" ann ");
    expect(api.GET).toHaveBeenCalledWith("/api/v1/users/search", {
      params: { query: { q: "ann", limit: 10 } },
    });
  });
});

describe("addSource", () => {
  const SOURCE = {
    id: "00000000-0000-7000-8000-0000000000d4",
    kind: "transcript",
    filename: "call.vtt",
    version: 1,
    version_count: 1,
    size_bytes: 6,
    uploaded_by: { id: USER_ID, name: "[OWNER]" },
    uploaded_at: "2026-10-04T10:00:00Z",
    created_at: "2026-10-04T10:00:00Z",
    parse: { status: "queued", error_code: null },
  };

  function form(file: File | string | null = new File(["WEBVTT"], "call.vtt")) {
    const data = new FormData();
    data.append("opportunityId", OPP_ID);
    if (file !== null) data.append("file", file);
    return data;
  }

  /** The FormData the action hands to openapi-fetch (through its bodySerializer). */
  function sentForm(): FormData {
    const init = api.POST.mock.calls[0][1];
    return init.bodySerializer(init.body);
  }

  it("posts the file as multipart to the Opportunity's sources", async () => {
    api.POST.mockResolvedValue({ data: SOURCE, response: status(201) });
    expect(await addSource(form())).toEqual({ kind: "ok", source: SOURCE });
    const [path, init] = api.POST.mock.calls[0];
    expect(path).toBe("/api/v1/opportunities/{opportunity_id}/sources");
    expect(init.params).toEqual({ path: { opportunity_id: OPP_ID } });
    const file = sentForm().get("file");
    expect(file).toBeInstanceOf(File);
    expect((file as File).name).toBe("call.vtt");
    expect(await (file as File).text()).toBe("WEBVTT");
  });

  it("forwards a 50 MB file whole", async () => {
    api.POST.mockResolvedValue({ data: SOURCE, response: status(201) });
    const big = new File([new Uint8Array(50 * 1024 * 1024)], "big.pdf");
    expect((await addSource(form(big))).kind).toBe("ok");
    expect((sentForm().get("file") as File).size).toBe(50 * 1024 * 1024);
  });

  it("a 422 keeps the API's 'Rejected: ...' sentence", async () => {
    api.POST.mockResolvedValueOnce({
      error: { code: "file_type_not_allowed", detail: "Rejected: .exe files aren't allowed" },
      response: status(422),
    });
    expect(await addSource(form(new File(["MZ"], "setup.exe")))).toEqual({
      kind: "rejected",
      reason: "Rejected: .exe files aren't allowed",
    });
    api.POST.mockResolvedValueOnce({
      error: { code: "validation_error", detail: "Invalid fields: body.file" },
      response: status(422),
    });
    expect(await addSource(form())).toEqual({
      kind: "rejected",
      reason: "Rejected: the file couldn't be read",
    });
  });

  it("maps 403, 404 and failures", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValueOnce({ error: { code: "forbidden" }, response: status(403) });
    expect(await addSource(form())).toEqual({ kind: "forbidden" });
    api.POST.mockResolvedValueOnce({ error: { code: "not_found" }, response: status(404) });
    expect(await addSource(form())).toEqual({ kind: "not-found" });
    api.POST.mockResolvedValueOnce({ error: { code: "internal_error" }, response: status(500) });
    expect(await addSource(form())).toEqual({ kind: "error" });
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await addSource(form())).toEqual({ kind: "error" });
  });

  it("rejects malformed input without calling the API", async () => {
    const badId = new FormData();
    badId.append("opportunityId", "not-a-uuid");
    badId.append("file", new File(["x"], "a.txt"));
    for (const bad of [badId, form(null), form("not a file"), { file: "x" }, null]) {
      expect(await addSource(bad)).toEqual({ kind: "error" });
    }
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("addTextSource", () => {
  const SOURCE = {
    id: "00000000-0000-7000-8000-0000000000d5",
    kind: "note",
    filename: "Pasted text",
    version: 1,
    version_count: 1,
    size_bytes: 23,
    uploaded_by: { id: USER_ID, name: "[OWNER]" },
    uploaded_at: "2026-10-04T10:00:00Z",
    created_at: "2026-10-04T10:00:00Z",
    parse: { status: "queued", error_code: null },
  };

  it("posts the text as JSON to the Opportunity's text sources", async () => {
    api.POST.mockResolvedValue({ data: SOURCE, response: status(201) });
    const text = "  Customer needs SAP sync\n";
    expect(await addTextSource(OPP_ID, text)).toEqual({ kind: "ok", source: SOURCE });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/sources/text", {
      params: { path: { opportunity_id: OPP_ID } },
      body: { text },
    });
  });

  it("a 422 keeps the API's 'Rejected: ...' sentence", async () => {
    api.POST.mockResolvedValueOnce({
      error: { code: "file_empty", detail: "Rejected: the text is empty" },
      response: status(422),
    });
    expect(await addTextSource(OPP_ID, " ")).toEqual({
      kind: "rejected",
      reason: "Rejected: the text is empty",
    });
    api.POST.mockResolvedValueOnce({
      error: { code: "validation_error", detail: "Invalid fields: body.text" },
      response: status(422),
    });
    expect(await addTextSource(OPP_ID, "x")).toEqual({
      kind: "rejected",
      reason: "Rejected: the text couldn't be read",
    });
  });

  it("maps 403, 404 and failures", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValueOnce({ error: { code: "forbidden" }, response: status(403) });
    expect(await addTextSource(OPP_ID, "x")).toEqual({ kind: "forbidden" });
    api.POST.mockResolvedValueOnce({ error: { code: "not_found" }, response: status(404) });
    expect(await addTextSource(OPP_ID, "x")).toEqual({ kind: "not-found" });
    api.POST.mockResolvedValueOnce({ error: { code: "internal_error" }, response: status(500) });
    expect(await addTextSource(OPP_ID, "x")).toEqual({ kind: "error" });
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await addTextSource(OPP_ID, "x")).toEqual({ kind: "error" });
  });

  it("rejects malformed input without calling the API", async () => {
    for (const [id, text] of [
      ["not-a-uuid", "x"],
      [null, "x"],
      [OPP_ID, null],
      [OPP_ID, 42],
    ]) {
      expect(await addTextSource(id, text)).toEqual({ kind: "error" });
    }
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("retryParse", () => {
  const SOURCE_ID = "00000000-0000-7000-8000-0000000000d6";
  const SOURCE = {
    id: SOURCE_ID,
    kind: "document",
    filename: "rfp.pdf",
    version: 1,
    version_count: 1,
    size_bytes: 6,
    uploaded_by: { id: USER_ID, name: "[OWNER]" },
    uploaded_at: "2026-10-04T10:00:00Z",
    created_at: "2026-10-04T10:00:00Z",
    parse: { status: "queued", error_code: null },
  };

  beforeEach(() => api.POST.mockReset());

  it("posts to the parse route and returns the requeued Source", async () => {
    api.POST.mockResolvedValue({ data: SOURCE, response: new Response(null, { status: 202 }) });
    expect(await retryParse(OPP_ID, SOURCE_ID)).toEqual({ kind: "ok", source: SOURCE });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/sources/{source_id}/parse",
      { params: { path: { opportunity_id: OPP_ID, source_id: SOURCE_ID } } },
    );
  });

  it.each([
    [409, "conflict"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({
      error: { code: "x" },
      response: new Response(null, { status }),
    });
    expect(await retryParse(OPP_ID, SOURCE_ID)).toEqual({ kind });
  });

  it("refuses ids that aren't UUIDs without calling the API", async () => {
    expect(await retryParse("nope", SOURCE_ID)).toEqual({ kind: "error" });
    expect(await retryParse(OPP_ID, 42)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("loadSources", () => {
  it("reads the Opportunity's Sources", async () => {
    api.GET.mockReset();
    api.GET.mockResolvedValue({
      data: { items: [] },
      response: new Response(null, { status: 200 }),
    });
    expect(await loadSources(OPP_ID)).toEqual({ kind: "ok", sources: [] });
    expect(await loadSources(7)).toEqual({ kind: "error" });
    expect(await loadSources("../../users")).toEqual({ kind: "error" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });
});

describe("startExtraction", () => {
  const QUEUED = { status: "queued", error_code: null, source_count: null };

  beforeEach(() => api.POST.mockReset());

  it("posts to the extractions route and returns the queued extraction", async () => {
    api.POST.mockResolvedValue({ data: QUEUED, response: new Response(null, { status: 201 }) });
    expect(await startExtraction(OPP_ID)).toEqual({ kind: "ok", extraction: QUEUED });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/extractions", {
      params: { path: { opportunity_id: OPP_ID } },
    });
  });

  it.each([
    [409, "conflict"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: new Response(null, { status }) });
    expect(await startExtraction(OPP_ID)).toEqual({ kind });
  });

  it("is an error when the call throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await startExtraction(OPP_ID)).toEqual({ kind: "error" });
  });

  it("refuses an id that isn't a UUID without calling the API", async () => {
    expect(await startExtraction("nope")).toEqual({ kind: "error" });
    expect(await startExtraction(undefined)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("loadRequirements", () => {
  it("reads the Opportunity's Requirements and latest extraction", async () => {
    const LIST = { items: [], extraction: null, can_start_extraction: false };
    api.GET.mockReset();
    api.GET.mockResolvedValue({ data: LIST, response: new Response(null, { status: 200 }) });
    expect(await loadRequirements(OPP_ID)).toEqual({ kind: "ok", list: LIST });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/requirements", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await loadRequirements(7)).toEqual({ kind: "error" });
    expect(await loadRequirements("../../users")).toEqual({ kind: "error" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("is an error when the API fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockReset();
    api.GET.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    expect(await loadRequirements(OPP_ID)).toEqual({ kind: "error" });
  });
});

describe("getPassage", () => {
  const PASSAGE_ID = "00000000-0000-7000-8000-0000000000a1";
  const PASSAGE = {
    passage_id: PASSAGE_ID,
    source_id: "00000000-0000-7000-8000-0000000000b1",
    source_version: 2,
    filename: "call.vtt",
    label: "S1 · call.vtt",
    before: "[BEFORE] ",
    text: "[QUOTE]",
    after: " [AFTER]…",
  };

  it("reads the passage route", async () => {
    api.GET.mockResolvedValue({ data: PASSAGE, response: status(200) });
    expect(await getPassage(OPP_ID, PASSAGE_ID)).toEqual({ kind: "ok", passage: PASSAGE });
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/passages/{passage_id}",
      { params: { path: { opportunity_id: OPP_ID, passage_id: PASSAGE_ID } } },
    );
  });

  it.each([
    [404, "not-found"],
    [500, "error"],
    [401, "error"],
  ])("maps %i to %s", async (code, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockResolvedValue({ error: { code: "x" }, response: status(code) });
    expect(await getPassage(OPP_ID, PASSAGE_ID)).toEqual({ kind });
  });

  it("is an error when the call throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockRejectedValueOnce(new Error("network"));
    expect(await getPassage(OPP_ID, PASSAGE_ID)).toEqual({ kind: "error" });
  });

  it("refuses ids that aren't UUIDs without calling the API", async () => {
    expect(await getPassage("nope", PASSAGE_ID)).toEqual({ kind: "error" });
    expect(await getPassage(OPP_ID, "../x")).toEqual({ kind: "error" });
    expect(await getPassage(OPP_ID, undefined)).toEqual({ kind: "error" });
    expect(api.GET).not.toHaveBeenCalled();
  });
});

describe("editRequirement / confirmRequirement / confirmAllRequirements", () => {
  const REQ_ID = "00000000-0000-7000-8000-0000000000c1";
  const REQ = {
    id: REQ_ID,
    text: "[TEXT]",
    row_version: 3,
    last_changed_by: null,
  };
  const ok = (data: unknown) => ({
    data,
    response: new Response(null, { status: 200 }),
  });

  it("PATCHes the text and classification with If-Match", async () => {
    api.PATCH.mockResolvedValue(ok(REQ));
    const input = {
      opportunityId: OPP_ID,
      requirementId: REQ_ID,
      rowVersion: 2,
      text: "[TEXT]",
      classification: "security",
    };
    expect(await editRequirement(input)).toEqual({
      kind: "ok",
      requirement: REQ,
    });
    expect(api.PATCH).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}",
      {
        params: {
          path: { opportunity_id: OPP_ID, requirement_id: REQ_ID },
          header: { "If-Match": '"2"' },
        },
        body: { text: "[TEXT]", classification: "security" },
      },
    );
  });

  it("refuses bad input without calling the API", async () => {
    const base = {
      opportunityId: OPP_ID,
      requirementId: REQ_ID,
      rowVersion: 1,
    };
    expect(await editRequirement(base)).toEqual({ kind: "error" }); // nothing to change
    expect(await editRequirement({ ...base, classification: "nice" })).toEqual({
      kind: "error",
    });
    expect(await editRequirement({ ...base, requirementId: "x", text: "a" })).toEqual({
      kind: "error",
    });
    expect(await confirmRequirement({ ...base, rowVersion: -1 })).toEqual({
      kind: "error",
    });
    expect(await confirmAllRequirements("nope")).toEqual({ kind: "error" });
    expect(api.PATCH).not.toHaveBeenCalled();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("on 412 reads who changed the Requirement", async () => {
    api.PATCH.mockResolvedValue({
      error: { code: "row_version_mismatch" },
      response: status(412),
    });
    api.GET.mockResolvedValue(
      ok({
        items: [{ ...REQ, last_changed_by: { id: USER_ID, name: "[OTHER]" } }],
      }),
    );
    expect(
      await editRequirement({
        opportunityId: OPP_ID,
        requirementId: REQ_ID,
        rowVersion: 1,
        text: "a",
      }),
    ).toEqual({ kind: "stale", changedBy: "[OTHER]" });
  });

  it.each([
    [422, { kind: "invalid", detail: "The Requirement text can't be blank." }],
    [403, { kind: "forbidden" }],
    [404, { kind: "not-found" }],
    [500, { kind: "error" }],
  ])("maps %i on confirm", async (code, expected) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({
      error: { code: "x", detail: "The Requirement text can't be blank." },
      response: status(code),
    });
    expect(
      await confirmRequirement({
        opportunityId: OPP_ID,
        requirementId: REQ_ID,
        rowVersion: 1,
      }),
    ).toEqual(expected);
  });

  it.each([
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i on confirm all to %s", async (code, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: status(code) });
    expect(await confirmAllRequirements(OPP_ID)).toEqual({ kind });
  });

  it("POSTs confirm with If-Match, and confirm-all without", async () => {
    api.POST.mockResolvedValueOnce(ok(REQ)).mockResolvedValueOnce(ok({ count: 3 }));
    await confirmRequirement({
      opportunityId: OPP_ID,
      requirementId: REQ_ID,
      rowVersion: 5,
    });
    expect(await confirmAllRequirements(OPP_ID)).toEqual({
      kind: "ok",
      count: 3,
    });
    expect(api.POST.mock.calls).toEqual([
      [
        "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/confirm",
        {
          params: {
            path: { opportunity_id: OPP_ID, requirement_id: REQ_ID },
            header: { "If-Match": '"5"' },
          },
        },
      ],
      [
        "/api/v1/opportunities/{opportunity_id}/requirements/confirm-all",
        { params: { path: { opportunity_id: OPP_ID } } },
      ],
    ]);
  });
});
