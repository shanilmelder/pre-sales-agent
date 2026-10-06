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
  acceptAllAssumptions,
  acceptAssumption,
  addSource,
  addTextSource,
  approveAllClarificationQuestions,
  cancelAssessmentRun,
  approveClarificationQuestion,
  changeCollaborator,
  confirmAllRequirements,
  confirmRequirement,
  createOpportunity,
  editClarificationQuestion,
  editEstimateLine,
  editRequirement,
  getPassage,
  importFile,
  loadAssessments,
  loadEstimate,
  loadGaps,
  loadImport,
  loadRedTeam,
  loadRequirements,
  loadSources,
  retryAssessmentTask,
  retryParse,
  searchUsers,
  startAssessmentRun,
  startEstimateDraft,
  startExtraction,
  startGapDetection,
  startRedTeamReview,
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

describe("createOpportunity with an import", () => {
  const IMPORT_ID = "00000000-0000-7000-8000-0000000000e1";

  it("sends the import id", async () => {
    api.POST.mockResolvedValue({ data: OPPORTUNITY, response: status(201) });
    expect(await createOpportunity({ ...INPUT, importId: IMPORT_ID })).toEqual({
      kind: "ok",
      id: OPP_ID,
    });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities", {
      body: { ...INPUT, title: null, import_id: IMPORT_ID },
    });
  });

  it.each([404, 409, 410])("maps %i for the import to import-unusable", async (code) => {
    api.POST.mockResolvedValueOnce({ error: { code: "x" }, response: status(code) });
    expect(await createOpportunity({ ...INPUT, importId: IMPORT_ID })).toEqual({
      kind: "import-unusable",
    });
  });

  it("refuses a malformed import id without calling the API", async () => {
    expect(await createOpportunity({ ...INPUT, importId: "nope" })).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("importFile and loadImport", () => {
  const IMPORTED = {
    id: "00000000-0000-7000-8000-0000000000e1",
    filename: "follow-up.eml",
    size_bytes: 10,
    status: "queued",
    error_code: null,
    suggestions: null,
    created_at: "2026-10-06T10:00:00Z",
  };

  function form(file: File | null = new File(["From: x"], "follow-up.eml")) {
    const data = new FormData();
    if (file !== null) data.append("file", file);
    return data;
  }

  it("posts the file as multipart to the imports", async () => {
    api.POST.mockResolvedValue({ data: IMPORTED, response: status(202) });
    expect(await importFile(form())).toEqual({ kind: "ok", import: IMPORTED });
    const [path, init] = api.POST.mock.calls[0];
    expect(path).toBe("/api/v1/opportunity-imports");
    const file = (init.bodySerializer(init.body) as FormData).get("file") as File;
    expect(file.name).toBe("follow-up.eml");
    expect(await file.text()).toBe("From: x");
  });

  it("passes on the API's rejection sentence for 413, 415 and 422", async () => {
    for (const [code, detail] of [
      [415, "Rejected: .exe files aren't allowed"],
      [413, "Rejected: larger than 50 MB"],
      [422, "Rejected: this file is empty"],
    ] as const) {
      api.POST.mockResolvedValueOnce({ error: { code: "x", detail }, response: status(code) });
      expect(await importFile(form())).toEqual({ kind: "rejected", reason: detail });
    }
    api.POST.mockResolvedValueOnce({ error: { code: "forbidden" }, response: status(403) });
    expect(await importFile(form())).toEqual({ kind: "forbidden" });
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await importFile(form())).toEqual({ kind: "error" });
    expect(await importFile(form(null))).toEqual({ kind: "error" });
  });

  it("reads an import, and 404/410 are gone", async () => {
    api.GET.mockResolvedValueOnce({ data: IMPORTED, response: status(200) });
    expect(await loadImport(IMPORTED.id)).toEqual({ kind: "ok", import: IMPORTED });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/opportunity-imports/{import_id}", {
      params: { path: { import_id: IMPORTED.id } },
    });
    api.GET.mockResolvedValueOnce({ error: { code: "import_expired" }, response: status(410) });
    expect(await loadImport(IMPORTED.id)).toEqual({ kind: "gone" });
    api.GET.mockResolvedValueOnce({ error: { code: "not_found" }, response: status(404) });
    expect(await loadImport(IMPORTED.id)).toEqual({ kind: "gone" });
    expect(await loadImport("nope")).toEqual({ kind: "error" });
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

describe("startGapDetection", () => {
  const QUEUED = { status: "queued", error_code: null };

  beforeEach(() => api.POST.mockReset());

  it("posts to the gap-detections route and returns the queued detection", async () => {
    api.POST.mockResolvedValue({ data: QUEUED, response: new Response(null, { status: 201 }) });
    expect(await startGapDetection(OPP_ID)).toEqual({ kind: "ok", detection: QUEUED });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/gap-detections",
      { params: { path: { opportunity_id: OPP_ID } } },
    );
  });

  it.each([
    [409, "conflict"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: new Response(null, { status }) });
    expect(await startGapDetection(OPP_ID)).toEqual({ kind });
  });

  it("is an error when the call throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await startGapDetection(OPP_ID)).toEqual({ kind: "error" });
  });

  it("refuses an id that isn't a UUID without calling the API", async () => {
    expect(await startGapDetection("nope")).toEqual({ kind: "error" });
    expect(await startGapDetection(undefined)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("loadGaps", () => {
  it("reads the Opportunity's open Gaps and latest detection", async () => {
    const LIST = {
      items: [],
      detection: null,
      can_start_detection: false,
      can_edit_questions: false,
    };
    api.GET.mockReset();
    api.GET.mockResolvedValue({ data: LIST, response: new Response(null, { status: 200 }) });
    expect(await loadGaps(OPP_ID)).toEqual({ kind: "ok", list: LIST });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/gaps", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await loadGaps(7)).toEqual({ kind: "error" });
    expect(await loadGaps("../../users")).toEqual({ kind: "error" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("is an error when the API fails", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockReset();
    api.GET.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    expect(await loadGaps(OPP_ID)).toEqual({ kind: "error" });
  });
});

describe("startEstimateDraft", () => {
  const QUEUED = { status: "queued", error_code: null };

  beforeEach(() => api.POST.mockReset());

  it("posts to the estimate-drafts route and returns the queued draft", async () => {
    api.POST.mockResolvedValue({ data: QUEUED, response: new Response(null, { status: 201 }) });
    expect(await startEstimateDraft(OPP_ID)).toEqual({ kind: "ok", draft: QUEUED });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/estimate-drafts",
      { params: { path: { opportunity_id: OPP_ID } } },
    );
  });

  it.each([
    [409, "conflict"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: new Response(null, { status }) });
    expect(await startEstimateDraft(OPP_ID)).toEqual({ kind });
  });

  it("is an error when the call throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await startEstimateDraft(OPP_ID)).toEqual({ kind: "error" });
  });

  it("refuses an id that isn't a UUID without calling the API", async () => {
    expect(await startEstimateDraft("nope")).toEqual({ kind: "error" });
    expect(await startEstimateDraft(undefined)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("loadEstimate", () => {
  it("reads the Opportunity's Estimate and latest draft", async () => {
    const VIEW = { version: null, draft: null, can_start_draft: false };
    api.GET.mockReset();
    api.GET.mockResolvedValue({ data: VIEW, response: new Response(null, { status: 200 }) });
    expect(await loadEstimate(OPP_ID)).toEqual({ kind: "ok", estimate: VIEW });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/estimate", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await loadEstimate(7)).toEqual({ kind: "error" });
    expect(await loadEstimate("../../users")).toEqual({ kind: "error" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("is an error when the API fails or throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockReset();
    api.GET.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    expect(await loadEstimate(OPP_ID)).toEqual({ kind: "error" });
    api.GET.mockRejectedValueOnce(new Error("network"));
    expect(await loadEstimate(OPP_ID)).toEqual({ kind: "error" });
  });
});

describe("startRedTeamReview", () => {
  const QUEUED = { status: "queued", error_code: null };

  beforeEach(() => api.POST.mockReset());

  it("posts to the red-team-reviews route and returns the queued run", async () => {
    api.POST.mockResolvedValue({ data: QUEUED, response: new Response(null, { status: 201 }) });
    expect(await startRedTeamReview(OPP_ID)).toEqual({ kind: "ok", run: QUEUED });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/red-team-reviews",
      { params: { path: { opportunity_id: OPP_ID } } },
    );
  });

  it.each([
    [409, "conflict"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: new Response(null, { status }) });
    expect(await startRedTeamReview(OPP_ID)).toEqual({ kind });
  });

  it("is an error when the call throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await startRedTeamReview(OPP_ID)).toEqual({ kind: "error" });
  });

  it("refuses an id that isn't a UUID without calling the API", async () => {
    expect(await startRedTeamReview("nope")).toEqual({ kind: "error" });
    expect(await startRedTeamReview(undefined)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("loadRedTeam", () => {
  it("reads the Opportunity's Red Team Review and latest run", async () => {
    const VIEW = { review: null, run: null, can_start: false };
    api.GET.mockReset();
    api.GET.mockResolvedValue({ data: VIEW, response: new Response(null, { status: 200 }) });
    expect(await loadRedTeam(OPP_ID)).toEqual({ kind: "ok", redTeam: VIEW });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/red-team", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await loadRedTeam(7)).toEqual({ kind: "error" });
    expect(await loadRedTeam("../../users")).toEqual({ kind: "error" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("is an error when the API fails or throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockReset();
    api.GET.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    expect(await loadRedTeam(OPP_ID)).toEqual({ kind: "error" });
    api.GET.mockRejectedValueOnce(new Error("network"));
    expect(await loadRedTeam(OPP_ID)).toEqual({ kind: "error" });
  });
});

describe("startAssessmentRun / retryAssessmentTask / cancelAssessmentRun", () => {
  const RUN_ID = "00000000-0000-7000-8000-0000000000b1";
  const RUN = { id: RUN_ID, status: "queued", tasks: [] };

  beforeEach(() => api.POST.mockReset());

  it("posts to the assessment-runs route and returns the queued run", async () => {
    api.POST.mockResolvedValue({ data: RUN, response: new Response(null, { status: 201 }) });
    expect(await startAssessmentRun(OPP_ID)).toEqual({ kind: "ok", run: RUN });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs",
      { params: { path: { opportunity_id: OPP_ID } } },
    );
  });

  it("posts one agent's retry to the task route", async () => {
    api.POST.mockResolvedValue({ data: RUN, response: new Response(null, { status: 200 }) });
    expect(await retryAssessmentTask(OPP_ID, RUN_ID, "security_agent")).toEqual({
      kind: "ok",
      run: RUN,
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs/{run_id}/tasks/{agent}/retry",
      { params: { path: { opportunity_id: OPP_ID, run_id: RUN_ID, agent: "security_agent" } } },
    );
  });

  it("posts a cancel to the run's cancel route", async () => {
    const cancelled = { ...RUN, status: "cancelled" };
    api.POST.mockResolvedValue({ data: cancelled, response: new Response(null, { status: 200 }) });
    expect(await cancelAssessmentRun(OPP_ID, RUN_ID)).toEqual({ kind: "ok", run: cancelled });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs/{run_id}/cancel",
      { params: { path: { opportunity_id: OPP_ID, run_id: RUN_ID } } },
    );
  });

  it.each([
    [409, "conflict"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: new Response(null, { status }) });
    expect(await startAssessmentRun(OPP_ID)).toEqual({ kind });
    expect(await retryAssessmentTask(OPP_ID, RUN_ID, "pm_agent")).toEqual({ kind });
    expect(await cancelAssessmentRun(OPP_ID, RUN_ID)).toEqual({ kind });
  });

  it("is an error when the call throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await startAssessmentRun(OPP_ID)).toEqual({ kind: "error" });
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await retryAssessmentTask(OPP_ID, RUN_ID, "pm_agent")).toEqual({ kind: "error" });
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await cancelAssessmentRun(OPP_ID, RUN_ID)).toEqual({ kind: "error" });
  });

  it("refuses bad ids or an unknown agent without calling the API", async () => {
    expect(await startAssessmentRun("nope")).toEqual({ kind: "error" });
    expect(await retryAssessmentTask("nope", RUN_ID, "pm_agent")).toEqual({ kind: "error" });
    expect(await retryAssessmentTask(OPP_ID, "nope", "pm_agent")).toEqual({ kind: "error" });
    expect(await retryAssessmentTask(OPP_ID, RUN_ID, "red_team_agent")).toEqual({
      kind: "error",
    });
    expect(await cancelAssessmentRun("nope", RUN_ID)).toEqual({ kind: "error" });
    expect(await cancelAssessmentRun(OPP_ID, undefined)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("loadAssessments", () => {
  it("reads the Opportunity's latest run and current Assessments", async () => {
    const VIEW = { run: null, assessments: [], can_start: false };
    api.GET.mockReset();
    api.GET.mockResolvedValue({ data: VIEW, response: new Response(null, { status: 200 }) });
    expect(await loadAssessments(OPP_ID)).toEqual({ kind: "ok", assessments: VIEW });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/assessments", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await loadAssessments(7)).toEqual({ kind: "error" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("is an error when the API fails or throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockReset();
    api.GET.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    expect(await loadAssessments(OPP_ID)).toEqual({ kind: "error" });
    api.GET.mockRejectedValueOnce(new Error("network"));
    expect(await loadAssessments(OPP_ID)).toEqual({ kind: "error" });
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

describe("acceptAssumption", () => {
  const AID = "00000000-0000-7000-8000-0000000000a1";
  const INPUT = { opportunityId: OPP_ID, assumptionId: AID, rowVersion: 1 };
  const ACCEPTED = {
    id: AID,
    accepted_by: { id: USER_ID, name: "[OWNER]" },
    row_version: 2,
  };

  beforeEach(() => {
    api.POST.mockReset();
    api.GET.mockReset();
  });

  it("posts with If-Match and returns the accepted Assumption", async () => {
    api.POST.mockResolvedValue({
      data: ACCEPTED,
      response: new Response(null, { status: 200 }),
    });
    expect(await acceptAssumption(INPUT)).toEqual({
      kind: "ok",
      assumption: ACCEPTED,
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assumptions/{assumption_id}/accept",
      {
        params: {
          path: { opportunity_id: OPP_ID, assumption_id: AID },
          header: { "If-Match": '"1"' },
        },
      },
    );
  });

  it("on 412 names who accepted it, read again", async () => {
    api.POST.mockResolvedValue({
      error: { code: "row_version_mismatch" },
      response: new Response(null, { status: 412 }),
    });
    api.GET.mockResolvedValue({
      data: {
        version: {
          assumptions: {
            conditions: [
              { id: AID, accepted_by: { id: USER_ID, name: "[OTHER]" } },
            ],
            contingencies: [],
          },
        },
      },
      response: new Response(null, { status: 200 }),
    });
    expect(await acceptAssumption(INPUT)).toEqual({
      kind: "stale",
      changedBy: "[OTHER]",
    });
  });

  it.each([
    [409, "gap-not-open"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({
      error: { code: "x" },
      response: new Response(null, { status }),
    });
    expect(await acceptAssumption(INPUT)).toEqual({ kind });
  });

  it("refuses bad input without calling the API", async () => {
    expect(await acceptAssumption({ ...INPUT, assumptionId: "nope" })).toEqual({
      kind: "error",
    });
    expect(await acceptAssumption({ ...INPUT, rowVersion: 1.5 })).toEqual({
      kind: "error",
    });
    expect(await acceptAssumption(null)).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("is an error when the call throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockRejectedValueOnce(new Error("network"));
    expect(await acceptAssumption(INPUT)).toEqual({ kind: "error" });
  });
});

describe("acceptAllAssumptions", () => {
  beforeEach(() => api.POST.mockReset());

  it("posts to accept-all and returns the count", async () => {
    api.POST.mockResolvedValue({
      data: { count: 3 },
      response: new Response(null, { status: 200 }),
    });
    expect(await acceptAllAssumptions(OPP_ID)).toEqual({
      kind: "ok",
      count: 3,
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assumptions/accept-all",
      { params: { path: { opportunity_id: OPP_ID } } },
    );
  });

  it.each([
    [409, "gap-not-open"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({
      error: { code: "x" },
      response: new Response(null, { status }),
    });
    expect(await acceptAllAssumptions(OPP_ID)).toEqual({ kind });
  });

  it("refuses an id that isn't a UUID", async () => {
    expect(await acceptAllAssumptions("nope")).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("editClarificationQuestion / approveClarificationQuestion / approveAll", () => {
  const Q_ID = "00000000-0000-7000-8000-0000000000d1";
  const QUESTION = { id: Q_ID, text: "[QUESTION]", topic: "[TOPIC]", row_version: 3 };
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
  const base = { opportunityId: OPP_ID, questionId: Q_ID, rowVersion: 2 };

  it("PATCHes the text and topic with If-Match", async () => {
    api.PATCH.mockResolvedValue(ok(QUESTION));
    expect(
      await editClarificationQuestion({ ...base, text: "[QUESTION]", topic: "[TOPIC]" }),
    ).toEqual({ kind: "ok", question: QUESTION });
    expect(api.PATCH).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}",
      {
        params: {
          path: { opportunity_id: OPP_ID, question_id: Q_ID },
          header: { "If-Match": '"2"' },
        },
        body: { text: "[QUESTION]", topic: "[TOPIC]" },
      },
    );
  });

  it("refuses bad input without calling the API", async () => {
    expect(await editClarificationQuestion(base)).toEqual({ kind: "error" }); // nothing to change
    expect(await editClarificationQuestion({ ...base, topic: 7 })).toEqual({ kind: "error" });
    expect(await editClarificationQuestion({ ...base, questionId: "x", text: "a" })).toEqual({
      kind: "error",
    });
    expect(await approveClarificationQuestion({ ...base, rowVersion: -1 })).toEqual({
      kind: "error",
    });
    expect(await approveAllClarificationQuestions("nope", [])).toEqual({ kind: "error" });
    expect(
      await approveAllClarificationQuestions(OPP_ID, [{ id: "x", row_version: 1 }]),
    ).toEqual({ kind: "error" });
    expect(await approveAllClarificationQuestions(OPP_ID, undefined)).toEqual({ kind: "error" });
    expect(api.PATCH).not.toHaveBeenCalled();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("on 412 reads who last changed the question", async () => {
    api.PATCH.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue(
      ok({
        items: [
          { id: "g", question: { ...QUESTION, last_changed_by: { id: USER_ID, name: "[OTHER]" } } },
        ],
      }),
    );
    expect(await editClarificationQuestion({ ...base, text: "a" })).toEqual({
      kind: "stale",
      changedBy: "[OTHER]",
    });
  });

  it.each([
    [409, { kind: "gap-not-open" }],
    [422, { kind: "invalid", detail: "The question can't be blank." }],
    [403, { kind: "forbidden" }],
    [404, { kind: "not-found" }],
    [500, { kind: "error" }],
  ])("maps %i on approve", async (code, expected) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({
      error: { code: "x", detail: "The question can't be blank." },
      response: status(code),
    });
    expect(await approveClarificationQuestion(base)).toEqual(expected);
  });

  it.each([
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i on approve all to %s", async (code, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: status(code) });
    expect(await approveAllClarificationQuestions(OPP_ID, [])).toEqual({ kind });
  });

  it("on 412 for approve all reads who changed a shown question", async () => {
    api.POST.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue(
      ok({
        items: [
          {
            id: "g",
            question: {
              ...QUESTION,
              status: "drafted",
              row_version: 4,
              last_changed_by: { id: USER_ID, name: "[OTHER]" },
            },
          },
        ],
      }),
    );
    expect(
      await approveAllClarificationQuestions(OPP_ID, [{ id: Q_ID, row_version: 3 }]),
    ).toEqual({ kind: "stale", changedBy: "[OTHER]" });
  });

  it("POSTs approve with If-Match, and approve-all with the shown questions", async () => {
    api.POST.mockResolvedValueOnce(ok(QUESTION)).mockResolvedValueOnce(ok({ count: 1 }));
    await approveClarificationQuestion({ ...base, rowVersion: 5 });
    expect(
      await approveAllClarificationQuestions(OPP_ID, [{ id: Q_ID, row_version: 3 }]),
    ).toEqual({ kind: "ok", count: 1 });
    expect(api.POST.mock.calls).toEqual([
      [
        "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}/approve",
        {
          params: {
            path: { opportunity_id: OPP_ID, question_id: Q_ID },
            header: { "If-Match": '"5"' },
          },
        },
      ],
      [
        "/api/v1/opportunities/{opportunity_id}/clarification-questions/approve-all",
        {
          params: { path: { opportunity_id: OPP_ID } },
          body: [{ id: Q_ID, row_version: 3 }],
        },
      ],
    ]);
  });
});

describe("editEstimateLine", () => {
  const LID = "00000000-0000-7000-8000-0000000000b1";
  const INPUT = {
    opportunityId: OPP_ID,
    lineId: LID,
    rowVersion: 1,
    effortHours: 32,
    reason: "[REASON]",
  };
  const ESTIMATE = { version: { sections: [] }, draft: null };

  beforeEach(() => {
    api.PATCH.mockReset();
    api.GET.mockReset();
  });

  it("patches with If-Match and only the given values, and returns the Estimate", async () => {
    api.PATCH.mockResolvedValue({
      data: ESTIMATE,
      response: new Response(null, { status: 200 }),
    });
    expect(await editEstimateLine(INPUT)).toEqual({
      kind: "ok",
      estimate: ESTIMATE,
    });
    expect(api.PATCH).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/estimate-lines/{line_id}",
      {
        params: {
          path: { opportunity_id: OPP_ID, line_id: LID },
          header: { "If-Match": '"1"' },
        },
        body: { effort_hours: 32, reason: "[REASON]" },
      },
    );
  });

  it("sends a role mix on its own", async () => {
    api.PATCH.mockResolvedValue({
      data: ESTIMATE,
      response: new Response(null, { status: 200 }),
    });
    const roleMix = { engineer: 40, project_manager: 40, qa: 20 };
    await editEstimateLine({ ...INPUT, effortHours: undefined, roleMix });
    expect(api.PATCH.mock.calls[0][1].body).toEqual({
      role_mix: roleMix,
      reason: "[REASON]",
    });
  });

  it("on 412 passes the API's sentence on, without reading anything again", async () => {
    api.PATCH.mockResolvedValueOnce({
      error: {
        code: "row_version_mismatch",
        detail: "Changed by [OTHER] since you opened it.",
      },
      response: new Response(null, { status: 412 }),
    });
    expect(await editEstimateLine(INPUT)).toEqual({
      kind: "stale",
      message: "Changed by [OTHER] since you opened it.",
    });
    api.PATCH.mockResolvedValueOnce({
      error: { code: "row_version_mismatch" },
      response: new Response(null, { status: 412 }),
    });
    expect(await editEstimateLine(INPUT)).toEqual({
      kind: "stale",
      message: "Changed by someone else since you opened it.",
    });
    expect(api.GET).not.toHaveBeenCalled();
  });

  it("on 422 passes the API's sentence on, but not a field list", async () => {
    const reject = (detail: string) =>
      api.PATCH.mockResolvedValueOnce({
        error: { code: "validation_error", detail },
        response: new Response(null, { status: 422 }),
      });
    reject("Role mix must name every role and add up to 100%.");
    expect(await editEstimateLine(INPUT)).toEqual({
      kind: "invalid",
      detail: "Role mix must name every role and add up to 100%.",
    });
    reject("Invalid fields: body.reason");
    expect(await editEstimateLine(INPUT)).toEqual({
      kind: "invalid",
      detail: "The change was not accepted.",
    });
  });

  it.each([
    [409, "not-draft"],
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.PATCH.mockResolvedValue({
      error: { code: "x" },
      response: new Response(null, { status }),
    });
    expect(await editEstimateLine(INPUT)).toEqual({ kind });
  });

  it("refuses bad input without calling the API", async () => {
    for (const bad of [
      { ...INPUT, lineId: "nope" },
      { ...INPUT, rowVersion: 1.5 },
      { ...INPUT, effortHours: undefined },
      { ...INPUT, effortHours: Number.NaN },
      { ...INPUT, reason: undefined },
      { ...INPUT, roleMix: { engineer: 100 } },
      null,
    ]) {
      expect(await editEstimateLine(bad)).toEqual({ kind: "error" });
    }
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("is an error when the call throws, logging no reason", async () => {
    const log = vi.spyOn(console, "error").mockImplementation(() => {});
    api.PATCH.mockRejectedValueOnce(new Error("network"));
    expect(await editEstimateLine(INPUT)).toEqual({ kind: "error" });
    expect(JSON.stringify(log.mock.calls)).not.toContain("[REASON]");
  });
});
