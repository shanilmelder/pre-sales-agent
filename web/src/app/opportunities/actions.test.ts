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
  closeDelivery,
  correctActual,
  saveActuals,
  acceptAllAssumptions,
  acceptAssumption,
  acceptRequirementChange,
  addSource,
  addTextSource,
  cancelReviewRequest,
  confirmChallenge,
  declineChallenge,
  decideReviewRequest,
  replyToReviewRequest,
  createEstimateVersion,
  loadChallenge,
  loadChallengeSuggestions,
  raiseChallenge,
  approveAllClarificationQuestions,
  cancelAssessmentRun,
  resolveRunDecision,
  approveClarificationQuestion,
  approveSelectedClarificationQuestions,
  changeCollaborator,
  changeGapImpact,
  confirmAnswerMatch,
  recordAnswer,
  rejectAnswerMatch,
  dismissGap,
  confirmAllRequirements,
  confirmRequirement,
  createRequirement,
  deleteRequirement,
  copyClarificationQuestions,
  countBlockingFindings,
  countOpenConflicts,
  decideFinding,
  loadEvidenceOptions,
  countOpenGaps,
  createOpportunity,
  editClarificationQuestion,
  editEstimateLine,
  editAssumption,
  convertGapToRisk,
  editRisk,
  editRequirement,
  mergeRequirements,
  splitRequirement,
  escalateConflict,
  getPassage,
  importFile,
  loadAssessments,
  loadEstimate,
  loadGaps,
  loadImport,
  loadOutdatedAssessments,
  loadRedTeam,
  loadCritic,
  loadRequirements,
  loadSources,
  markClarificationQuestionsSent,
  markClarificationQuestionUnanswered,
  rejectRequirementChange,
  reopenGap,
  resolveConflict,
  retryAssessmentTask,
  retryParse,
  requestReview,
  searchReviewerCandidates,
  searchUsers,
  startAssessmentRun,
  startEstimateDraft,
  startExtraction,
  startGapDetection,
  startRedTeamReview,
  submitEstimateVersion,
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

describe("loadCritic", () => {
  it("reads the Opportunity's Critic Review (Story 6.4)", async () => {
    const VIEW = { review: null };
    api.GET.mockReset();
    api.GET.mockResolvedValue({ data: VIEW, response: new Response(null, { status: 200 }) });
    expect(await loadCritic(OPP_ID)).toEqual({ kind: "ok", critic: VIEW });
    expect(api.GET).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/critic", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    expect(await loadCritic(7)).toEqual({ kind: "error" });
    expect(await loadCritic("../../users")).toEqual({ kind: "error" });
    expect(api.GET).toHaveBeenCalledTimes(1);
  });

  it("is an error when the API fails or throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockReset();
    api.GET.mockResolvedValue({ response: new Response(null, { status: 500 }) });
    expect(await loadCritic(OPP_ID)).toEqual({ kind: "error" });
    api.GET.mockRejectedValueOnce(new Error("network"));
    expect(await loadCritic(OPP_ID)).toEqual({ kind: "error" });
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

describe("resolveRunDecision (Story 5.5)", () => {
  const RUN_ID = "00000000-0000-7000-8000-0000000000b1";
  const DECISION_ID = "00000000-0000-7000-8000-0000000000d1";
  const INPUT = {
    opportunityId: OPP_ID,
    runId: RUN_ID,
    decisionId: DECISION_ID,
    rowVersion: 1,
    choice: "continue_without",
  };

  beforeEach(() => api.POST.mockReset());

  it("posts the choice with the decision's version as If-Match", async () => {
    const run = { id: RUN_ID, status: "queued", tasks: [] };
    api.POST.mockResolvedValue({ data: run, response: new Response(null, { status: 200 }) });
    expect(await resolveRunDecision(INPUT)).toEqual({ kind: "ok", run });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs/{run_id}/decisions/{decision_id}/resolve",
      {
        params: {
          path: { opportunity_id: OPP_ID, run_id: RUN_ID, decision_id: DECISION_ID },
          header: { "If-Match": '"1"' },
        },
        body: { choice: "continue_without" },
      },
    );
  });

  it("maps 412 to the API's who-resolved-it sentence and 409 to why", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValueOnce({
      error: { code: "row_version_mismatch", detail: "Already resolved by Sam Person." },
      response: new Response(null, { status: 412 }),
    });
    expect(await resolveRunDecision(INPUT)).toEqual({
      kind: "stale",
      message: "Already resolved by Sam Person.",
    });
    api.POST.mockResolvedValueOnce({
      error: { code: "registry_agent_disabled", detail: "Security Agent is disabled" },
      response: new Response(null, { status: 409 }),
    });
    expect(await resolveRunDecision({ ...INPUT, choice: "replan" })).toEqual({
      kind: "conflict",
      detail: "Security Agent is disabled",
    });
    api.POST.mockResolvedValueOnce({
      error: { code: "decision_not_open" },
      response: new Response(null, { status: 409 }),
    });
    expect(await resolveRunDecision(INPUT)).toEqual({
      kind: "conflict",
      detail: "This decision is no longer open.",
    });
    api.POST.mockResolvedValueOnce({ error: {}, response: new Response(null, { status: 403 }) });
    expect(await resolveRunDecision(INPUT)).toEqual({ kind: "forbidden" });
    api.POST.mockResolvedValueOnce({ error: {}, response: new Response(null, { status: 500 }) });
    expect(await resolveRunDecision(INPUT)).toEqual({ kind: "error" });
  });

  it("refuses a bad input without calling the API", async () => {
    expect(await resolveRunDecision({ ...INPUT, choice: "skip" })).toEqual({ kind: "error" });
    expect(await resolveRunDecision({ ...INPUT, decisionId: "nope" })).toEqual({ kind: "error" });
    expect(await resolveRunDecision({ ...INPUT, rowVersion: "1" })).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
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

  it("posts the Critic's retry too (Story 6.4)", async () => {
    api.POST.mockResolvedValue({ data: RUN, response: new Response(null, { status: 200 }) });
    expect(await retryAssessmentTask(OPP_ID, RUN_ID, "critic_agent")).toEqual({
      kind: "ok",
      run: RUN,
    });
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
    ).toMatchObject({ kind: "stale", changedBy: "[OTHER]", current: { id: REQ_ID, row_version: 3 } });
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

describe("acceptRequirementChange / rejectRequirementChange / loadOutdatedAssessments", () => {
  const REQ_ID = "00000000-0000-7000-8000-0000000000c1";
  const REQ = { id: REQ_ID, text: "[TEXT]", row_version: 4, last_changed_by: null };
  const TARGET = { opportunityId: OPP_ID, requirementId: REQ_ID, rowVersion: 3 };
  const PARAMS = {
    path: { opportunity_id: OPP_ID, requirement_id: REQ_ID },
    header: { "If-Match": '"3"' },
  };
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

  it("POSTs accept with If-Match", async () => {
    api.POST.mockResolvedValue(ok(REQ));
    expect(await acceptRequirementChange(TARGET)).toEqual({ kind: "ok", requirement: REQ });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/change/accept",
      { params: PARAMS },
    );
  });

  it("POSTs reject with If-Match and the reason", async () => {
    api.POST.mockResolvedValue(ok(REQ));
    expect(await rejectRequirementChange({ ...TARGET, reason: "[REASON]" })).toEqual({
      kind: "ok",
      requirement: REQ,
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/change/reject",
      { params: PARAMS, body: { reason: "[REASON]" } },
    );
  });

  it.each([
    [409, { kind: "no-change" }],
    [412, { kind: "stale", changedBy: null, current: null }],
    [422, { kind: "invalid", detail: "The reason can be at most 500 characters." }],
    [403, { kind: "forbidden" }],
  ])("maps %i on accept and on reject", async (code, expected) => {
    api.POST.mockResolvedValue({
      error: { code: "x", detail: "The reason can be at most 500 characters." },
      response: status(code),
    });
    api.GET.mockResolvedValue(ok({ items: [] })); // the 412 changer lookup
    expect(await acceptRequirementChange(TARGET)).toEqual(expected);
    expect(await rejectRequirementChange({ ...TARGET, reason: "x" })).toEqual(expected);
  });

  it("refuses bad input without calling the API", async () => {
    expect(await acceptRequirementChange({ ...TARGET, requirementId: "x" })).toEqual({
      kind: "error",
    });
    expect(await acceptRequirementChange({ ...TARGET, rowVersion: -1 })).toEqual({
      kind: "error",
    });
    expect(await rejectRequirementChange(TARGET)).toEqual({ kind: "error" }); // no reason
    expect(await rejectRequirementChange({ ...TARGET, reason: 5 })).toEqual({ kind: "error" });
    expect(await loadOutdatedAssessments("nope")).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
    expect(api.GET).not.toHaveBeenCalled();
  });

  it("GETs the outdated Assessments and returns their items", async () => {
    const items = [
      { id: "a1", agent: "engineering_agent", label: "Engineering Agent", requirement_labels: ["R1"] },
    ];
    api.GET.mockResolvedValue(ok({ items }));
    expect(await loadOutdatedAssessments(OPP_ID)).toEqual({ kind: "ok", items });
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assessments/outdated",
      { params: { path: { opportunity_id: OPP_ID } } },
    );
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

describe("changeGapImpact / dismissGap / reopenGap / approveSelected (Story 4.4)", () => {
  const G_ID = "00000000-0000-7000-8000-0000000000e1";
  const Q_ID = "00000000-0000-7000-8000-0000000000e2";
  const GAP = { id: G_ID, title: "[GAP]", row_version: 3 };
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
  const base = { opportunityId: OPP_ID, gapId: G_ID, rowVersion: 2 };
  const target = {
    params: { path: { opportunity_id: OPP_ID, gap_id: G_ID }, header: { "If-Match": '"2"' } },
  };

  it("PATCHes the impact with If-Match and the reason", async () => {
    api.PATCH.mockResolvedValue(ok(GAP));
    expect(await changeGapImpact({ ...base, impact: "low", reason: "[REASON]" })).toEqual({
      kind: "ok",
      gap: GAP,
    });
    expect(api.PATCH).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/gaps/{gap_id}/impact",
      { ...target, body: { impact: "low", reason: "[REASON]" } },
    );
  });

  it("POSTs dismiss (the note left out when empty) and reopen with If-Match", async () => {
    api.POST.mockResolvedValue(ok(GAP));
    await dismissGap({ ...base, reasonKind: "not_relevant", note: "" });
    await dismissGap({ ...base, reasonKind: "other", note: "[NOTE]" });
    await reopenGap({ ...base, reason: "[BACK]" });
    expect(api.POST.mock.calls).toEqual([
      [
        "/api/v1/opportunities/{opportunity_id}/gaps/{gap_id}/dismiss",
        { ...target, body: { reason_kind: "not_relevant" } },
      ],
      [
        "/api/v1/opportunities/{opportunity_id}/gaps/{gap_id}/dismiss",
        { ...target, body: { reason_kind: "other", note: "[NOTE]" } },
      ],
      [
        "/api/v1/opportunities/{opportunity_id}/gaps/{gap_id}/reopen",
        { ...target, body: { reason: "[BACK]" } },
      ],
    ]);
  });

  it("refuses bad input without calling the API", async () => {
    expect(await changeGapImpact({ ...base, impact: "huge", reason: "a" })).toEqual({
      kind: "error",
    });
    expect(await changeGapImpact({ ...base, gapId: "x", impact: "low", reason: "a" })).toEqual({
      kind: "error",
    });
    expect(await dismissGap({ ...base, reasonKind: "duplicate" })).toEqual({ kind: "error" });
    expect(await reopenGap({ ...base, rowVersion: -1, reason: "a" })).toEqual({ kind: "error" });
    expect(await approveSelectedClarificationQuestions(OPP_ID, [])).toEqual({ kind: "error" });
    const many = Array.from({ length: 201 }, () => ({ id: Q_ID, row_version: 1 }));
    expect(await approveSelectedClarificationQuestions(OPP_ID, many)).toEqual({ kind: "error" });
    expect(api.PATCH).not.toHaveBeenCalled();
    expect(api.POST).not.toHaveBeenCalled();
  });

  it.each([
    [409, "gap_not_reopenable", { kind: "gap-not-reopenable" }],
    [409, "gap_not_open", { kind: "gap-not-open" }],
    [409, "gap_mandatory", { kind: "gap-mandatory" }],
    [422, "validation_error", { kind: "invalid", detail: "The reason must be 1 to 500." }],
    [403, "forbidden", { kind: "forbidden" }],
    [404, "not_found", { kind: "not-found" }],
    [500, "x", { kind: "error" }],
  ])("maps %i %s", async (code, problemCode, expected) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({
      error: { code: problemCode, detail: "The reason must be 1 to 500." },
      response: status(code),
    });
    expect(await reopenGap({ ...base, reason: "a" })).toEqual(expected);
  });

  it("a 422 without a readable detail falls back to a general sentence", async () => {
    api.PATCH.mockResolvedValue({
      error: { code: "validation_error", detail: "Invalid fields: body.impact" },
      response: status(422),
    });
    expect(await changeGapImpact({ ...base, impact: "low", reason: "a" })).toEqual({
      kind: "invalid",
      detail: "The change was not accepted.",
    });
  });

  it("on 412 reads who last changed the Gap", async () => {
    api.POST.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue(
      ok({ items: [{ ...GAP, last_changed_by: { id: USER_ID, name: "[OTHER]" } }] }),
    );
    expect(await dismissGap({ ...base, reasonKind: "not_relevant" })).toEqual({
      kind: "stale",
      changedBy: "[OTHER]",
    });
  });

  it("POSTs approve-selected with the selected questions and maps its failures", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValueOnce(ok({ count: 1 }))
      .mockResolvedValueOnce({ error: { code: "forbidden" }, response: status(403) })
      .mockResolvedValueOnce({ error: { code: "not_found" }, response: status(404) });
    const selected = [{ id: Q_ID, row_version: 3 }];
    expect(await approveSelectedClarificationQuestions(OPP_ID, selected)).toEqual({
      kind: "ok",
      count: 1,
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/approve-selected",
      { params: { path: { opportunity_id: OPP_ID } }, body: selected },
    );
    expect(await approveSelectedClarificationQuestions(OPP_ID, selected)).toEqual({
      kind: "forbidden",
    });
    expect(await approveSelectedClarificationQuestions(OPP_ID, selected)).toEqual({
      kind: "not-found",
    });
  });

  it("on 412 for approve-selected reads who changed a selected question", async () => {
    api.POST.mockResolvedValue({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue(
      ok({
        items: [
          {
            id: G_ID,
            question: {
              id: Q_ID,
              status: "drafted",
              row_version: 4,
              last_changed_by: { id: USER_ID, name: "[OTHER]" },
            },
          },
        ],
      }),
    );
    expect(
      await approveSelectedClarificationQuestions(OPP_ID, [{ id: Q_ID, row_version: 3 }]),
    ).toEqual({ kind: "stale", changedBy: "[OTHER]" });
  });
});

describe("copy / mark sent / No answer (Story 4.6)", () => {
  const Q_ID = "00000000-0000-7000-8000-0000000000d1";
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });

  it("copies: POSTs the export as copy and returns the text and count", async () => {
    api.POST.mockResolvedValue(
      ok({ format: "copy", question_count: 2, text: "[TEXT]", url: null, file_name: null }),
    );
    expect(await copyClarificationQuestions(OPP_ID)).toEqual({
      kind: "ok",
      text: "[TEXT]",
      count: 2,
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/export",
      { params: { path: { opportunity_id: OPP_ID } }, body: { format: "copy" } },
    );
  });

  it.each([
    [409, { kind: "nothing-approved" }],
    [403, { kind: "forbidden" }],
    [404, { kind: "not-found" }],
    [500, { kind: "error" }],
  ])("copy maps %i", async (code, expected) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error: { code: "x" }, response: status(code) });
    expect(await copyClarificationQuestions(OPP_ID)).toEqual(expected);
  });

  it("marks sent: POSTs the date and the shown questions", async () => {
    api.POST.mockResolvedValue(ok({ count: 1 }));
    const questions = [{ id: Q_ID, row_version: 3 }];
    expect(await markClarificationQuestionsSent(OPP_ID, "2026-10-14", questions)).toEqual({
      kind: "ok",
      count: 1,
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/mark-sent",
      {
        params: { path: { opportunity_id: OPP_ID } },
        body: { sent_on: "2026-10-14", questions },
      },
    );
  });

  it("refuses bad mark-sent input without calling the API", async () => {
    const one = [{ id: Q_ID, row_version: 3 }];
    expect(await markClarificationQuestionsSent("x", "2026-10-14", one)).toEqual({ kind: "error" });
    expect(await markClarificationQuestionsSent(OPP_ID, "14/10/2026", one)).toEqual({
      kind: "error",
    });
    expect(await markClarificationQuestionsSent(OPP_ID, "2026-10-14", [])).toEqual({
      kind: "error",
    });
    const many = Array.from({ length: 201 }, () => ({ id: Q_ID, row_version: 1 }));
    expect(await markClarificationQuestionsSent(OPP_ID, "2026-10-14", many)).toEqual({
      kind: "error",
    });
    expect(await markClarificationQuestionUnanswered({ opportunityId: OPP_ID })).toEqual({
      kind: "error",
    });
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("maps mark-sent failures; a 412 reads who changed a listed question", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const one = [{ id: Q_ID, row_version: 3 }];
    api.POST.mockResolvedValueOnce({
      error: { code: "validation_error", detail: "The date sent can't be in the future." },
      response: status(422),
    })
      .mockResolvedValueOnce({ error: { code: "forbidden" }, response: status(403) })
      .mockResolvedValueOnce({ error: { code: "row_version_mismatch" }, response: status(412) });
    api.GET.mockResolvedValue(
      ok({
        items: [
          {
            id: "g",
            question: {
              id: Q_ID,
              status: "sent",
              row_version: 4,
              last_changed_by: { id: USER_ID, name: "[OTHER]" },
            },
          },
        ],
      }),
    );
    expect(await markClarificationQuestionsSent(OPP_ID, "2026-10-14", one)).toEqual({
      kind: "invalid",
      detail: "The date sent can't be in the future.",
    });
    expect(await markClarificationQuestionsSent(OPP_ID, "2026-10-14", one)).toEqual({
      kind: "forbidden",
    });
    expect(await markClarificationQuestionsSent(OPP_ID, "2026-10-14", one)).toEqual({
      kind: "stale",
      changedBy: "[OTHER]",
    });
  });

  it("No answer POSTs with If-Match and maps question_not_sent", async () => {
    const base = { opportunityId: OPP_ID, questionId: Q_ID, rowVersion: 3 };
    api.POST.mockResolvedValueOnce(ok({ id: Q_ID, status: "unanswered" })).mockResolvedValueOnce({
      error: { code: "question_not_sent" },
      response: status(409),
    });
    expect(await markClarificationQuestionUnanswered(base)).toEqual({
      kind: "ok",
      question: { id: Q_ID, status: "unanswered" },
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}/no-answer",
      {
        params: {
          path: { opportunity_id: OPP_ID, question_id: Q_ID },
          header: { "If-Match": '"3"' },
        },
      },
    );
    expect(await markClarificationQuestionUnanswered(base)).toEqual({ kind: "question-not-sent" });
  });

  it("an edit of a sent question maps question_not_editable", async () => {
    api.PATCH.mockResolvedValue({
      error: { code: "question_not_editable" },
      response: status(409),
    });
    expect(
      await editClarificationQuestion({
        opportunityId: OPP_ID,
        questionId: Q_ID,
        rowVersion: 3,
        text: "a",
      }),
    ).toEqual({ kind: "question-not-editable" });
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

describe("resolveConflict and escalateConflict", () => {
  const CID = "00000000-0000-7000-8000-0000000000c1";
  const REVIEWER = "00000000-0000-7000-8000-0000000000e1";
  const RESOLVE = {
    opportunityId: OPP_ID,
    conflictId: CID,
    rowVersion: 1,
    choice: { position: 1 },
    reason: "[REASON]",
  };
  const ESCALATE = {
    opportunityId: OPP_ID,
    conflictId: CID,
    rowVersion: 2,
    reviewerId: REVIEWER,
    reason: "[REASON]",
  };
  const CONFLICT = { id: CID, status: "resolved", row_version: 2 };
  const PATH = "/api/v1/opportunities/{opportunity_id}/conflicts/{conflict_id}";

  beforeEach(() => {
    api.POST.mockReset();
  });

  function answer(status: number, error?: Record<string, string>) {
    api.POST.mockResolvedValueOnce({
      error,
      response: new Response(null, { status }),
    });
  }

  it("posts a chosen position with If-Match and returns the Conflict", async () => {
    api.POST.mockResolvedValue({
      data: CONFLICT,
      response: new Response(null, { status: 200 }),
    });
    expect(await resolveConflict(RESOLVE)).toEqual({
      kind: "ok",
      conflict: CONFLICT,
    });
    expect(api.POST).toHaveBeenCalledWith(`${PATH}/resolution`, {
      params: {
        path: { opportunity_id: OPP_ID, conflict_id: CID },
        header: { "If-Match": '"1"' },
      },
      body: { choice: 1, reason: "[REASON]" },
    });
  });

  it("posts an entered position as {entered}", async () => {
    api.POST.mockResolvedValue({
      data: CONFLICT,
      response: new Response(null, { status: 200 }),
    });
    await resolveConflict({ ...RESOLVE, choice: { entered: "48" } });
    expect(api.POST.mock.calls[0][1].body).toEqual({
      choice: { entered: "48" },
      reason: "[REASON]",
    });
  });

  it("posts an escalation with If-Match", async () => {
    api.POST.mockResolvedValue({
      data: CONFLICT,
      response: new Response(null, { status: 200 }),
    });
    expect(await escalateConflict(ESCALATE)).toEqual({
      kind: "ok",
      conflict: CONFLICT,
    });
    expect(api.POST).toHaveBeenCalledWith(`${PATH}/escalation`, {
      params: {
        path: { opportunity_id: OPP_ID, conflict_id: CID },
        header: { "If-Match": '"2"' },
      },
      body: { reviewer_id: REVIEWER, reason: "[REASON]" },
    });
  });

  it.each([
    ["resolve", () => resolveConflict(RESOLVE)],
    ["escalate", () => escalateConflict(ESCALATE)],
  ])("%s: 412 passes the API's sentence on", async (_, call) => {
    answer(412, {
      code: "row_version_mismatch",
      detail: "Changed by [OTHER] since you opened it.",
    });
    expect(await call()).toEqual({
      kind: "stale",
      message: "Changed by [OTHER] since you opened it.",
    });
    answer(412, { code: "row_version_mismatch" });
    expect(await call()).toEqual({
      kind: "stale",
      message: "Changed by someone else since you opened it.",
    });
  });

  it("tells already escalated from already resolved on 409", async () => {
    answer(409, { code: "conflict_not_open" });
    expect(await escalateConflict(ESCALATE)).toEqual({
      kind: "conflict",
      detail: "This Conflict is already escalated.",
    });
    answer(409, { code: "conflict_already_resolved" });
    expect(await resolveConflict(RESOLVE)).toEqual({
      kind: "conflict",
      detail: "This Conflict is already resolved.",
    });
  });

  it("on 422 passes the API's sentence on, but not a field list", async () => {
    answer(422, {
      code: "validation_error",
      detail: "Give a reason of 1 to 1,000 characters.",
    });
    expect(await resolveConflict(RESOLVE)).toEqual({
      kind: "invalid",
      detail: "Give a reason of 1 to 1,000 characters.",
    });
    answer(422, {
      code: "validation_error",
      detail: "Invalid fields: body.reason",
    });
    expect(await escalateConflict(ESCALATE)).toEqual({
      kind: "invalid",
      detail: "The decision was not accepted.",
    });
  });

  it.each([
    [403, "forbidden"],
    [404, "not-found"],
    [500, "error"],
  ])("maps %i to %s", async (status, kind) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    answer(status, { code: "x" });
    expect(await resolveConflict(RESOLVE)).toEqual({ kind });
    answer(status, { code: "x" });
    expect(await escalateConflict(ESCALATE)).toEqual({ kind });
  });

  it("refuses bad input without calling the API", async () => {
    for (const bad of [
      { ...RESOLVE, conflictId: "nope" },
      { ...RESOLVE, choice: { position: 0 } },
      { ...RESOLVE, choice: 1 },
      { ...RESOLVE, reason: undefined },
      null,
    ]) {
      expect(await resolveConflict(bad)).toEqual({ kind: "error" });
    }
    expect(await escalateConflict({ ...ESCALATE, reviewerId: "nope" })).toEqual(
      {
        kind: "error",
      },
    );
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("recordAnswer / confirmAnswerMatch / rejectAnswerMatch (Story 4.7)", () => {
  const Q_ID = "00000000-0000-7000-8000-0000000000f1";
  const M_ID = "00000000-0000-7000-8000-0000000000f2";
  const GAP = { id: "00000000-0000-7000-8000-0000000000f3", title: "[GAP]", row_version: 4 };
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
  const answer = {
    opportunityId: OPP_ID,
    questionId: Q_ID,
    rowVersion: 3,
    text: "[ANSWER]",
    answeredOn: "2026-10-12",
    settlesGap: true,
  };

  it("POSTs the answer with If-Match", async () => {
    api.POST.mockResolvedValue(ok(GAP));
    expect(await recordAnswer(answer)).toEqual({ kind: "ok", gap: GAP });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}/answer",
      {
        params: {
          path: { opportunity_id: OPP_ID, question_id: Q_ID },
          header: { "If-Match": '"3"' },
        },
        body: { text: "[ANSWER]", answered_on: "2026-10-12", settles_gap: true },
      },
    );
  });

  it("POSTs confirm and reject with the suggestion's If-Match", async () => {
    api.POST.mockResolvedValue(ok(GAP));
    const target = { opportunityId: OPP_ID, matchId: M_ID, rowVersion: 1 };
    expect(await confirmAnswerMatch(target)).toEqual({ kind: "ok", gap: GAP });
    expect(await rejectAnswerMatch(target)).toEqual({ kind: "ok", gap: GAP });
    const params = {
      params: { path: { opportunity_id: OPP_ID, match_id: M_ID }, header: { "If-Match": '"1"' } },
    };
    expect(api.POST.mock.calls).toEqual([
      ["/api/v1/opportunities/{opportunity_id}/answer-matches/{match_id}/confirm", params],
      ["/api/v1/opportunities/{opportunity_id}/answer-matches/{match_id}/reject", params],
    ]);
  });

  it("refuses bad input without calling the API", async () => {
    expect(await recordAnswer({ ...answer, answeredOn: "12 Oct" })).toEqual({ kind: "error" });
    expect(await recordAnswer({ ...answer, settlesGap: "yes" })).toEqual({ kind: "error" });
    expect(await confirmAnswerMatch({ opportunityId: OPP_ID, matchId: "x", rowVersion: 1 })).toEqual(
      { kind: "error" },
    );
    expect(api.POST).not.toHaveBeenCalled();
  });

  it.each([
    [409, "question_not_sent", { kind: "question-not-sent" }],
    [409, "gap_not_open", { kind: "gap-not-open" }],
    [412, "row_version_mismatch", { kind: "stale" }],
    [422, "validation_error", { kind: "invalid", detail: "The date answered can't be in the future." }],
    [403, "forbidden", { kind: "forbidden" }],
    [404, "not_found", { kind: "not-found" }],
    [500, "x", { kind: "error" }],
  ])("maps %i %s", async (code, problemCode, expected) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({
      error: { code: problemCode, detail: "The date answered can't be in the future." },
      response: status(code),
    });
    expect(await recordAnswer(answer)).toEqual(expected);
  });
});

describe("countOpenGaps (Story 4.7)", () => {
  it("counts only the open Gaps, and is null on a failed read", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockResolvedValueOnce({
      data: { items: [{ status: "open" }, { status: "answered" }, { status: "open" }] },
      response: new Response(null, { status: 200 }),
    });
    expect(await countOpenGaps(OPP_ID)).toBe(2);
    api.GET.mockResolvedValueOnce({ response: new Response(null, { status: 500 }) });
    expect(await countOpenGaps(OPP_ID)).toBeNull();
    expect(await countOpenGaps("nope")).toBeNull();
  });
});

describe("countOpenConflicts (Story 6.2)", () => {
  it("is the open-plus-escalated count, null on a failed read or a bad id", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockResolvedValueOnce({
      data: {
        conflicts: [{ status: "open" }, { status: "resolved" }, { status: "escalated" }],
        open_count: 2,
        reviewers: [],
      },
      response: new Response(null, { status: 200 }),
    });
    expect(await countOpenConflicts(OPP_ID)).toBe(2);
    expect(api.GET).toHaveBeenLastCalledWith("/api/v1/opportunities/{opportunity_id}/conflicts", {
      params: { path: { opportunity_id: OPP_ID } },
    });
    api.GET.mockResolvedValueOnce({ response: new Response(null, { status: 500 }) });
    expect(await countOpenConflicts(OPP_ID)).toBeNull();
    api.GET.mockClear();
    expect(await countOpenConflicts("nope")).toBeNull();
    expect(api.GET).not.toHaveBeenCalled();
  });
});

describe("createRequirement / deleteRequirement / splitRequirement / mergeRequirements", () => {
  const REQ_ID = "00000000-0000-7000-8000-0000000000c1";
  const OTHER_ID = "00000000-0000-7000-8000-0000000000c2";
  const REQ = { id: REQ_ID, number: 6, text: "[TEXT]", row_version: 1, last_changed_by: null };
  const ok = (data: unknown) => ({ data, response: new Response(null, { status: 200 }) });
  const failing = (code: number) => ({
    error: { code: "x", detail: "[SENTENCE]" },
    response: status(code),
  });
  const TARGET = { opportunityId: OPP_ID, requirementId: REQ_ID, rowVersion: 4 };
  const PARTS = [
    { text: "[A]", classification: "functional" },
    { text: "[B]", classification: "security" },
  ];
  const MERGE = {
    opportunityId: OPP_ID,
    requirements: [
      { id: REQ_ID, rowVersion: 2 },
      { id: OTHER_ID, rowVersion: 5 },
    ],
    text: "[MERGED]",
    classification: "data",
  };

  it("createRequirement POSTs the text and classification", async () => {
    api.POST.mockResolvedValue(ok(REQ));
    expect(
      await createRequirement({ opportunityId: OPP_ID, text: "[TEXT]", classification: "data" }),
    ).toEqual({ kind: "ok", requirement: REQ });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/requirements", {
      params: { path: { opportunity_id: OPP_ID } },
      body: { text: "[TEXT]", classification: "data" },
    });
  });

  it("deleteRequirement POSTs the reason with If-Match", async () => {
    api.POST.mockResolvedValue(ok({ id: REQ_ID, status: "deleted", version: 1 }));
    expect(await deleteRequirement({ ...TARGET, reason: "[WHY]" })).toEqual({ kind: "ok" });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/delete",
      {
        params: {
          path: { opportunity_id: OPP_ID, requirement_id: REQ_ID },
          header: { "If-Match": '"4"' },
        },
        body: { reason: "[WHY]" },
      },
    );
  });

  it("splitRequirement POSTs the two parts with If-Match", async () => {
    api.POST.mockResolvedValue(ok({ items: [REQ, { ...REQ, id: OTHER_ID }] }));
    expect(await splitRequirement({ ...TARGET, parts: PARTS })).toEqual({
      kind: "ok",
      requirements: [REQ, { ...REQ, id: OTHER_ID }],
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/split",
      {
        params: {
          path: { opportunity_id: OPP_ID, requirement_id: REQ_ID },
          header: { "If-Match": '"4"' },
        },
        body: { parts: PARTS },
      },
    );
  });

  it("mergeRequirements POSTs each row_version in the body, with no If-Match", async () => {
    api.POST.mockResolvedValue(ok(REQ));
    expect(await mergeRequirements(MERGE)).toEqual({ kind: "ok", requirement: REQ });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/requirements/merge",
      {
        params: { path: { opportunity_id: OPP_ID } },
        body: {
          requirements: [
            { id: REQ_ID, row_version: 2 },
            { id: OTHER_ID, row_version: 5 },
          ],
          text: "[MERGED]",
          classification: "data",
        },
      },
    );
  });

  it.each([
    [422, { kind: "invalid", detail: "[SENTENCE]" }],
    [403, { kind: "forbidden" }],
    [404, { kind: "not-found" }],
    [500, { kind: "error" }],
  ])("maps %i on every shaping write", async (code, expected) => {
    api.POST.mockResolvedValue(failing(code));
    vi.spyOn(console, "error").mockImplementation(() => {});
    expect(
      await createRequirement({ opportunityId: OPP_ID, text: "x", classification: "data" }),
    ).toEqual(expected);
    expect(await deleteRequirement({ ...TARGET, reason: "x" })).toEqual(expected);
    expect(await splitRequirement({ ...TARGET, parts: PARTS })).toEqual(expected);
    expect(await mergeRequirements(MERGE)).toEqual(expected);
  });

  it("maps 412: delete and split read the saved Requirement; create and merge name no one", async () => {
    api.POST.mockResolvedValue(failing(412));
    const saved = { ...REQ, last_changed_by: { id: USER_ID, name: "[OTHER]" } };
    api.GET.mockResolvedValue(ok({ items: [saved] }));
    const named = { kind: "stale", changedBy: "[OTHER]", current: saved };
    expect(await deleteRequirement({ ...TARGET, reason: "x" })).toEqual(named);
    expect(await splitRequirement({ ...TARGET, parts: PARTS })).toEqual(named);
    const unnamed = { kind: "stale", changedBy: null, current: null };
    expect(await mergeRequirements(MERGE)).toEqual(unnamed);
    expect(
      await createRequirement({ opportunityId: OPP_ID, text: "x", classification: "data" }),
    ).toEqual(unnamed);
  });

  it("refuses bad input without calling the API", async () => {
    expect(
      await createRequirement({ opportunityId: "x", text: "a", classification: "data" }),
    ).toEqual({ kind: "error" });
    expect(
      await createRequirement({ opportunityId: OPP_ID, text: "a", classification: "nice" }),
    ).toEqual({ kind: "error" });
    expect(await deleteRequirement(TARGET)).toEqual({ kind: "error" }); // no reason
    expect(await splitRequirement({ ...TARGET, parts: PARTS.slice(0, 1) })).toEqual({
      kind: "error",
    });
    expect(
      await mergeRequirements({
        ...MERGE,
        requirements: [
          { id: REQ_ID, rowVersion: 0 },
          { id: OTHER_ID, rowVersion: 1 },
        ],
      }),
    ).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("editAssumption, convertGapToRisk and editRisk (Story 8.5)", () => {
  const AID = "00000000-0000-7000-8000-0000000000a1";
  const RID = "00000000-0000-7000-8000-0000000000b1";
  const GID = "00000000-0000-7000-8000-0000000000e1";
  const LID = "00000000-0000-7000-8000-0000000000d1";
  const ESTIMATE = { version: { sections: [] }, draft: null };
  const EDIT = {
    opportunityId: OPP_ID,
    assumptionId: AID,
    rowVersion: 2,
    kind: "contingency",
    wording: "[WORDING]",
    amountHours: 12,
    lineId: LID,
    reason: "[REASON]",
  };

  beforeEach(() => {
    api.PATCH.mockReset();
    api.POST.mockReset();
  });

  it("patches an Assumption with If-Match and every field, and returns the Estimate", async () => {
    api.PATCH.mockResolvedValue({ data: ESTIMATE, response: new Response(null, { status: 200 }) });
    expect(await editAssumption(EDIT)).toEqual({ kind: "ok", estimate: ESTIMATE });
    expect(api.PATCH).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/assumptions/{assumption_id}",
      {
        params: {
          path: { opportunity_id: OPP_ID, assumption_id: AID },
          header: { "If-Match": '"2"' },
        },
        body: {
          kind: "contingency",
          wording: "[WORDING]",
          amount_hours: 12,
          line_id: LID,
          reason: "[REASON]",
        },
      },
    );
  });

  it.each([
    [412, "row_version_mismatch", "Changed by [OTHER] since you opened it.", {
      kind: "stale",
      message: "Changed by [OTHER] since you opened it.",
    }],
    [422, "validation_error", "A Condition has no hours.", {
      kind: "invalid",
      detail: "A Condition has no hours.",
    }],
    [409, "estimate_version_not_draft", "", { kind: "not-draft" }],
    [403, "forbidden", "", { kind: "forbidden" }],
    [404, "not_found", "", { kind: "not-found" }],
  ])("maps a %i on an Assumption edit", async (status, code, detail, expected) => {
    api.PATCH.mockResolvedValue({
      error: { code, detail },
      response: new Response(null, { status }),
    });
    expect(await editAssumption(EDIT)).toEqual(expected);
  });

  it("refuses bad input without calling the API", async () => {
    expect(await editAssumption({ ...EDIT, kind: "risk" })).toEqual({ kind: "error" });
    expect(await editAssumption({ ...EDIT, lineId: "x" })).toEqual({ kind: "error" });
    expect(api.PATCH).not.toHaveBeenCalled();
  });

  it("converts a Gap to a Risk and tells the two 409s apart", async () => {
    const input = {
      opportunityId: OPP_ID,
      gapId: GID,
      description: "[RISK]",
      likelihood: "medium",
      impact: "high",
    };
    api.POST.mockResolvedValueOnce({
      data: { id: RID },
      response: new Response(null, { status: 201 }),
    });
    expect(await convertGapToRisk(input)).toEqual({ kind: "ok", risk: { id: RID } });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/risks", {
      params: { path: { opportunity_id: OPP_ID } },
      body: { gap_id: GID, description: "[RISK]", likelihood: "medium", impact: "high" },
    });
    api.POST.mockResolvedValueOnce({
      error: { code: "no_draft_estimate" },
      response: new Response(null, { status: 409 }),
    });
    expect(await convertGapToRisk(input)).toEqual({ kind: "no-draft" });
    api.POST.mockResolvedValueOnce({
      error: { code: "gap_not_open" },
      response: new Response(null, { status: 409 }),
    });
    expect(await convertGapToRisk(input)).toEqual({ kind: "gap-not-open" });
    expect(await convertGapToRisk({ ...input, impact: "severe" })).toEqual({ kind: "error" });
  });

  it("patches a Risk with If-Match", async () => {
    api.PATCH.mockResolvedValue({ data: ESTIMATE, response: new Response(null, { status: 200 }) });
    const input = {
      opportunityId: OPP_ID,
      riskId: RID,
      rowVersion: 1,
      description: "[RISK]",
      likelihood: "low",
      impact: "high",
      reason: "[REASON]",
    };
    expect(await editRisk(input)).toEqual({ kind: "ok", estimate: ESTIMATE });
    expect(api.PATCH).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/risks/{risk_id}", {
      params: { path: { opportunity_id: OPP_ID, risk_id: RID }, header: { "If-Match": '"1"' } },
      body: { description: "[RISK]", likelihood: "low", impact: "high", reason: "[REASON]" },
    });
  });
});

describe("decideFinding, loadEvidenceOptions and countBlockingFindings (Story 6.6)", () => {
  const FID = "00000000-0000-7000-8000-0000000000f1";
  const PATH = "/api/v1/opportunities/{opportunity_id}/findings/{finding_id}";
  const BASE = { opportunityId: OPP_ID, findingId: FID, rowVersion: 3, reason: "[REASON]" };
  const STATE = { id: FID, status: "overridden", row_version: 4 };
  const params = {
    path: { opportunity_id: OPP_ID, finding_id: FID },
    header: { "If-Match": '"3"' },
  };

  beforeEach(() => {
    api.POST.mockReset();
    api.GET.mockReset();
  });

  function answer(status: number, error?: Record<string, string>) {
    api.POST.mockResolvedValueOnce({ error, response: new Response(null, { status }) });
  }

  it("posts each action to its route with If-Match and returns the Finding's state", async () => {
    api.POST.mockResolvedValue({ data: STATE, response: new Response(null, { status: 200 }) });
    expect(await decideFinding({ ...BASE, action: "override" })).toEqual({
      kind: "ok",
      finding: STATE,
    });
    expect(api.POST).toHaveBeenLastCalledWith(`${PATH}/override`, {
      params,
      body: { reason: "[REASON]" },
    });
    await decideFinding({ ...BASE, action: "resolve" });
    expect(api.POST).toHaveBeenLastCalledWith(`${PATH}/resolution`, {
      params,
      body: { reason: "[REASON]" },
    });
    const refs = [{ kind: "requirement", id: OPP_ID, version: 2 }];
    await decideFinding({ ...BASE, action: "evidence", refs });
    expect(api.POST).toHaveBeenLastCalledWith(`${PATH}/evidence`, {
      params,
      body: { refs, note: "[REASON]" },
    });
  });

  it("maps 412, 422, 409, 403 and 404 and rejects bad input without a call", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    answer(412, { code: "row_version_mismatch", detail: "Changed by Sam since you opened it." });
    expect(await decideFinding({ ...BASE, action: "override" })).toEqual({
      kind: "stale",
      message: "Changed by Sam since you opened it.",
    });
    answer(422, { code: "finding_not_overridable", detail: "[NOT OVERRIDABLE]" });
    expect(await decideFinding({ ...BASE, action: "override" })).toEqual({
      kind: "invalid",
      detail: "[NOT OVERRIDABLE]",
    });
    answer(422, { code: "evidence_unresolvable", detail: "Evidence requirement:x" });
    expect((await decideFinding({ ...BASE, action: "resolve" })).kind).toBe("invalid");
    answer(409, { code: "finding_not_open", detail: "This Finding is already resolved." });
    expect(await decideFinding({ ...BASE, action: "resolve" })).toEqual({
      kind: "conflict",
      detail: "This Finding is already resolved.",
    });
    answer(403);
    expect(await decideFinding({ ...BASE, action: "resolve" })).toEqual({ kind: "forbidden" });
    answer(404);
    expect(await decideFinding({ ...BASE, action: "resolve" })).toEqual({ kind: "not-found" });
    api.POST.mockClear();
    expect(await decideFinding({ ...BASE, action: "delete" })).toEqual({ kind: "error" });
    expect(await decideFinding({ ...BASE, findingId: "nope", action: "resolve" })).toEqual({
      kind: "error",
    });
    const estimate = { kind: "estimate_line", id: BASE.findingId, version: 1 };
    expect(
      await decideFinding({ ...BASE, action: "evidence", refs: [estimate] } as never),
    ).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("reads the Evidence picker", async () => {
    const items = [{ kind: "requirement", id: FID, version: 1, label: "R1", excerpt: "" }];
    api.GET.mockResolvedValueOnce({ data: { items }, response: new Response(null) });
    expect(await loadEvidenceOptions(OPP_ID)).toEqual({ kind: "ok", items });
    expect(api.GET).toHaveBeenLastCalledWith(
      "/api/v1/opportunities/{opportunity_id}/evidence-options",
      { params: { path: { opportunity_id: OPP_ID } } },
    );
    expect(await loadEvidenceOptions("nope")).toEqual({ kind: "error" });
  });

  it("sums the Red Team's and the Critic's blocking counts for the badge", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.GET.mockImplementation(async (path: string) => ({
      data: path.endsWith("/red-team")
        ? { review: null, run: null, can_start: false, blocking_count: 2 }
        : { review: null, blocking_count: 1 },
      response: new Response(null),
    }));
    expect(await countBlockingFindings(OPP_ID)).toBe(3);
    // A failed Critic read must not undercount: no number at all.
    api.GET.mockImplementation(async (path: string) =>
      path.endsWith("/red-team")
        ? {
            data: { review: null, run: null, can_start: false, blocking_count: 2 },
            response: new Response(null),
          }
        : { response: new Response(null, { status: 500 }) },
    );
    expect(await countBlockingFindings(OPP_ID)).toBeNull();
    api.GET.mockImplementation(async () => ({ response: new Response(null, { status: 500 }) }));
    expect(await countBlockingFindings(OPP_ID)).toBeNull();
    expect(await countBlockingFindings("nope")).toBeNull();
  });
});

describe("submitEstimateVersion (Story 8.6)", () => {
  const VID = "00000000-0000-7000-8000-0000000000e3";
  const INPUT = { opportunityId: OPP_ID, versionId: VID, rowVersion: 2 };
  const BLOCKERS = {
    to_submit: [{ kind: "gap", subject_id: "g1", title: "[GAP]", detail: "", href: "#gap-g1" }],
    to_baseline: [],
  };

  it("posts with If-Match and returns the submitted version", async () => {
    const SUBMITTED = { id: VID, version: 3, status: "submitted", row_version: 3 };
    api.POST.mockResolvedValue({ data: SUBMITTED, response: status(200) });
    expect(await submitEstimateVersion(INPUT)).toEqual({ kind: "ok", version: SUBMITTED });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/estimate/versions/{version_id}/submit",
      {
        params: {
          path: { opportunity_id: OPP_ID, version_id: VID },
          header: { "If-Match": '"2"' },
        },
      },
    );
  });

  it.each([
    [
      409,
      { code: "estimate_version_blocked", detail: "Resolve 1 blocker.", blockers: BLOCKERS },
      { kind: "blocked", blockers: BLOCKERS, detail: "Resolve 1 blocker." },
    ],
    [
      409,
      { code: "estimate_version_blocked" },
      { kind: "blocked", blockers: null, detail: null },
    ],
    [409, { code: "estimate_version_not_draft" }, { kind: "not-draft" }],
    [412, { code: "row_version_mismatch" }, { kind: "stale" }],
    [403, { code: "forbidden" }, { kind: "forbidden" }],
    [404, { code: "not_found" }, { kind: "not-found" }],
  ])("maps %i %o", async (code, error, expected) => {
    api.POST.mockResolvedValue({ error, response: status(code) });
    expect(await submitEstimateVersion(INPUT)).toEqual(expected);
  });

  it("refuses bad input without calling the API", async () => {
    expect(await submitEstimateVersion({ ...INPUT, rowVersion: "2" })).toEqual({ kind: "error" });
    expect(await submitEstimateVersion({ ...INPUT, versionId: "x" })).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("Review Requests (Story 9.1)", () => {
  const VID = "00000000-0000-7000-8000-0000000000e3";
  const RID = "00000000-0000-7000-8000-0000000000d1";
  const ANA = "00000000-0000-7000-8000-0000000000a1";
  const A1 = "00000000-0000-7000-8000-0000000000b1";
  const INPUT = {
    opportunityId: OPP_ID,
    versionId: VID,
    rowVersion: 4,
    reviewType: "engineering",
    reviewerIds: [ANA],
    assessmentRefs: [{ id: A1, version: 2 }],
    message: "  ",
  };

  it("requestReview posts with If-Match and a null message for a blank one", async () => {
    const CREATED = { items: [], version_status: "in_review", version_row_version: 5 };
    api.POST.mockResolvedValue({ data: CREATED, response: status(201) });
    expect(await requestReview(INPUT)).toEqual({ kind: "ok", value: CREATED });
    const PATH = "/api/v1/opportunities/{opportunity_id}/review-requests";
    expect(api.POST).toHaveBeenCalledWith(PATH, {
      params: { path: { opportunity_id: OPP_ID }, header: { "If-Match": '"4"' } },
      body: {
        version_id: VID,
        review_type: "engineering",
        reviewer_ids: [ANA],
        assessment_refs: [{ id: A1, version: 2 }],
        message: null,
      },
    });
    await requestReview({ ...INPUT, message: "  Check L3  " });
    expect(api.POST.mock.calls[1]![1].body.message).toBe("Check L3");
  });

  it.each([
    [409, { code: "review_request_duplicate", detail: "Ana already has one." }, "invalid"],
    [422, { code: "author_cannot_review", detail: "The author of v3 can't review it" }, "invalid"],
    [412, { code: "row_version_mismatch" }, "stale"],
    [403, { code: "forbidden" }, "forbidden"],
    [404, { code: "not_found" }, "not-found"],
    [500, { code: "internal_error" }, "error"],
  ])("requestReview maps %i", async (code, error, kind) => {
    api.POST.mockResolvedValue({ error, response: status(code) });
    const expected =
      kind === "invalid" ? { kind, detail: (error as { detail: string }).detail } : { kind };
    expect(await requestReview(INPUT)).toEqual(expected);
  });

  it("requestReview refuses bad input without calling the API", async () => {
    expect(await requestReview({ ...INPUT, reviewerIds: [] })).toEqual({ kind: "error" });
    expect(await requestReview({ ...INPUT, reviewType: "legal" })).toEqual({ kind: "error" });
    expect(await requestReview({ ...INPUT, rowVersion: "4" })).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });

  it("cancelReviewRequest posts the trimmed reason with If-Match", async () => {
    const CANCELLED = { id: RID, status: "cancelled", row_version: 2 };
    api.POST.mockResolvedValue({ data: CANCELLED, response: status(200) });
    const input = { opportunityId: OPP_ID, requestId: RID, rowVersion: 1, reason: "  Wrong one  " };
    expect(await cancelReviewRequest(input)).toEqual({ kind: "ok", value: CANCELLED });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/review-requests/{request_id}/cancel",
      {
        params: {
          path: { opportunity_id: OPP_ID, request_id: RID },
          header: { "If-Match": '"1"' },
        },
        body: { reason: "Wrong one" },
      },
    );
  });

  it.each([
    [409, { code: "review_request_not_pending", detail: "Only a pending one." }, "invalid"],
    [422, { code: "validation_error", detail: "Give a reason." }, "invalid"],
    [412, { code: "row_version_mismatch" }, "stale"],
    [403, { code: "forbidden" }, "forbidden"],
    [404, { code: "not_found" }, "not-found"],
  ])("cancelReviewRequest maps %i", async (code, error, kind) => {
    api.POST.mockResolvedValue({ error, response: status(code) });
    const input = { opportunityId: OPP_ID, requestId: RID, rowVersion: 1, reason: "Why" };
    const expected =
      kind === "invalid" ? { kind, detail: (error as { detail: string }).detail } : { kind };
    expect(await cancelReviewRequest(input)).toEqual(expected);
  });

  it("searchReviewerCandidates sends the type and the trimmed query", async () => {
    const USERS = [{ id: ANA, name: "Ana", email: "ana@ex.test" }];
    api.GET.mockResolvedValue({ data: { items: USERS }, response: status(200) });
    expect(
      await searchReviewerCandidates({ opportunityId: OPP_ID, reviewType: "pm", q: "  an " }),
    ).toEqual({ kind: "ok", users: USERS });
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/review-requests/reviewer-candidates",
      {
        params: {
          path: { opportunity_id: OPP_ID },
          query: { review_type: "pm", q: "an" },
        },
      },
    );
    expect(
      await searchReviewerCandidates({ opportunityId: OPP_ID, reviewType: "legal", q: "" }),
    ).toEqual({ kind: "error" });
  });
});

describe("decideReviewRequest (Story 9.3)", () => {
  const RID = "00000000-0000-7000-8000-0000000000d1";
  const CY = "00000000-0000-7000-8000-0000000000a3";
  const PATH = "/api/v1/opportunities/{opportunity_id}/review-requests/{request_id}/decisions";
  const BASE = { opportunityId: OPP_ID, requestId: RID, rowVersion: 3 };
  const RECORDED = { decision: { id: "d" }, request: { id: RID }, version_status: "approved" };

  beforeEach(() => api.POST.mockReset());

  it("posts with If-Match; approve sends a null reason", async () => {
    api.POST.mockResolvedValue({ data: RECORDED, response: status(201) });
    expect(await decideReviewRequest({ ...BASE, decision: "approved", reason: "  " })).toEqual({
      kind: "ok",
      value: RECORDED,
    });
    expect(api.POST).toHaveBeenCalledWith(PATH, {
      params: { path: { opportunity_id: OPP_ID, request_id: RID }, header: { "If-Match": '"3"' } },
      body: { decision: "approved", reason: null },
    });
  });

  it("reject sends the trimmed reason; only escalate sends escalated_to", async () => {
    api.POST.mockResolvedValue({ data: RECORDED, response: status(201) });
    const reject = { ...BASE, decision: "rejected", reason: "  No basis  ", escalatedTo: CY };
    await decideReviewRequest(reject);
    expect(api.POST.mock.calls[0]![1].body).toEqual({ decision: "rejected", reason: "No basis" });
    await decideReviewRequest({ ...BASE, decision: "escalated", reason: "Cy", escalatedTo: CY });
    expect(api.POST.mock.calls[1]![1].body).toEqual({
      decision: "escalated",
      reason: "Cy",
      escalated_to: CY,
    });
  });

  it.each([
    [412, { code: "row_version_mismatch", detail: "Changed by Ana since you opened it." }, {
      kind: "stale",
      detail: "Changed by Ana since you opened it.",
    }],
    [409, { code: "review_request_not_pending", detail: "Only pending." }, {
      kind: "invalid",
      detail: "Only pending.",
    }],
    [422, { code: "validation_error", detail: "Give a reason." }, {
      kind: "invalid",
      detail: "Give a reason.",
    }],
    [403, { code: "forbidden", detail: "Not allowed" }, { kind: "forbidden", detail: null }],
    [403, { code: "self_approval_forbidden", detail: "You authored v3." }, {
      kind: "forbidden",
      detail: "You authored v3.",
    }],
    [404, { code: "not_found" }, { kind: "not-found" }],
    [500, { code: "internal_error" }, { kind: "error" }],
  ])("maps %i %o", async (code, error, expected) => {
    api.POST.mockResolvedValue({ error, response: status(code) });
    expect(await decideReviewRequest({ ...BASE, decision: "approved", reason: "" })).toEqual(
      expected,
    );
  });

  it("refuses bad input without calling the API", async () => {
    for (const bad of [
      { ...BASE, decision: "challenged", reason: "x" },
      { ...BASE, decision: "approved", reason: "", rowVersion: "3" },
      { ...BASE, decision: "escalated", reason: "x", escalatedTo: "nope" },
    ]) {
      expect(await decideReviewRequest(bad)).toEqual({ kind: "error" });
    }
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("replyToReviewRequest (Story 9.4)", () => {
  const RID = "00000000-0000-7000-8000-0000000000d1";
  const V4 = "00000000-0000-7000-8000-0000000000e4";
  const PATH = "/api/v1/opportunities/{opportunity_id}/review-requests/{request_id}/replies";
  const R4 = { kind: "requirement", id: "00000000-0000-7000-8000-0000000000e9", version: 1 };
  const BASE = { opportunityId: OPP_ID, requestId: RID, rowVersion: 3, evidence: [R4] };
  const RECORDED = { reply: { id: "r" }, request: { id: RID } };

  beforeEach(() => api.POST.mockReset());

  it("posts the trimmed message and Evidence with If-Match; an alternative only when given", async () => {
    api.POST.mockResolvedValue({ data: RECORDED, response: status(201) });
    expect(await replyToReviewRequest({ ...BASE, message: "  See R4  " })).toEqual({
      kind: "ok",
      value: RECORDED,
    });
    expect(api.POST).toHaveBeenCalledWith(PATH, {
      params: { path: { opportunity_id: OPP_ID, request_id: RID }, header: { "If-Match": '"3"' } },
      body: { message: "See R4", evidence: [R4] },
    });
    await replyToReviewRequest({ ...BASE, message: "v4", alternativeVersionId: V4 });
    expect(api.POST.mock.calls[1]![1].body).toEqual({
      message: "v4",
      evidence: [R4],
      alternative_version_id: V4,
    });
  });

  it.each([
    [412, { code: "row_version_mismatch", detail: "Changed by Ana since you opened it." }, {
      kind: "stale",
      detail: "Changed by Ana since you opened it.",
    }],
    [409, { code: "review_reply_not_expected", detail: "Nothing to reply to." }, {
      kind: "invalid",
      detail: "Nothing to reply to.",
    }],
    [422, { code: "evidence_unresolvable", detail: "Evidence requirement:x does not resolve" }, {
      kind: "invalid",
      detail: "Evidence requirement:x does not resolve",
    }],
    [422, { code: "evidence_unresolvable" }, {
      kind: "invalid",
      detail: "That Evidence can't be cited: choose this Opportunity's Requirements or Sources.",
    }],
    [403, { code: "forbidden" }, { kind: "forbidden" }],
    [404, { code: "not_found" }, { kind: "not-found" }],
    [500, { code: "internal_error" }, { kind: "error" }],
  ])("maps %i %o", async (code, error, expected) => {
    api.POST.mockResolvedValue({ error, response: status(code) });
    expect(await replyToReviewRequest({ ...BASE, message: "x" })).toEqual(expected);
  });

  it("refuses bad input without calling the API", async () => {
    for (const bad of [
      { ...BASE, message: 3 },
      { ...BASE, message: "x", evidence: [{ kind: "knowledge_chunk", id: R4.id, version: 1 }] },
      { ...BASE, message: "x", alternativeVersionId: "nope" },
    ]) {
      expect(await replyToReviewRequest(bad)).toEqual({ kind: "error" });
    }
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("createEstimateVersion (Story 9.4)", () => {
  const V3 = "00000000-0000-7000-8000-0000000000e3";
  const PATH = "/api/v1/opportunities/{opportunity_id}/estimate-versions/{version_id}/new-version";

  beforeEach(() => api.POST.mockReset());

  it("posts for the base version", async () => {
    const created = { id: "v4", version: 4, status: "draft", row_version: 1 };
    api.POST.mockResolvedValue({ data: created, response: status(201) });
    expect(await createEstimateVersion({ opportunityId: OPP_ID, versionId: V3 })).toEqual({
      kind: "ok",
      value: created,
    });
    expect(api.POST).toHaveBeenCalledWith(PATH, {
      params: { path: { opportunity_id: OPP_ID, version_id: V3 } },
      body: {},
    });
  });

  it("maps a 409 to the API's sentence and refuses bad ids", async () => {
    api.POST.mockResolvedValue({
      error: { code: "estimate_draft_exists", detail: "Draft v4 already exists." },
      response: status(409),
    });
    expect(await createEstimateVersion({ opportunityId: OPP_ID, versionId: V3 })).toEqual({
      kind: "invalid",
      detail: "Draft v4 already exists.",
    });
    api.POST.mockReset();
    expect(await createEstimateVersion({ opportunityId: OPP_ID, versionId: "x" })).toEqual({
      kind: "error",
    });
    expect(api.POST).not.toHaveBeenCalled();
  });
});

describe("Challenges (Story 9.5)", () => {
  const CID = "00000000-0000-7000-8000-0000000000b1";
  const TARGET = "00000000-0000-7000-8000-0000000000f9";
  const RID = "00000000-0000-7000-8000-0000000000c1";
  const VIEW = { id: CID, status: "awaiting_confirmation" };

  beforeEach(() => {
    api.POST.mockReset();
    api.GET.mockReset();
  });

  it("raises with the trimmed reason, the request and, for the owner, confirmed", async () => {
    api.POST.mockResolvedValue({ data: VIEW, response: status(201) });
    const input = {
      opportunityId: OPP_ID,
      targetKind: "finding",
      targetId: TARGET,
      reason: "  Too low  ",
      reviewRequestId: RID,
    };
    expect(await raiseChallenge(input)).toEqual({ kind: "ok", value: VIEW });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/challenges", {
      params: { path: { opportunity_id: OPP_ID } },
      body: {
        target_kind: "finding",
        target_id: TARGET,
        reason: "Too low",
        review_request_id: RID,
      },
    });
    await raiseChallenge({
      opportunityId: OPP_ID,
      targetKind: "assessment",
      targetId: TARGET,
      reason: "x",
      confirmed: ["engineering_agent"],
    });
    expect(api.POST.mock.calls[1]![1].body).toEqual({
      target_kind: "assessment",
      target_id: TARGET,
      reason: "x",
      confirmed: ["engineering_agent"],
    });
  });

  it("confirms and declines with If-Match", async () => {
    api.POST.mockResolvedValue({ data: VIEW, response: status(200) });
    await confirmChallenge({
      opportunityId: OPP_ID,
      challengeId: CID,
      rowVersion: 2,
      confirmed: ["engineering_agent", "pm_agent"],
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/challenges/{challenge_id}/confirm",
      {
        params: {
          path: { opportunity_id: OPP_ID, challenge_id: CID },
          header: { "If-Match": '"2"' },
        },
        body: { confirmed: ["engineering_agent", "pm_agent"] },
      },
    );
    const decline = { opportunityId: OPP_ID, challengeId: CID, rowVersion: 1, reason: " No " };
    await declineChallenge(decline);
    expect(api.POST.mock.calls[1]![0]).toBe(
      "/api/v1/opportunities/{opportunity_id}/challenges/{challenge_id}/decline",
    );
    expect(api.POST.mock.calls[1]![1].body).toEqual({ reason: "No" });
  });

  it.each([
    [412, { code: "row_version_mismatch" }, { kind: "stale" }],
    [409, { code: "challenge_version_superseded", detail: "v2 is superseded by v3." }, {
      kind: "invalid",
      detail: "v2 is superseded by v3.",
      code: "challenge_version_superseded",
    }],
    [422, { code: "validation_error", detail: "Tick at least one." }, {
      kind: "invalid",
      detail: "Tick at least one.",
      code: "validation_error",
    }],
    [403, { code: "forbidden", detail: "Only the owner." }, {
      kind: "forbidden",
      detail: "Only the owner.",
    }],
    [404, { code: "not_found" }, { kind: "not-found" }],
    [500, { code: "internal_error" }, { kind: "error" }],
  ])("maps %i %o", async (code, error, expected) => {
    api.POST.mockResolvedValue({ error, response: status(code) });
    expect(
      await confirmChallenge({
        opportunityId: OPP_ID,
        challengeId: CID,
        rowVersion: 1,
        confirmed: ["engineering_agent"],
      }),
    ).toEqual(expected);
  });

  it("reads the suggestions and the Challenge", async () => {
    api.GET.mockResolvedValue({ data: VIEW, response: status(200) });
    expect(
      await loadChallengeSuggestions({
        opportunityId: OPP_ID,
        targetKind: "finding",
        targetId: TARGET,
      }),
    ).toEqual({ kind: "ok", value: VIEW });
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/challenges/suggestions",
      {
        params: {
          path: { opportunity_id: OPP_ID },
          query: { target_kind: "finding", target_id: TARGET },
        },
      },
    );
    expect(await loadChallenge({ opportunityId: OPP_ID, challengeId: CID })).toEqual({
      kind: "ok",
      value: VIEW,
    });
    api.GET.mockResolvedValue({
      error: { code: "challenge_needs_estimate", detail: "No Estimate yet." },
      response: status(409),
    });
    expect(
      await loadChallengeSuggestions({
        opportunityId: OPP_ID,
        targetKind: "finding",
        targetId: TARGET,
      }),
    ).toEqual({ kind: "invalid", detail: "No Estimate yet." });
  });

  it("refuses bad input without calling the API", async () => {
    expect(
      await raiseChallenge({
        opportunityId: OPP_ID,
        targetKind: "line",
        targetId: TARGET,
        reason: "x",
      }),
    ).toEqual({ kind: "error" });
    expect(
      await raiseChallenge({
        opportunityId: OPP_ID,
        targetKind: "finding",
        targetId: TARGET,
        reason: "x",
        confirmed: ["critic_agent"],
      }),
    ).toEqual({ kind: "error" });
    expect(
      await confirmChallenge({
        opportunityId: OPP_ID,
        challengeId: CID,
        rowVersion: "1",
        confirmed: [],
      }),
    ).toEqual({ kind: "error" });
    expect(api.POST).not.toHaveBeenCalled();
  });
});


describe("Actuals (Story 10.1)", () => {
  const LINE = "00000000-0000-7000-8000-0000000000b2";
  const AID = "00000000-0000-7000-8000-0000000000c2";
  const SAVED = { recorded: 1, corrected: 0, view: { row_version: 5 } };
  const ITEM = { line_id: LINE, kind: "final", effort_hours: 41, variance_cause: "other" };

  beforeEach(() => {
    api.POST.mockReset();
  });

  it("saveActuals posts the items and reason with the quoted If-Match", async () => {
    api.POST.mockResolvedValue({ data: SAVED, response: status(200) });
    expect(
      await saveActuals({ opportunityId: OPP_ID, rowVersion: 4, items: [ITEM], reason: "Fix" }),
    ).toEqual({ kind: "ok", saved: SAVED });
    expect(api.POST).toHaveBeenCalledWith("/api/v1/opportunities/{opportunity_id}/actuals", {
      params: { path: { opportunity_id: OPP_ID }, header: { "If-Match": '"4"' } },
      body: { items: [ITEM], reason: "Fix" },
    });
  });

  it("correctActual posts the fields with the Actual's version", async () => {
    api.POST.mockResolvedValue({ data: SAVED, response: status(201) });
    const fields = { kind: "final", effort_hours: 40, reason: "Late invoice" };
    await correctActual({ opportunityId: OPP_ID, actualId: AID, version: 2, fields });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/actuals/{actual_id}/corrections",
      {
        params: {
          path: { opportunity_id: OPP_ID, actual_id: AID },
          header: { "If-Match": '"2"' },
        },
        body: fields,
      },
    );
  });

  it("closeDelivery posts with the quoted If-Match", async () => {
    api.POST.mockResolvedValue({ data: { row_version: 7 }, response: status(200) });
    expect(await closeDelivery({ opportunityId: OPP_ID, rowVersion: 6 })).toEqual({
      kind: "ok",
      actuals: { row_version: 7 },
    });
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/actuals/delivery/close",
      { params: { path: { opportunity_id: OPP_ID }, header: { "If-Match": '"6"' } } },
    );
  });

  const ERRORS = [{ item: 0, field: "variance_cause", message: "Needs a cause." }];
  it.each([
    [422, { code: "actual_invalid", errors: ERRORS }, { kind: "invalid", errors: ERRORS }],
    [412, { code: "row_version_mismatch" }, { kind: "stale" }],
    [403, { code: "forbidden" }, { kind: "forbidden" }],
    [409, { code: "delivery_closed", detail: "Delivery is closed." }, {
      kind: "conflict",
      detail: "Delivery is closed.",
    }],
    [500, { code: "internal_error" }, { kind: "error" }],
  ])("save and correct map %i %o", async (code, error, expected) => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    api.POST.mockResolvedValue({ error, response: status(code) });
    expect(await saveActuals({ opportunityId: OPP_ID, rowVersion: 1, items: [ITEM] })).toEqual(
      expected,
    );
    expect(
      await correctActual({
        opportunityId: OPP_ID,
        actualId: AID,
        version: 1,
        fields: { kind: "final", effort_hours: 1, reason: "x" },
      }),
    ).toEqual(expected);
  });

  it.each([
    [412, { code: "row_version_mismatch" }, { kind: "stale" }],
    [403, { code: "forbidden" }, { kind: "forbidden" }],
    [409, { code: "delivery_not_ready", detail: "1 line has no final Actual" }, {
      kind: "conflict",
      detail: "1 line has no final Actual",
    }],
  ])("closeDelivery maps %i %o", async (code, error, expected) => {
    api.POST.mockResolvedValue({ error, response: status(code) });
    expect(await closeDelivery({ opportunityId: OPP_ID, rowVersion: 1 })).toEqual(expected);
  });

  it("rejects bad input without calling the API", async () => {
    expect(await saveActuals({ opportunityId: "x", rowVersion: 1, items: [ITEM] })).toEqual({
      kind: "error",
    });
    expect(await closeDelivery({ opportunityId: OPP_ID, rowVersion: -1 })).toEqual({
      kind: "error",
    });
    expect(api.POST).not.toHaveBeenCalled();
  });
});
