"use server";

import {
  getAssessments,
  getConflicts,
  getEstimate,
  getOpportunity,
  getRedTeam,
  listGaps,
  listOutdatedAssessments,
  listRequirements,
  listSources,
  type AssessmentsResult,
  type EstimateResult,
  type GapsResult,
  type OutdatedAssessmentsResult,
  type RedTeamResult,
  type RequirementsResult,
  type SourcesResult,
} from "@/app/opportunities/data";
import { createServerApiClient } from "@/lib/api/server";
import type { AssessmentAgent, AssessmentRun } from "@/lib/assessments";
import type { Conflict } from "@/lib/conflicts";
import type {
  Assumption,
  AssumptionKind,
  EstimateDraft,
  EstimateView,
  Risk,
  RiskLevel,
  RoleMix,
} from "@/lib/estimates";
import { openGapCount, type ClarificationQuestion, type Detection, type Gap } from "@/lib/gaps";
import type { OpportunityImport } from "@/lib/opportunity-import";
import type { RedTeamRun } from "@/lib/red-team";
import {
  codePointLength,
  sliceCodePoints,
  TITLE_MAX,
  UUID_RE,
  type Opportunity,
  type UserSummary,
} from "@/lib/opportunities";
import {
  CLASSIFICATIONS,
  type Classification,
  type Extraction,
  type Passage,
  type Requirement,
} from "@/lib/requirements";
import type { Source } from "@/lib/sources";

/** The API's query bounds for people search (in code points). */
const SEARCH_MIN = 2;
const SEARCH_MAX = 100;

export type CreateField =
  | "title"
  | "customer_name"
  | "products"
  | "industry"
  | "target_proposal_date";

export type CreateInput = {
  title: string;
  customer_name: string;
  products: string[];
  industry: string;
  target_proposal_date: string;
  /** An Opportunity import whose file becomes the first Source. */
  importId?: string;
};

export type CreateResult =
  | { kind: "ok"; id: string }
  /** 422: the fields the API rejected (empty when it named none we know). */
  | { kind: "invalid"; fields: CreateField[] }
  /** 404 / 409 / 410 for the import: not the caller's, already used, or expired. */
  | { kind: "import-unusable" }
  | { kind: "forbidden" }
  | { kind: "error" };

export type ImportFileResult =
  | { kind: "ok"; import: OpportunityImport }
  /** 413 / 415 / 422: the API's sentence for the UI ("Rejected: .exe files aren't allowed"). */
  | { kind: "rejected"; reason: string }
  | { kind: "forbidden" }
  | { kind: "error" };

export type LoadImportResult =
  | { kind: "ok"; import: OpportunityImport }
  /** 404 / 410: not the caller's, or expired. */
  | { kind: "gone" }
  | { kind: "error" };

export type LoadResult =
  | { kind: "ok"; opportunity: Opportunity }
  | { kind: "not-found" }
  | { kind: "error" };

export type CollaboratorInput = {
  opportunityId: string;
  userId: string;
  /** True to add the collaborator, false to remove them. */
  add: boolean;
  /** The `row_version` the page was opened with; sent as `If-Match`. */
  rowVersion: number;
};

export type CollaboratorResult =
  | { kind: "ok"; opportunity: Opportunity }
  /** 412: someone changed the Opportunity first. `changedBy` is null when unknown. */
  | { kind: "stale"; changedBy: string | null }
  /** 422 `invalid_collaborator`, with the API's detail text. */
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type UpdateInput = {
  opportunityId: string;
  /** The `row_version` the header last saw; sent as `If-Match`. */
  rowVersion: number;
  /** The new title (blank falls back to the customer name). Omit to leave it unchanged. */
  title?: string;
  /** The new target proposal date (`YYYY-MM-DD`). Omit to leave it unchanged. */
  target_proposal_date?: string;
};

export type UpdateResult =
  | { kind: "ok"; opportunity: Opportunity }
  /** 412: someone changed the Opportunity first. `changedBy` is null when unknown. */
  | { kind: "stale"; changedBy: string | null }
  /** 422: a readable reason. */
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type AddSourceResult =
  | { kind: "ok"; source: Source }
  /** 422: the API's sentence for the UI ("Rejected: .exe files aren't allowed"). */
  | { kind: "rejected"; reason: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type RetryParseResult =
  | { kind: "ok"; source: Source }
  /** 409: the latest version's parse has not failed (any more). */
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type StartExtractionResult =
  | { kind: "ok"; extraction: Extraction }
  /** 409: an extraction is already queued or running. */
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type StartEstimateDraftResult =
  | { kind: "ok"; draft: EstimateDraft }
  /** 409: a draft is already queued or running. */
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type StartRedTeamReviewResult =
  | { kind: "ok"; run: RedTeamRun }
  /** 409: a Red Team review is already queued or running. */
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type StartAssessmentResult =
  | { kind: "ok"; run: AssessmentRun }
  /** 409: an assessment is already queued or running, or the task is no longer failed. */
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type StartGapDetectionResult =
  | { kind: "ok"; detection: Detection }
  /** 409: a detection is already queued or running. */
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type PassageResult =
  | { kind: "ok"; passage: Passage }
  /** 404: no such passage in this Opportunity, or the Opportunity can't be read. */
  | { kind: "not-found" }
  | { kind: "error" };

export type SearchResult = { kind: "ok"; users: UserSummary[] } | { kind: "error" };

const CREATE_FIELDS: readonly CreateField[] = [
  "title",
  "customer_name",
  "products",
  "industry",
  "target_proposal_date",
];

function problem(error: unknown): { code?: string; detail?: string } {
  const { code, detail } = (error ?? {}) as { code?: unknown; detail?: unknown };
  return {
    code: typeof code === "string" ? code : undefined,
    detail: typeof detail === "string" ? detail : undefined,
  };
}

/** The fields named in a `validation_error` detail ("Invalid fields: body.products, ..."). */
function invalidFields(detail: string | undefined): CreateField[] {
  if (!detail) return [];
  return CREATE_FIELDS.filter((field) =>
    new RegExp(`(^|[\\s,:])body\\.${field}(\\.|,|$)`).test(detail),
  );
}

function isCreateInput(input: unknown): input is CreateInput {
  if (typeof input !== "object" || input === null) return false;
  const { title, customer_name, products, industry, target_proposal_date } = input as Record<
    string,
    unknown
  >;
  const { importId } = input as Record<string, unknown>;
  return (
    (importId === undefined || (typeof importId === "string" && UUID_RE.test(importId))) &&
    typeof title === "string" &&
    typeof customer_name === "string" &&
    Array.isArray(products) &&
    products.every((p) => typeof p === "string") &&
    typeof industry === "string" &&
    typeof target_proposal_date === "string"
  );
}

/** `POST /api/v1/opportunities`. Field rules are enforced by the API. */
export async function createOpportunity(input: unknown): Promise<CreateResult> {
  if (!isCreateInput(input)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST("/api/v1/opportunities", {
      body: {
        title: input.title.trim() ? input.title : null,
        customer_name: input.customer_name,
        products: input.products,
        industry: input.industry,
        target_proposal_date: input.target_proposal_date,
        ...(input.importId ? { import_id: input.importId } : {}),
      },
    });
    if (data) return { kind: "ok", id: data.id };
    if (response.status === 422) return { kind: "invalid", fields: invalidFields(problem(error).detail) };
    if (response.status === 403) return { kind: "forbidden" };
    if (input.importId && [404, 409, 410].includes(response.status)) {
      return { kind: "import-unusable" };
    }
    console.error(`create opportunity failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`create opportunity failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunity-imports` with the `file` from `formData`: one file to start a
 * New Opportunity from. The API checks who may import, the type, the size and the content;
 * this only forwards the file. */
export async function importFile(formData: unknown): Promise<ImportFileResult> {
  if (!(formData instanceof FormData)) return { kind: "error" };
  const file = formData.get("file");
  if (!(file instanceof File)) return { kind: "error" };
  const upload = new FormData();
  upload.append("file", file, file.name);
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST("/api/v1/opportunity-imports", {
      // The generated type describes the multipart field; the body sent is the FormData.
      body: { file: "" },
      bodySerializer: () => upload,
    });
    if (data) return { kind: "ok", import: data };
    switch (response.status) {
      case 413:
      case 415:
      case 422:
        return { kind: "rejected", reason: rejectionReason(problem(error).detail, FILE_UNREADABLE) };
      case 403:
        return { kind: "forbidden" };
      default:
        console.error(`import file failed: status=${response.status} code=${String(problem(error).code)}`);
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(`import file failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunity-imports/{id}`: the import's status and suggestions (the New
 * Opportunity form polls this while the file is read). */
export async function loadImport(importId: unknown): Promise<LoadImportResult> {
  if (typeof importId !== "string" || !UUID_RE.test(importId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.GET("/api/v1/opportunity-imports/{import_id}", {
      params: { path: { import_id: importId } },
    });
    if (data) return { kind: "ok", import: data };
    if (response.status === 404 || response.status === 410) return { kind: "gone" };
    console.error(`load import failed: status=${response.status} code=${String(problem(error).code)}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`load import failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** The Opportunity as stored now (for Reload after a 412). */
export async function loadOpportunity(id: unknown): Promise<LoadResult> {
  return getOpportunity(id);
}

function isCollaboratorInput(input: unknown): input is CollaboratorInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, userId, add, rowVersion } = input as Record<string, unknown>;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof userId === "string" &&
    UUID_RE.test(userId) &&
    typeof add === "boolean" &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0
  );
}

/** Adds or removes one collaborator with `If-Match`. Never retries or overwrites on 412. */
export async function changeCollaborator(input: unknown): Promise<CollaboratorResult> {
  if (!isCollaboratorInput(input)) return { kind: "error" };
  const { opportunityId, userId, add, rowVersion } = input;
  try {
    const api = await createServerApiClient();
    const init = {
      params: {
        path: { opportunity_id: opportunityId, user_id: userId },
        header: { "If-Match": `"${rowVersion}"` },
      },
    };
    const path = "/api/v1/opportunities/{opportunity_id}/collaborators/{user_id}" as const;
    const { data, error, response } = add
      ? await api.PUT(path, init)
      : await api.DELETE(path, init);
    if (data) return { kind: "ok", opportunity: data };
    switch (response.status) {
      case 412: {
        const current = await getOpportunity(opportunityId);
        return {
          kind: "stale",
          changedBy: current.kind === "ok" ? current.opportunity.last_changed_by : null,
        };
      }
      case 422:
        return {
          kind: "invalid",
          detail: problem(error).detail ?? "This person can't be a collaborator.",
        };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `change collaborator failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `change collaborator failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function isUpdateInput(input: unknown): input is UpdateInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, rowVersion, title, target_proposal_date } = input as Record<
    string,
    unknown
  >;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0 &&
    (title === undefined || typeof title === "string") &&
    (target_proposal_date === undefined ||
      (typeof target_proposal_date === "string" && DATE_RE.test(target_proposal_date))) &&
    (title !== undefined || target_proposal_date !== undefined)
  );
}

/** A readable reason for a 422 on an edit. The API's own sentence (e.g. a past date) is
 * kept; its "Invalid fields: body.x" format is turned into words. */
function updateReason(detail: string | undefined): string {
  if (!detail) return "The change was not accepted.";
  if (!detail.startsWith("Invalid fields:")) return detail;
  if (/body\.title\b/.test(detail)) return `The title can be at most ${TITLE_MAX} characters.`;
  if (/body\.target_proposal_date\b/.test(detail)) return "Enter a valid date.";
  return "The change was not accepted.";
}

/** `PATCH /api/v1/opportunities/{id}` with `If-Match`: the title and/or target proposal date.
 * Never retries or overwrites on 412. */
export async function updateOpportunity(input: unknown): Promise<UpdateResult> {
  if (!isUpdateInput(input)) return { kind: "error" };
  const { opportunityId, rowVersion, title, target_proposal_date } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PATCH("/api/v1/opportunities/{opportunity_id}", {
      params: {
        path: { opportunity_id: opportunityId },
        header: { "If-Match": `"${rowVersion}"` },
      },
      body: {
        ...(title !== undefined ? { title } : {}),
        ...(target_proposal_date !== undefined ? { target_proposal_date } : {}),
      },
    });
    if (data) return { kind: "ok", opportunity: data };
    switch (response.status) {
      case 412: {
        const current = await getOpportunity(opportunityId);
        return {
          kind: "stale",
          changedBy: current.kind === "ok" ? current.opportunity.last_changed_by : null,
        };
      }
      case 422:
        return { kind: "invalid", detail: updateReason(problem(error).detail) };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `update opportunity failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `update opportunity failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `GET /api/v1/users/search?q=`: people with a role, by name or email. Queries shorter than
 * two characters return nothing without calling the API. */
export async function searchUsers(q: unknown): Promise<SearchResult> {
  if (typeof q !== "string") return { kind: "error" };
  const query = sliceCodePoints(q.trim(), SEARCH_MAX);
  if (codePointLength(query) < SEARCH_MIN) return { kind: "ok", users: [] };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/users/search", {
      params: { query: { q: query, limit: 10 } },
    });
    if (data) return { kind: "ok", users: data.items };
    console.error(`search users failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`search users failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

const FILE_UNREADABLE = "Rejected: the file couldn't be read";
const TEXT_UNREADABLE = "Rejected: the text couldn't be read";

/** A 422's sentence: the API's own "Rejected: ..." detail, or a general one. */
function rejectionReason(detail: string | undefined, fallback: string): string {
  if (detail?.startsWith("Rejected:")) return detail;
  return fallback;
}

/** An add-Source call's outcome (a file or pasted text), by status. */
function addSourceResult(
  label: string,
  data: Source | undefined,
  error: unknown,
  response: Response,
  fallbackReason: string,
): AddSourceResult {
  if (data) return { kind: "ok", source: data };
  switch (response.status) {
    case 422:
      return { kind: "rejected", reason: rejectionReason(problem(error).detail, fallbackReason) };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${label} failed: status=${response.status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/sources` with the `file` from `formData` (its
 * `opportunityId` names the Opportunity). The API checks who may add, the type, the size and
 * the content; this only forwards the file. */
export async function addSource(formData: unknown): Promise<AddSourceResult> {
  if (!(formData instanceof FormData)) return { kind: "error" };
  const opportunityId = formData.get("opportunityId");
  const file = formData.get("file");
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  if (!(file instanceof File)) return { kind: "error" };
  const upload = new FormData();
  upload.append("file", file, file.name);
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/sources",
      {
        params: { path: { opportunity_id: opportunityId } },
        // The generated type describes the multipart field; the body sent is the FormData.
        body: { file: "" },
        bodySerializer: () => upload,
      },
    );
    return addSourceResult("add source", data, error, response, FILE_UNREADABLE);
  } catch (thrown) {
    console.error(`add source failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/sources/text`: pasted text as a `note` Source named
 * "Pasted text". The API trims it and checks who may add, the length and the characters;
 * this only forwards it. Results map as for `addSource`. */
export async function addTextSource(
  opportunityId: unknown,
  text: unknown,
): Promise<AddSourceResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  if (typeof text !== "string") return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/sources/text",
      { params: { path: { opportunity_id: opportunityId } }, body: { text } },
    );
    return addSourceResult("add text source", data, error, response, TEXT_UNREADABLE);
  } catch (thrown) {
    console.error(`add text source failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/sources/{source_id}/parse`: parse a Source's failed
 * latest version again. The API checks who may retry and that the parse failed. */
export async function retryParse(
  opportunityId: unknown,
  sourceId: unknown,
): Promise<RetryParseResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  if (typeof sourceId !== "string" || !UUID_RE.test(sourceId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/sources/{source_id}/parse",
      { params: { path: { opportunity_id: opportunityId, source_id: sourceId } } },
    );
    if (data) return { kind: "ok", source: data };
    switch (response.status) {
      case 409:
        return { kind: "conflict" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `retry parse failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(`retry parse failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** The Opportunity's Sources as stored now (the Sources tab polls this while a parse is
 * pending). */
export async function loadSources(opportunityId: unknown): Promise<SourcesResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  return listSources(opportunityId);
}

export type SourceTextResult =
  | { kind: "ok"; version: number; text: string; charCount: number }
  /** 404: not parsed (yet), or not readable by the caller. */
  | { kind: "unavailable" }
  | { kind: "error" };

/** `GET /api/v1/opportunities/{id}/sources/{source_id}/versions/{version}/text`: the
 * extracted text of a parsed Source version, for the Sources tab's inspector (Story 2.3). */
export async function loadSourceText(
  opportunityId: unknown,
  sourceId: unknown,
  version: unknown,
): Promise<SourceTextResult> {
  if (
    typeof opportunityId !== "string" ||
    !UUID_RE.test(opportunityId) ||
    typeof sourceId !== "string" ||
    !UUID_RE.test(sourceId) ||
    typeof version !== "number" ||
    !Number.isSafeInteger(version) ||
    version < 1
  ) {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/sources/{source_id}/versions/{version}/text",
      { params: { path: { opportunity_id: opportunityId, source_id: sourceId, version } } },
    );
    if (data) {
      return { kind: "ok", version: data.version, text: data.text, charCount: data.char_count };
    }
    if (response.status === 404) return { kind: "unavailable" };
    console.error(`GET source text failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET source text failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** The Opportunity's Requirements and latest extraction as stored now (the Requirements tab
 * polls this while an extraction runs). */
export async function loadRequirements(opportunityId: unknown): Promise<RequirementsResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  return listRequirements(opportunityId);
}

/** `POST /api/v1/opportunities/{id}/extractions`: extract the Requirements again (the Retry of
 * a failed extraction). The API checks who may start one and that none is running. */
export async function startExtraction(opportunityId: unknown): Promise<StartExtractionResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/extractions",
      { params: { path: { opportunity_id: opportunityId } } },
    );
    if (data) return { kind: "ok", extraction: data };
    switch (response.status) {
      case 409:
        return { kind: "conflict" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `start extraction failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `start extraction failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** The Opportunity's open Gaps and latest detection as stored now (the Gaps tab polls this
 * while a detection runs). */
export async function loadGaps(opportunityId: unknown): Promise<GapsResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  return listGaps(opportunityId);
}

/** How many of the Opportunity's Gaps are open (the Gaps tab badge, Story 4.7); null when it
 * can't be read. */
export async function countOpenGaps(opportunityId: unknown): Promise<number | null> {
  const loaded = await loadGaps(opportunityId);
  return loaded.kind === "ok" ? openGapCount(loaded.list.items) : null;
}

/** How many of the Opportunity's Conflicts are open or escalated (the Conflicts tab badge,
 * Story 6.2); null when they can't be read. */
export async function countOpenConflicts(opportunityId: unknown): Promise<number | null> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return null;
  const loaded = await getConflicts(opportunityId);
  return loaded.kind === "ok" ? loaded.conflicts.open_count : null;
}

/** `POST /api/v1/opportunities/{id}/gap-detections`: detect the Gaps again (the Retry of a
 * failed detection). The API checks who may start one and that none is running. */
export async function startGapDetection(opportunityId: unknown): Promise<StartGapDetectionResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/gap-detections",
      { params: { path: { opportunity_id: opportunityId } } },
    );
    if (data) return { kind: "ok", detection: data };
    switch (response.status) {
      case 409:
        return { kind: "conflict" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `start gap detection failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `start gap detection failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** The Opportunity's Estimate and latest draft as stored now (the Estimate tab polls this
 * while a draft runs). */
export async function loadEstimate(opportunityId: unknown): Promise<EstimateResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  return getEstimate(opportunityId);
}

/** `POST /api/v1/opportunities/{id}/estimate-drafts`: draft the Estimate again (the Retry of
 * a failed draft). The API checks who may start one and that none is running. */
export async function startEstimateDraft(
  opportunityId: unknown,
): Promise<StartEstimateDraftResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/estimate-drafts",
      { params: { path: { opportunity_id: opportunityId } } },
    );
    if (data) return { kind: "ok", draft: data };
    switch (response.status) {
      case 409:
        return { kind: "conflict" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `start estimate draft failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `start estimate draft failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** The Opportunity's Red Team Review and latest run as stored now (the Assessments tab polls
 * this while a review runs). */
export async function loadRedTeam(opportunityId: unknown): Promise<RedTeamResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  return getRedTeam(opportunityId);
}

/** `POST /api/v1/opportunities/{id}/red-team-reviews`: review the Opportunity again (the Retry
 * of a failed review). The API checks who may start one and that none is running. */
export async function startRedTeamReview(
  opportunityId: unknown,
): Promise<StartRedTeamReviewResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/red-team-reviews",
      { params: { path: { opportunity_id: opportunityId } } },
    );
    if (data) return { kind: "ok", run: data };
    switch (response.status) {
      case 409:
        return { kind: "conflict" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `start red team review failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `start red team review failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** The Opportunity's latest assessment run and current Assessments as stored now (the
 * Assessments tab polls this while a run is queued or running). */
export async function loadAssessments(opportunityId: unknown): Promise<AssessmentsResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  return getAssessments(opportunityId);
}

const ASSESSMENT_AGENTS: readonly string[] = ["engineering_agent", "pm_agent", "security_agent"];

function startResult(
  label: string,
  data: AssessmentRun | undefined,
  error: unknown,
  status: number,
): StartAssessmentResult {
  if (data) return { kind: "ok", run: data };
  switch (status) {
    case 409:
      return { kind: "conflict" };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${label} failed: status=${status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/assessment-runs`: the Engineering, PM and Security Agents
 * assess the Opportunity. The API checks who may start one and that none is running. */
export async function startAssessmentRun(opportunityId: unknown): Promise<StartAssessmentResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs",
      { params: { path: { opportunity_id: opportunityId } } },
    );
    return startResult("start assessment run", data, error, response.status);
  } catch (thrown) {
    console.error(
      `start assessment run failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/assessment-runs/{run_id}/tasks/{agent}/retry`: re-run one
 * failed agent task of the latest run. */
export async function retryAssessmentTask(
  opportunityId: unknown,
  runId: unknown,
  agent: unknown,
): Promise<StartAssessmentResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  if (typeof runId !== "string" || !UUID_RE.test(runId)) return { kind: "error" };
  if (typeof agent !== "string" || !ASSESSMENT_AGENTS.includes(agent)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs/{run_id}/tasks/{agent}/retry",
      {
        params: {
          path: {
            opportunity_id: opportunityId,
            run_id: runId,
            agent: agent as AssessmentAgent,
          },
        },
      },
    );
    return startResult("retry assessment task", data, error, response.status);
  } catch (thrown) {
    console.error(
      `retry assessment task failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/assessment-runs/{run_id}/cancel`: cancel the latest run
 * while it is queued, running or waiting for a person (Story 5.5); completed Assessments are
 * kept. 409 (`conflict`)
 * once it is no longer in progress. */
export async function cancelAssessmentRun(
  opportunityId: unknown,
  runId: unknown,
): Promise<StartAssessmentResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  if (typeof runId !== "string" || !UUID_RE.test(runId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs/{run_id}/cancel",
      { params: { path: { opportunity_id: opportunityId, run_id: runId } } },
    );
    return startResult("cancel assessment run", data, error, response.status);
  } catch (thrown) {
    console.error(
      `cancel assessment run failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

export type RunDecisionChoice = "continue_without" | "replan";

export type ResolveRunDecisionInput = {
  opportunityId: string;
  runId: string;
  decisionId: string;
  /** The decision's `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
  choice: RunDecisionChoice;
};

export type RunDecisionResult =
  /** The run, queued again to resume. */
  | { kind: "ok"; run: AssessmentRun }
  /** 412: someone resolved it first; `message` is the API's "Already resolved by {name}." */
  | { kind: "stale"; message: string }
  /** 409: the decision is no longer open (or its run was cancelled), or Re-plan while the
   * Agent is still disabled; `detail` is a sentence to show. */
  | { kind: "conflict"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

function isResolveRunDecisionInput(input: unknown): input is ResolveRunDecisionInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, runId, decisionId, rowVersion, choice } = input as Record<
    string,
    unknown
  >;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof runId === "string" &&
    UUID_RE.test(runId) &&
    typeof decisionId === "string" &&
    UUID_RE.test(decisionId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0 &&
    (choice === "continue_without" || choice === "replan")
  );
}

/** `POST /api/v1/opportunities/{id}/assessment-runs/{run_id}/decisions/{decision_id}/resolve`
 * with `If-Match` (Story 5.5): **Continue without** the disabled Agent, or **Re-plan** once it
 * is active again; the run then resumes. Never retries or overwrites on 412. Logs ids and
 * statuses only. */
export async function resolveRunDecision(input: unknown): Promise<RunDecisionResult> {
  if (!isResolveRunDecisionInput(input)) return { kind: "error" };
  const { opportunityId, runId, decisionId, rowVersion, choice } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/assessment-runs/{run_id}/decisions/{decision_id}/resolve",
      {
        params: {
          path: { opportunity_id: opportunityId, run_id: runId, decision_id: decisionId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: { choice },
      },
    );
    if (data) return { kind: "ok", run: data };
    const { detail, code } = problem(error);
    switch (response.status) {
      case 412:
        return { kind: "stale", message: detail ?? "Already resolved by someone else." };
      case 409:
        return {
          kind: "conflict",
          detail:
            code === "registry_agent_disabled"
              ? (detail ?? "The Agent is still disabled.")
              : "This decision is no longer open.",
        };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(`resolve run decision failed: status=${response.status} code=${String(code)}`);
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `resolve run decision failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/passages/{passage_id}`: a cited passage with its span and
 * the text around it, for the Evidence inspector. Logs ids and statuses only. */
export async function getPassage(opportunityId: unknown, passageId: unknown): Promise<PassageResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  if (typeof passageId !== "string" || !UUID_RE.test(passageId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/passages/{passage_id}",
      { params: { path: { opportunity_id: opportunityId, passage_id: passageId } } },
    );
    if (data) return { kind: "ok", passage: data };
    if (response.status === 404) return { kind: "not-found" };
    console.error(`get passage failed: status=${response.status} code=${String(problem(error).code)}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`get passage failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

// --- editing and confirming Requirements (Story 2.6) ------------------------------------------

export type RequirementEditInput = {
  opportunityId: string;
  requirementId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
  text?: string;
  classification?: Classification;
};

export type RequirementConfirmInput = {
  opportunityId: string;
  requirementId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
};

export type RequirementWriteResult = { kind: "ok"; requirement: Requirement } | RequirementFailure;

/** Why a Requirement write failed. */
export type RequirementFailure =
  /** 412: someone changed the Requirement first. `changedBy` is null when unknown;
   * `current` is the Requirement as now saved (null when unknown), for **View diff**. */
  | { kind: "stale"; changedBy: string | null; current?: Requirement | null }
  /** 422: a readable reason. */
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the Requirement is gone (superseded). */
  | { kind: "not-found" }
  | { kind: "error" };

export type ConfirmAllResult =
  { kind: "ok"; count: number } | { kind: "forbidden" } | { kind: "not-found" } | { kind: "error" };

const KNOWN_CLASSIFICATIONS = new Set<string>(CLASSIFICATIONS.map((c) => c.value));

function isRowTarget(input: unknown): input is RequirementConfirmInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, requirementId, rowVersion } = input as Record<string, unknown>;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof requirementId === "string" &&
    UUID_RE.test(requirementId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0
  );
}

function isEditInput(input: unknown): input is RequirementEditInput {
  if (!isRowTarget(input)) return false;
  const { text, classification } = input as Record<string, unknown>;
  return (
    (text === undefined || typeof text === "string") &&
    (classification === undefined ||
      (typeof classification === "string" && KNOWN_CLASSIFICATIONS.has(classification))) &&
    (text !== undefined || classification !== undefined)
  );
}

/** The Requirement as now saved, read again after a 412 (null when unknown or gone). */
async function currentRequirement(
  opportunityId: string,
  requirementId: string,
): Promise<Requirement | null> {
  const current = await listRequirements(opportunityId);
  if (current.kind !== "ok") return null;
  return current.list.items.find((item) => item.id === requirementId) ?? null;
}

async function requirementWriteFailure(
  action: string,
  input: RequirementConfirmInput,
  status: number,
  error: unknown,
): Promise<RequirementFailure> {
  switch (status) {
    case 412: {
      const current = await currentRequirement(input.opportunityId, input.requirementId);
      return { kind: "stale", changedBy: current?.last_changed_by?.name ?? null, current };
    }
    case 422: {
      const { detail } = problem(error);
      return {
        kind: "invalid",
        detail:
          detail && !detail.startsWith("Invalid fields:") ? detail : "The change was not accepted.",
      };
    }
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${action} failed: status=${status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

/** `PATCH /api/v1/opportunities/{id}/requirements/{rid}` with `If-Match`: a Requirement's
 * text and/or classification. Never retries or overwrites on 412. Logs ids and statuses
 * only. */
export async function editRequirement(input: unknown): Promise<RequirementWriteResult> {
  if (!isEditInput(input)) return { kind: "error" };
  const { opportunityId, requirementId, rowVersion, text, classification } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PATCH(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}",
      {
        params: {
          path: {
            opportunity_id: opportunityId,
            requirement_id: requirementId,
          },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: {
          ...(text !== undefined ? { text } : {}),
          ...(classification !== undefined ? { classification } : {}),
        },
      },
    );
    if (data) return { kind: "ok", requirement: data };
    return await requirementWriteFailure("edit requirement", input, response.status, error);
  } catch (thrown) {
    console.error(`edit requirement failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

export type RequirementTagInput = RequirementConfirmInput & {
  /** The whole new set of catalogue Integration Type ids (it replaces the current one). */
  integrationTypeIds: string[];
};

/** The most Integration Types one Requirement can carry (the API's limit). */
const INTEGRATION_TYPES_MAX = 50;

function isTagInput(input: unknown): input is RequirementTagInput {
  if (!isRowTarget(input)) return false;
  const { integrationTypeIds } = input as Record<string, unknown>;
  return (
    Array.isArray(integrationTypeIds) &&
    integrationTypeIds.length <= INTEGRATION_TYPES_MAX &&
    integrationTypeIds.every((id) => typeof id === "string" && UUID_RE.test(id))
  );
}

/** `PUT /api/v1/opportunities/{id}/requirements/{rid}/integration-types` with `If-Match`
 * (Story 4.1): replace the Requirement's Integration Type tags. Never retries or overwrites
 * on 412. Logs ids and statuses only. */
export async function tagRequirementIntegrationTypes(
  input: unknown,
): Promise<RequirementWriteResult> {
  if (!isTagInput(input)) return { kind: "error" };
  const { opportunityId, requirementId, rowVersion, integrationTypeIds } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PUT(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/integration-types",
      {
        params: {
          path: { opportunity_id: opportunityId, requirement_id: requirementId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: { integration_type_ids: integrationTypeIds },
      },
    );
    if (data) return { kind: "ok", requirement: data };
    return await requirementWriteFailure("tag requirement", input, response.status, error);
  } catch (thrown) {
    console.error(`tag requirement failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/requirements/{rid}/confirm` with `If-Match`. Confirming
 * one already confirmed is a no-op on the API. */
export async function confirmRequirement(input: unknown): Promise<RequirementWriteResult> {
  if (!isRowTarget(input)) return { kind: "error" };
  const { opportunityId, requirementId, rowVersion } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/confirm",
      {
        params: {
          path: {
            opportunity_id: opportunityId,
            requirement_id: requirementId,
          },
          header: { "If-Match": `"${rowVersion}"` },
        },
      },
    );
    if (data) return { kind: "ok", requirement: data };
    return await requirementWriteFailure("confirm requirement", input, response.status, error);
  } catch (thrown) {
    console.error(
      `confirm requirement failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/requirements/confirm-all`: confirm every Requirement not
 * confirmed yet. */
export async function confirmAllRequirements(opportunityId: unknown): Promise<ConfirmAllResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/requirements/confirm-all",
      { params: { path: { opportunity_id: opportunityId } } },
    );
    if (data) return { kind: "ok", count: data.count };
    switch (response.status) {
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `confirm all requirements failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `confirm all requirements failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

// --- shaping the Requirement list (Story 2.6) -------------------------------------------------

export type RequirementDraftInput = { text: string; classification: Classification };

export type RequirementCreateInput = RequirementDraftInput & { opportunityId: string };

/** A create or merge: the new Requirement, or why not. */
export type RequirementCreateResult = RequirementWriteResult;

export type RequirementDeleteInput = RequirementConfirmInput & {
  /** Why: 1 to 500 code points once trimmed (the API checks again). */
  reason: string;
};

export type RequirementDeleteResult = { kind: "ok" } | RequirementFailure;

export type RequirementSplitInput = RequirementConfirmInput & {
  parts: [RequirementDraftInput, RequirementDraftInput];
};

export type RequirementSplitResult =
  | { kind: "ok"; requirements: Requirement[] }
  | RequirementFailure;

export type RequirementMergeInput = RequirementDraftInput & {
  opportunityId: string;
  /** The Requirements to merge, each at the `row_version` last seen. */
  requirements: { id: string; rowVersion: number }[];
};

function isDraft(input: unknown): input is RequirementDraftInput {
  if (typeof input !== "object" || input === null) return false;
  const { text, classification } = input as Record<string, unknown>;
  return (
    typeof text === "string" &&
    typeof classification === "string" &&
    KNOWN_CLASSIFICATIONS.has(classification)
  );
}

function isId(value: unknown): value is string {
  return typeof value === "string" && UUID_RE.test(value);
}

function isMergeRef(value: unknown): value is { id: string; rowVersion: number } {
  if (typeof value !== "object" || value === null) return false;
  const { id, rowVersion } = value as Record<string, unknown>;
  return (
    isId(id) && typeof rowVersion === "number" && Number.isSafeInteger(rowVersion) && rowVersion >= 1
  );
}

/** A failure of a write that names no single Requirement (a create or merge): a 412 has no
 * one changer to name. */
function listWriteFailure(action: string, status: number, error: unknown): RequirementFailure {
  switch (status) {
    case 412:
      return { kind: "stale", changedBy: null, current: null };
    case 422: {
      const { detail } = problem(error);
      return {
        kind: "invalid",
        detail:
          detail && !detail.startsWith("Invalid fields:") ? detail : "The change was not accepted.",
      };
    }
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${action} failed: status=${status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

function thrownName(thrown: unknown): string {
  return thrown instanceof Error ? thrown.name : "unknown";
}

/** `POST /api/v1/opportunities/{id}/requirements`: add a Requirement the extraction missed
 * (`human`, locked, no Evidence). Logs ids and statuses only. */
export async function createRequirement(input: unknown): Promise<RequirementCreateResult> {
  if (!isDraft(input) || !isId((input as Record<string, unknown>).opportunityId)) {
    return { kind: "error" };
  }
  const { opportunityId, text, classification } = input as RequirementCreateInput;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/requirements",
      { params: { path: { opportunity_id: opportunityId } }, body: { text, classification } },
    );
    if (data) return { kind: "ok", requirement: data };
    return listWriteFailure("create requirement", response.status, error);
  } catch (thrown) {
    console.error(`create requirement failed: ${thrownName(thrown)}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/requirements/{rid}/delete` with `If-Match` and a
 * reason. Never retries or overwrites on 412. */
export async function deleteRequirement(input: unknown): Promise<RequirementDeleteResult> {
  if (!isRowTarget(input) || typeof (input as Record<string, unknown>).reason !== "string") {
    return { kind: "error" };
  }
  const { opportunityId, requirementId, rowVersion, reason } = input as RequirementDeleteInput;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/delete",
      {
        params: {
          path: { opportunity_id: opportunityId, requirement_id: requirementId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: { reason },
      },
    );
    if (data) return { kind: "ok" };
    return await requirementWriteFailure("delete requirement", input, response.status, error);
  } catch (thrown) {
    console.error(`delete requirement failed: ${thrownName(thrown)}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/requirements/{rid}/split` with `If-Match`: two new
 * Requirements, each citing all the original's Evidence. */
export async function splitRequirement(input: unknown): Promise<RequirementSplitResult> {
  if (!isRowTarget(input)) return { kind: "error" };
  const { parts } = input as Record<string, unknown>;
  if (!Array.isArray(parts) || parts.length !== 2 || !parts.every(isDraft)) {
    return { kind: "error" };
  }
  const { opportunityId, requirementId, rowVersion } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/split",
      {
        params: {
          path: { opportunity_id: opportunityId, requirement_id: requirementId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: { parts: parts.map(({ text, classification }) => ({ text, classification })) },
      },
    );
    if (data) return { kind: "ok", requirements: data.items };
    return await requirementWriteFailure("split requirement", input, response.status, error);
  } catch (thrown) {
    console.error(`split requirement failed: ${thrownName(thrown)}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/requirements/merge`: one new Requirement citing all the
 * merged ones' Evidence. Each Requirement goes with its `row_version` last seen; any stale
 * one fails the whole merge (412). */
export async function mergeRequirements(input: unknown): Promise<RequirementCreateResult> {
  if (!isDraft(input)) return { kind: "error" };
  const { opportunityId, requirements } = input as Record<string, unknown>;
  if (!isId(opportunityId) || !Array.isArray(requirements) || !requirements.every(isMergeRef)) {
    return { kind: "error" };
  }
  const { text, classification } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/requirements/merge",
      {
        params: { path: { opportunity_id: opportunityId } },
        body: {
          requirements: requirements.map((r) => ({ id: r.id, row_version: r.rowVersion })),
          text,
          classification,
        },
      },
    );
    if (data) return { kind: "ok", requirement: data };
    return listWriteFailure("merge requirements", response.status, error);
  } catch (thrown) {
    console.error(`merge requirements failed: ${thrownName(thrown)}`);
    return { kind: "error" };
  }
}

// --- pending Requirement changes (Story 2.7) --------------------------------------------------

export type RequirementRejectInput = RequirementConfirmInput & {
  /** Why: 1 to 500 code points once trimmed (the API checks again). */
  reason: string;
};

/** A write on a pending change: as a Requirement write, plus 409 when it has none (any
 * more), e.g. someone else decided it first. */
export type RequirementChangeResult = RequirementWriteResult | { kind: "no-change" };

function isRejectInput(input: unknown): input is RequirementRejectInput {
  return isRowTarget(input) && typeof (input as Record<string, unknown>).reason === "string";
}

/** `POST /api/v1/opportunities/{id}/requirements/{rid}/change/accept` (or `/reject` with a
 * reason) with `If-Match`. Never retries or overwrites on 412. Logs ids and statuses only. */
async function decideRequirementChange(
  input: RequirementConfirmInput,
  decision: { reason: string } | null,
): Promise<RequirementChangeResult> {
  const { opportunityId, requirementId, rowVersion } = input;
  const action = decision ? "reject requirement change" : "accept requirement change";
  try {
    const api = await createServerApiClient();
    const params = {
      path: { opportunity_id: opportunityId, requirement_id: requirementId },
      header: { "If-Match": `"${rowVersion}"` },
    };
    const { data, error, response } = decision
      ? await api.POST(
          "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/change/reject",
          { params, body: { reason: decision.reason } },
        )
      : await api.POST(
          "/api/v1/opportunities/{opportunity_id}/requirements/{requirement_id}/change/accept",
          { params },
        );
    if (data) return { kind: "ok", requirement: data };
    if (response.status === 409) return { kind: "no-change" };
    return await requirementWriteFailure(action, input, response.status, error);
  } catch (thrown) {
    console.error(`${action} failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** Accept a Requirement's pending change: its text and classification become the next
 * version. */
export async function acceptRequirementChange(input: unknown): Promise<RequirementChangeResult> {
  if (!isRowTarget(input)) return { kind: "error" };
  return decideRequirementChange(input, null);
}

/** Reject a Requirement's pending change with a reason; the Requirement stays as it is. */
export async function rejectRequirementChange(input: unknown): Promise<RequirementChangeResult> {
  if (!isRejectInput(input)) return { kind: "error" };
  return decideRequirementChange(input, { reason: input.reason });
}

/** The current Assessments that used Requirement versions that have changed since (the
 * Requirements tab's notice). */
export async function loadOutdatedAssessments(
  opportunityId: unknown,
): Promise<OutdatedAssessmentsResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  return listOutdatedAssessments(opportunityId);
}

// --- editing and approving Clarification Questions (Story 4.5) -------------------------------

export type QuestionEditInput = {
  opportunityId: string;
  questionId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
  text?: string;
  topic?: string;
};

export type QuestionApproveInput = {
  opportunityId: string;
  questionId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
};

export type QuestionWriteResult =
  | { kind: "ok"; question: ClarificationQuestion }
  /** 412: someone changed the question first. `changedBy` is null when unknown. */
  | { kind: "stale"; changedBy: string | null }
  /** 422: a readable reason. */
  | { kind: "invalid"; detail: string }
  /** 409 `gap_not_open`: the Gap was dismissed, converted or replaced; nothing changed. */
  | { kind: "gap-not-open" }
  /** 409 `question_not_editable`: the question was sent (Story 4.6); nothing changed. */
  | { kind: "question-not-editable" }
  /** 409 `question_not_sent`: "No answer" on a question that isn't sent; nothing changed. */
  | { kind: "question-not-sent" }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the question is gone. */
  | { kind: "not-found" }
  | { kind: "error" };

export type ApproveAllQuestionsResult =
  | { kind: "ok"; count: number }
  /** 412: a shown question changed, or the drafted set differs; nothing was approved. */
  | { kind: "stale"; changedBy: string | null }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

function isQuestionTarget(input: unknown): input is QuestionApproveInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, questionId, rowVersion } = input as Record<string, unknown>;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof questionId === "string" &&
    UUID_RE.test(questionId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0
  );
}

function isQuestionEdit(input: unknown): input is QuestionEditInput {
  if (!isQuestionTarget(input)) return false;
  const { text, topic } = input as Record<string, unknown>;
  return (
    (text === undefined || typeof text === "string") &&
    (topic === undefined || typeof topic === "string") &&
    (text !== undefined || topic !== undefined)
  );
}

/** Who last changed the question, read again after a 412 (null when unknown). */
async function questionChanger(opportunityId: string, questionId: string): Promise<string | null> {
  const current = await listGaps(opportunityId);
  if (current.kind !== "ok") return null;
  return (
    current.list.items.find((g) => g.question?.id === questionId)?.question?.last_changed_by
      ?.name ?? null
  );
}

async function questionWriteFailure(
  action: string,
  input: QuestionApproveInput,
  status: number,
  error: unknown,
): Promise<QuestionWriteResult> {
  switch (status) {
    case 412:
      return {
        kind: "stale",
        changedBy: await questionChanger(input.opportunityId, input.questionId),
      };
    case 422: {
      const { detail } = problem(error);
      return {
        kind: "invalid",
        detail:
          detail && !detail.startsWith("Invalid fields:") ? detail : "The change was not accepted.",
      };
    }
    case 409: {
      const { code } = problem(error);
      if (code === "question_not_editable") return { kind: "question-not-editable" };
      if (code === "question_not_sent") return { kind: "question-not-sent" };
      return { kind: "gap-not-open" };
    }
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${action} failed: status=${status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

/** `PATCH /api/v1/opportunities/{id}/clarification-questions/{qid}` with `If-Match`: a
 * question's text and/or topic. Never retries or overwrites on 412. Logs ids and statuses
 * only. */
export async function editClarificationQuestion(input: unknown): Promise<QuestionWriteResult> {
  if (!isQuestionEdit(input)) return { kind: "error" };
  const { opportunityId, questionId, rowVersion, text, topic } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PATCH(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}",
      {
        params: {
          path: { opportunity_id: opportunityId, question_id: questionId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: {
          ...(text !== undefined ? { text } : {}),
          ...(topic !== undefined ? { topic } : {}),
        },
      },
    );
    if (data) return { kind: "ok", question: data };
    return await questionWriteFailure("edit question", input, response.status, error);
  } catch (thrown) {
    console.error(`edit question failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/clarification-questions/{qid}/approve` with `If-Match`.
 * Approving one already approved is a no-op on the API. */
export async function approveClarificationQuestion(input: unknown): Promise<QuestionWriteResult> {
  if (!isQuestionTarget(input)) return { kind: "error" };
  const { opportunityId, questionId, rowVersion } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}/approve",
      {
        params: {
          path: { opportunity_id: opportunityId, question_id: questionId },
          header: { "If-Match": `"${rowVersion}"` },
        },
      },
    );
    if (data) return { kind: "ok", question: data };
    return await questionWriteFailure("approve question", input, response.status, error);
  } catch (thrown) {
    console.error(`approve question failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** A drafted question as the Gaps tab shows it, for **Approve all**. */
export type ShownQuestion = { id: string; row_version: number };

function isShownList(input: unknown): input is ShownQuestion[] {
  return (
    Array.isArray(input) &&
    input.every(
      (q) =>
        typeof q === "object" &&
        q !== null &&
        typeof (q as Record<string, unknown>).id === "string" &&
        UUID_RE.test((q as Record<string, unknown>).id as string) &&
        typeof (q as Record<string, unknown>).row_version === "number" &&
        Number.isSafeInteger((q as Record<string, unknown>).row_version) &&
        ((q as Record<string, unknown>).row_version as number) >= 0,
    )
  );
}

/** Who changed one of the shown questions, read again after a 412 (null when unknown). */
async function shownChanger(opportunityId: string, shown: ShownQuestion[]): Promise<string | null> {
  const current = await listGaps(opportunityId);
  if (current.kind !== "ok") return null;
  const versions = new Map(shown.map((q) => [q.id, q.row_version]));
  for (const gap of current.list.items) {
    const question = gap.question;
    if (!question) continue;
    const seen = versions.get(question.id);
    const changed =
      seen === undefined ? question.status === "drafted" : seen !== question.row_version;
    if (changed && question.last_changed_by) return question.last_changed_by.name;
  }
  return null;
}

/** `POST /api/v1/opportunities/{id}/clarification-questions/approve-all` with the drafted
 * questions the tab shows (`[{id, row_version}]`): approves exactly those, all or nothing.
 * A 412 (one changed, or the set differs) approves nothing. */
export async function approveAllClarificationQuestions(
  opportunityId: unknown,
  shown: unknown,
): Promise<ApproveAllQuestionsResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId) || !isShownList(shown))
    return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/approve-all",
      {
        params: { path: { opportunity_id: opportunityId } },
        body: shown.map(({ id, row_version }) => ({ id, row_version })),
      },
    );
    if (data) return { kind: "ok", count: data.count };
    switch (response.status) {
      case 412:
        return { kind: "stale", changedBy: await shownChanger(opportunityId, shown) };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `approve all questions failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `approve all questions failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/clarification-questions/approve-selected` with the
 * selected drafted questions (`[{id, row_version}]`, 1 to 200): approves exactly those, all
 * or nothing (Story 4.4). A 412 (one changed, isn't drafted or isn't on an open Gap) approves
 * nothing. */
export async function approveSelectedClarificationQuestions(
  opportunityId: unknown,
  selected: unknown,
): Promise<ApproveAllQuestionsResult> {
  if (
    typeof opportunityId !== "string" ||
    !UUID_RE.test(opportunityId) ||
    !isShownList(selected) ||
    selected.length < 1 ||
    selected.length > 200
  )
    return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/approve-selected",
      {
        params: { path: { opportunity_id: opportunityId } },
        body: selected.map(({ id, row_version }) => ({ id, row_version })),
      },
    );
    if (data) return { kind: "ok", count: data.count };
    switch (response.status) {
      case 412:
        return { kind: "stale", changedBy: await shownChanger(opportunityId, selected) };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `approve selected questions failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `approve selected questions failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

// --- exporting and sending Clarification Questions (Story 4.6) --------------------------------

export type CopyQuestionsResult =
  | { kind: "ok"; text: string; count: number }
  /** 409 `no_approved_questions`: nothing to export. */
  | { kind: "nothing-approved" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

/** `POST /api/v1/opportunities/{id}/clarification-questions/export` as `copy`: the approved
 * questions as plain text, grouped by topic, in customer wording only. Logs statuses only,
 * never the text. */
export async function copyClarificationQuestions(
  opportunityId: unknown,
): Promise<CopyQuestionsResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/export",
      { params: { path: { opportunity_id: opportunityId } }, body: { format: "copy" } },
    );
    if (data && typeof data.text === "string") {
      return { kind: "ok", text: data.text, count: data.question_count };
    }
    switch (response.status) {
      case 409:
        return { kind: "nothing-approved" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `copy questions failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(`copy questions failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

export type MarkSentResult =
  | { kind: "ok"; count: number }
  /** 412: a listed question changed, isn't approved or isn't on an open Gap; nothing marked. */
  | { kind: "stale"; changedBy: string | null }
  /** 422: e.g. a date in the future. */
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

/** Who changed one of the listed approved questions, read again after a 412 (null when
 * unknown). */
async function sentChanger(opportunityId: string, listed: ShownQuestion[]): Promise<string | null> {
  const current = await listGaps(opportunityId);
  if (current.kind !== "ok") return null;
  const versions = new Map(listed.map((q) => [q.id, q.row_version]));
  for (const gap of current.list.items) {
    const question = gap.question;
    if (!question || !versions.has(question.id)) continue;
    if (versions.get(question.id) !== question.row_version && question.last_changed_by) {
      return question.last_changed_by.name;
    }
  }
  return null;
}

/** `POST /api/v1/opportunities/{id}/clarification-questions/mark-sent` with the date sent and
 * the approved questions the tab shows (`[{id, row_version}]`, 1 to 200): marks exactly those,
 * all or nothing. A 412 marks nothing. */
export async function markClarificationQuestionsSent(
  opportunityId: unknown,
  sentOn: unknown,
  questions: unknown,
): Promise<MarkSentResult> {
  if (
    typeof opportunityId !== "string" ||
    !UUID_RE.test(opportunityId) ||
    typeof sentOn !== "string" ||
    !DATE_RE.test(sentOn) ||
    !isShownList(questions) ||
    questions.length < 1 ||
    questions.length > 200
  )
    return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/mark-sent",
      {
        params: { path: { opportunity_id: opportunityId } },
        body: {
          sent_on: sentOn,
          questions: questions.map(({ id, row_version }) => ({ id, row_version })),
        },
      },
    );
    if (data) return { kind: "ok", count: data.count };
    switch (response.status) {
      case 412:
        return { kind: "stale", changedBy: await sentChanger(opportunityId, questions) };
      case 422: {
        const { detail } = problem(error);
        return {
          kind: "invalid",
          detail:
            detail && !detail.startsWith("Invalid fields:")
              ? detail
              : "The date or the questions were not accepted.",
        };
      }
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `mark questions sent failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `mark questions sent failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/clarification-questions/{qid}/no-answer` with `If-Match`:
 * the customer won't answer the sent question. Never retries or overwrites on 412. */
export async function markClarificationQuestionUnanswered(
  input: unknown,
): Promise<QuestionWriteResult> {
  if (!isQuestionTarget(input)) return { kind: "error" };
  const { opportunityId, questionId, rowVersion } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}/no-answer",
      {
        params: {
          path: { opportunity_id: opportunityId, question_id: questionId },
          header: { "If-Match": `"${rowVersion}"` },
        },
      },
    );
    if (data) return { kind: "ok", question: data };
    return await questionWriteFailure("mark question unanswered", input, response.status, error);
  } catch (thrown) {
    console.error(
      `mark question unanswered failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

// --- changing impact, dismissing and reopening Gaps (Story 4.4) ------------------------------

export type GapTarget = {
  opportunityId: string;
  gapId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
};

export type GapWriteResult =
  | { kind: "ok"; gap: Gap }
  /** 412: someone changed the Gap first. `changedBy` is null when unknown. */
  | { kind: "stale"; changedBy: string | null }
  /** 422: a readable reason. */
  | { kind: "invalid"; detail: string }
  /** 409 `gap_not_open`: the Gap was dismissed, converted or replaced; nothing changed. */
  | { kind: "gap-not-open" }
  /** 409 `gap_not_reopenable`: the Gap is neither dismissed nor answered (reopened meanwhile). */
  | { kind: "gap-not-reopenable" }
  /** 409 `gap_mandatory` (Story 4.2): a mandatory Gap whose Checklist still applies. */
  | { kind: "gap-mandatory" }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the Gap is gone. */
  | { kind: "not-found" }
  | { kind: "error" };

function isGapTarget(input: unknown): input is GapTarget {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, gapId, rowVersion } = input as Record<string, unknown>;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof gapId === "string" &&
    UUID_RE.test(gapId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0
  );
}

/** Who last changed the Gap, read again after a 412 (null when unknown). */
async function gapChanger(opportunityId: string, gapId: string): Promise<string | null> {
  const current = await listGaps(opportunityId);
  if (current.kind !== "ok") return null;
  return current.list.items.find((g) => g.id === gapId)?.last_changed_by?.name ?? null;
}

async function gapWriteFailure(
  action: string,
  input: GapTarget,
  status: number,
  error: unknown,
): Promise<GapWriteResult> {
  switch (status) {
    case 412:
      return { kind: "stale", changedBy: await gapChanger(input.opportunityId, input.gapId) };
    case 422: {
      const { detail } = problem(error);
      return {
        kind: "invalid",
        detail:
          detail && !detail.startsWith("Invalid fields:") ? detail : "The change was not accepted.",
      };
    }
    case 409: {
      const { code } = problem(error);
      if (code === "gap_not_reopenable") return { kind: "gap-not-reopenable" };
      if (code === "gap_mandatory") return { kind: "gap-mandatory" };
      return { kind: "gap-not-open" };
    }
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${action} failed: status=${status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

const IMPACT_VALUES: readonly string[] = ["high", "medium", "low"];

/** `PATCH /api/v1/opportunities/{id}/gaps/{gid}/impact` with `If-Match`: an open Gap's
 * impact, with a reason. Never retries or overwrites on 412. Logs ids and statuses only,
 * never the reason. */
export async function changeGapImpact(input: unknown): Promise<GapWriteResult> {
  if (!isGapTarget(input)) return { kind: "error" };
  const { impact, reason } = input as Record<string, unknown>;
  if (typeof impact !== "string" || !IMPACT_VALUES.includes(impact) || typeof reason !== "string")
    return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PATCH(
      "/api/v1/opportunities/{opportunity_id}/gaps/{gap_id}/impact",
      {
        params: {
          path: { opportunity_id: input.opportunityId, gap_id: input.gapId },
          header: { "If-Match": `"${input.rowVersion}"` },
        },
        body: { impact: impact as Gap["impact"], reason },
      },
    );
    if (data) return { kind: "ok", gap: data };
    return await gapWriteFailure("change impact", input, response.status, error);
  } catch (thrown) {
    console.error(`change impact failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/gaps/{gid}/dismiss` with `If-Match`: dismiss an open Gap
 * as `not_relevant` (note optional) or `other` (note required). */
export async function dismissGap(input: unknown): Promise<GapWriteResult> {
  if (!isGapTarget(input)) return { kind: "error" };
  const { reasonKind, note } = input as Record<string, unknown>;
  if (
    (reasonKind !== "not_relevant" && reasonKind !== "other") ||
    (note !== undefined && typeof note !== "string")
  )
    return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/gaps/{gap_id}/dismiss",
      {
        params: {
          path: { opportunity_id: input.opportunityId, gap_id: input.gapId },
          header: { "If-Match": `"${input.rowVersion}"` },
        },
        body: { reason_kind: reasonKind, ...(note ? { note } : {}) },
      },
    );
    if (data) return { kind: "ok", gap: data };
    return await gapWriteFailure("dismiss gap", input, response.status, error);
  } catch (thrown) {
    console.error(`dismiss gap failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/gaps/{gid}/reopen` with `If-Match`: reopen a dismissed or answered
 * Gap, with a reason. */
export async function reopenGap(input: unknown): Promise<GapWriteResult> {
  if (!isGapTarget(input)) return { kind: "error" };
  const { reason } = input as Record<string, unknown>;
  if (typeof reason !== "string") return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/gaps/{gap_id}/reopen",
      {
        params: {
          path: { opportunity_id: input.opportunityId, gap_id: input.gapId },
          header: { "If-Match": `"${input.rowVersion}"` },
        },
        body: { reason },
      },
    );
    if (data) return { kind: "ok", gap: data };
    return await gapWriteFailure("reopen gap", input, response.status, error);
  } catch (thrown) {
    console.error(`reopen gap failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

// --- answering Clarification Questions (Story 4.7) -------------------------------------------

export type AnswerWriteResult =
  | { kind: "ok"; gap: Gap }
  /** 412: the question or suggestion changed first. */
  | { kind: "stale" }
  /** 422: a readable reason. */
  | { kind: "invalid"; detail: string }
  /** 409 `gap_not_open`: the Gap was dismissed, converted or replaced; nothing changed. */
  | { kind: "gap-not-open" }
  /** 409 `question_not_sent`: the question is no longer sent or "No answer"; nothing changed. */
  | { kind: "question-not-sent" }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the question or suggestion is gone. */
  | { kind: "not-found" }
  | { kind: "error" };

function answerWriteFailure(action: string, status: number, error: unknown): AnswerWriteResult {
  switch (status) {
    case 412:
      return { kind: "stale" };
    case 422: {
      const { detail } = problem(error);
      return {
        kind: "invalid",
        detail:
          detail && !detail.startsWith("Invalid fields:") ? detail : "The answer was not accepted.",
      };
    }
    case 409:
      return problem(error).code === "question_not_sent"
        ? { kind: "question-not-sent" }
        : { kind: "gap-not-open" };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${action} failed: status=${status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/clarification-questions/{qid}/answer` with `If-Match`:
 * **Record answer**. The text becomes a Source; the question is answered, and the Gap too when
 * `settlesGap`. Logs ids and statuses only, never the answer. */
export async function recordAnswer(input: unknown): Promise<AnswerWriteResult> {
  if (!isQuestionTarget(input)) return { kind: "error" };
  const { text, answeredOn, settlesGap } = input as Record<string, unknown>;
  if (
    typeof text !== "string" ||
    typeof answeredOn !== "string" ||
    !/^\d{4}-\d{2}-\d{2}$/.test(answeredOn) ||
    typeof settlesGap !== "boolean"
  )
    return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/{question_id}/answer",
      {
        params: {
          path: { opportunity_id: input.opportunityId, question_id: input.questionId },
          header: { "If-Match": `"${input.rowVersion}"` },
        },
        body: { text, answered_on: answeredOn, settles_gap: settlesGap },
      },
    );
    if (data) return { kind: "ok", gap: data };
    return answerWriteFailure("record answer", response.status, error);
  } catch (thrown) {
    console.error(`record answer failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

export type AnswerMatchInput = {
  opportunityId: string;
  matchId: string;
  /** The suggestion's `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
};

function isMatchTarget(input: unknown): input is AnswerMatchInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, matchId, rowVersion } = input as Record<string, unknown>;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof matchId === "string" &&
    UUID_RE.test(matchId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0
  );
}

async function decideMatch(
  input: unknown,
  decision: "confirm" | "reject",
): Promise<AnswerWriteResult> {
  if (!isMatchTarget(input)) return { kind: "error" };
  const action = decision === "confirm" ? "confirm answer" : "reject answer";
  try {
    const api = await createServerApiClient();
    const options = {
      params: {
        path: { opportunity_id: input.opportunityId, match_id: input.matchId },
        header: { "If-Match": `"${input.rowVersion}"` },
      },
    };
    const { data, error, response } =
      decision === "confirm"
        ? await api.POST(
            "/api/v1/opportunities/{opportunity_id}/answer-matches/{match_id}/confirm",
            options,
          )
        : await api.POST(
            "/api/v1/opportunities/{opportunity_id}/answer-matches/{match_id}/reject",
            options,
          );
    if (data) return { kind: "ok", gap: data };
    return answerWriteFailure(action, response.status, error);
  } catch (thrown) {
    console.error(`${action} failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST …/answer-matches/{mid}/confirm` with `If-Match`: the suggested passage answers the
 * question, which settles its Gap. */
export async function confirmAnswerMatch(input: unknown): Promise<AnswerWriteResult> {
  return decideMatch(input, "confirm");
}

/** `POST …/answer-matches/{mid}/reject` with `If-Match`: **Not an answer**. */
export async function rejectAnswerMatch(input: unknown): Promise<AnswerWriteResult> {
  return decideMatch(input, "reject");
}

// --- accepting Assumptions (Story 8.4 + 8.5) -------------------------------------------------

export type AssumptionAcceptInput = {
  opportunityId: string;
  assumptionId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
};

export type AssumptionAcceptResult =
  | { kind: "ok"; assumption: Assumption }
  /** 412: someone changed the Assumption first. `changedBy` is null when unknown. */
  | { kind: "stale"; changedBy: string | null }
  /** 409 `gap_not_open`: the Gap was dismissed, converted or replaced; nothing changed. */
  | { kind: "gap-not-open" }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the Assumption isn't in the current draft. */
  | { kind: "not-found" }
  | { kind: "error" };

export type AcceptAllAssumptionsResult =
  | { kind: "ok"; count: number }
  | { kind: "gap-not-open" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

function isAcceptInput(input: unknown): input is AssumptionAcceptInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, assumptionId, rowVersion } = input as Record<
    string,
    unknown
  >;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof assumptionId === "string" &&
    UUID_RE.test(assumptionId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0
  );
}

/** Who accepted the Assumption, read again after a 412 (null when unknown). */
async function assumptionChanger(
  opportunityId: string,
  assumptionId: string,
): Promise<string | null> {
  const current = await getEstimate(opportunityId);
  if (current.kind !== "ok" || !current.estimate.version) return null;
  const { conditions, contingencies } = current.estimate.version.assumptions;
  return (
    [...conditions, ...contingencies].find((a) => a.id === assumptionId)
      ?.accepted_by?.name ?? null
  );
}

/** `POST /api/v1/opportunities/{id}/assumptions/{aid}/accept` with `If-Match`: accept one
 * Assumption as the signed-in user. Never retries or overwrites on 412. Logs ids and statuses
 * only. */
export async function acceptAssumption(
  input: unknown,
): Promise<AssumptionAcceptResult> {
  if (!isAcceptInput(input)) return { kind: "error" };
  const { opportunityId, assumptionId, rowVersion } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/assumptions/{assumption_id}/accept",
      {
        params: {
          path: { opportunity_id: opportunityId, assumption_id: assumptionId },
          header: { "If-Match": `"${rowVersion}"` },
        },
      },
    );
    if (data) return { kind: "ok", assumption: data };
    switch (response.status) {
      case 412:
        return {
          kind: "stale",
          changedBy: await assumptionChanger(opportunityId, assumptionId),
        };
      case 409:
        return { kind: "gap-not-open" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `accept assumption failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `accept assumption failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/assumptions/accept-all`: accept every Assumption of the
 * current draft not accepted yet, as the signed-in user. All or nothing on the API. */
export async function acceptAllAssumptions(
  opportunityId: unknown,
): Promise<AcceptAllAssumptionsResult> {
  if (typeof opportunityId !== "string" || !UUID_RE.test(opportunityId))
    return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/assumptions/accept-all",
      { params: { path: { opportunity_id: opportunityId } } },
    );
    if (data) return { kind: "ok", count: data.count };
    switch (response.status) {
      case 409:
        return { kind: "gap-not-open" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `accept all assumptions failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `accept all assumptions failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

// --- editing an Estimate line (Story 8.2) ---------------------------------------------------

export type EstimateLineEditInput = {
  opportunityId: string;
  lineId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
  effortHours?: number;
  roleMix?: RoleMix;
  reason: string;
};

export type EstimateLineEditResult =
  /** The whole Estimate as it is now, every total recalculated by the server. */
  | { kind: "ok"; estimate: EstimateView }
  /** 412: someone changed the line first; `message` is the API's "Changed by {name} since you
   * opened it." */
  | { kind: "stale"; message: string }
  /** 422: a readable reason. */
  | { kind: "invalid"; detail: string }
  /** 409 `estimate_version_not_draft`: a re-draft replaced the version. */
  | { kind: "not-draft" }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the line is gone. */
  | { kind: "not-found" }
  | { kind: "error" };

const ROLE_KEYS = ["engineer", "project_manager", "qa"] as const;

function isRoleMix(value: unknown): value is RoleMix {
  if (typeof value !== "object" || value === null) return false;
  const mix = value as Record<string, unknown>;
  return (
    Object.keys(mix).length === ROLE_KEYS.length &&
    ROLE_KEYS.every((key) => typeof mix[key] === "number" && Number.isFinite(mix[key]))
  );
}

function isLineEditInput(input: unknown): input is EstimateLineEditInput {
  if (typeof input !== "object" || input === null) return false;
  const { opportunityId, lineId, rowVersion, effortHours, roleMix, reason } = input as Record<
    string,
    unknown
  >;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof lineId === "string" &&
    UUID_RE.test(lineId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0 &&
    (effortHours === undefined ||
      (typeof effortHours === "number" && Number.isFinite(effortHours))) &&
    (roleMix === undefined || isRoleMix(roleMix)) &&
    (effortHours !== undefined || roleMix !== undefined) &&
    typeof reason === "string"
  );
}

/** `PATCH /api/v1/opportunities/{id}/estimate-lines/{lid}` with `If-Match`: a draft line's
 * effort hours and/or role mix, with a reason. Never retries or overwrites on 412. Logs ids
 * and statuses only (never the reason). */
export async function editEstimateLine(input: unknown): Promise<EstimateLineEditResult> {
  if (!isLineEditInput(input)) return { kind: "error" };
  const { opportunityId, lineId, rowVersion, effortHours, roleMix, reason } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PATCH(
      "/api/v1/opportunities/{opportunity_id}/estimate-lines/{line_id}",
      {
        params: {
          path: { opportunity_id: opportunityId, line_id: lineId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: {
          ...(effortHours !== undefined ? { effort_hours: effortHours } : {}),
          ...(roleMix !== undefined ? { role_mix: { ...roleMix } } : {}),
          reason,
        },
      },
    );
    if (data) return { kind: "ok", estimate: data };
    switch (response.status) {
      case 412:
        return {
          kind: "stale",
          message: problem(error).detail ?? "Changed by someone else since you opened it.",
        };
      case 422: {
        const { detail } = problem(error);
        return {
          kind: "invalid",
          detail:
            detail && !detail.startsWith("Invalid fields:")
              ? detail
              : "The change was not accepted.",
        };
      }
      case 409:
        return { kind: "not-draft" };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `edit estimate line failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `edit estimate line failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

// --- editing Assumptions and Risks (Story 8.5) ----------------------------------------------

export type AssumptionEditInput = {
  opportunityId: string;
  assumptionId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
  kind: AssumptionKind;
  wording: string;
  /** Null for a Condition. */
  amountHours: number | null;
  /** Null for a Condition, or a Contingency with no line (Unallocated). */
  lineId: string | null;
  reason: string;
};

/** What saving an edit of an Assumption or a Risk came to. */
export type EstimateItemEditResult =
  /** The whole Estimate as it is now, every total recalculated by the server. */
  | { kind: "ok"; estimate: EstimateView }
  /** 412: someone changed it first; `message` is the API's "Changed by {name} since you opened
   * it." */
  | { kind: "stale"; message: string }
  /** 422: the rule it broke, as a sentence. */
  | { kind: "invalid"; detail: string }
  /** 409 `estimate_version_not_draft`: the version is not the draft any more. */
  | { kind: "not-draft" }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the item is gone. */
  | { kind: "not-found" }
  | { kind: "error" };

const ASSUMPTION_KINDS: readonly string[] = ["condition", "contingency"];
const RISK_LEVEL_VALUES: readonly string[] = ["low", "medium", "high"];

function isRowVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function isAssumptionEditInput(input: unknown): input is AssumptionEditInput {
  if (typeof input !== "object" || input === null) return false;
  const i = input as Record<string, unknown>;
  return (
    typeof i.opportunityId === "string" &&
    UUID_RE.test(i.opportunityId) &&
    typeof i.assumptionId === "string" &&
    UUID_RE.test(i.assumptionId) &&
    isRowVersion(i.rowVersion) &&
    typeof i.kind === "string" &&
    ASSUMPTION_KINDS.includes(i.kind) &&
    typeof i.wording === "string" &&
    (i.amountHours === null ||
      (typeof i.amountHours === "number" && Number.isFinite(i.amountHours))) &&
    (i.lineId === null || (typeof i.lineId === "string" && UUID_RE.test(i.lineId))) &&
    typeof i.reason === "string"
  );
}

/** The result of a failed edit, by status. */
function itemEditFailure(
  status: number,
  error: unknown,
  what: string,
): Exclude<EstimateItemEditResult, { kind: "ok" }> {
  switch (status) {
    case 412:
      return {
        kind: "stale",
        message: problem(error).detail ?? "Changed by someone else since you opened it.",
      };
    case 422: {
      const { detail } = problem(error);
      return {
        kind: "invalid",
        detail:
          detail && !detail.startsWith("Invalid fields:") ? detail : "The change was not accepted.",
      };
    }
    case 409:
      return { kind: "not-draft" };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${what} failed: status=${status} code=${String(problem(error).code)}`);
      return { kind: "error" };
  }
}

/** `PATCH /api/v1/opportunities/{id}/assumptions/{aid}` with `If-Match`: an Assumption's kind,
 * wording, hours and line, with a reason; saving clears its acceptance. Never retries or
 * overwrites on 412. Logs ids and statuses only (never the wording or the reason). */
export async function editAssumption(input: unknown): Promise<EstimateItemEditResult> {
  if (!isAssumptionEditInput(input)) return { kind: "error" };
  const { opportunityId, assumptionId, rowVersion, kind, wording, amountHours, lineId, reason } =
    input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PATCH(
      "/api/v1/opportunities/{opportunity_id}/assumptions/{assumption_id}",
      {
        params: {
          path: { opportunity_id: opportunityId, assumption_id: assumptionId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: { kind, wording, amount_hours: amountHours, line_id: lineId, reason },
      },
    );
    if (data) return { kind: "ok", estimate: data };
    return itemEditFailure(response.status, error, "edit assumption");
  } catch (thrown) {
    console.error(`edit assumption failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

export type RiskConvertInput = {
  opportunityId: string;
  gapId: string;
  description: string;
  likelihood: RiskLevel;
  impact: RiskLevel;
};

export type RiskConvertResult =
  | { kind: "ok"; risk: Risk }
  /** 409 `gap_not_open`: the Gap was converted, dismissed, answered or replaced. */
  | { kind: "gap-not-open" }
  /** 409 `no_draft_estimate`: there is no draft Estimate to add the Risk to. */
  | { kind: "no-draft" }
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

function isRiskConvertInput(input: unknown): input is RiskConvertInput {
  if (typeof input !== "object" || input === null) return false;
  const i = input as Record<string, unknown>;
  return (
    typeof i.opportunityId === "string" &&
    UUID_RE.test(i.opportunityId) &&
    typeof i.gapId === "string" &&
    UUID_RE.test(i.gapId) &&
    typeof i.description === "string" &&
    typeof i.likelihood === "string" &&
    RISK_LEVEL_VALUES.includes(i.likelihood) &&
    typeof i.impact === "string" &&
    RISK_LEVEL_VALUES.includes(i.impact)
  );
}

/** `POST /api/v1/opportunities/{id}/risks`: convert an open Gap to a Risk of the draft
 * Estimate. Logs ids and statuses only (never the description). */
export async function convertGapToRisk(input: unknown): Promise<RiskConvertResult> {
  if (!isRiskConvertInput(input)) return { kind: "error" };
  const { opportunityId, gapId, description, likelihood, impact } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST("/api/v1/opportunities/{opportunity_id}/risks", {
      params: { path: { opportunity_id: opportunityId } },
      body: { gap_id: gapId, description, likelihood, impact },
    });
    if (data) return { kind: "ok", risk: data };
    const { code, detail } = problem(error);
    switch (response.status) {
      case 409:
        return code === "no_draft_estimate" ? { kind: "no-draft" } : { kind: "gap-not-open" };
      case 422:
        return {
          kind: "invalid",
          detail:
            detail && !detail.startsWith("Invalid fields:") ? detail : "The Risk was not accepted.",
        };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(`convert gap to risk failed: status=${response.status} code=${String(code)}`);
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(
      `convert gap to risk failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

export type RiskEditInput = {
  opportunityId: string;
  riskId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
  description: string;
  likelihood: RiskLevel;
  impact: RiskLevel;
  reason: string;
};

function isRiskEditInput(input: unknown): input is RiskEditInput {
  if (typeof input !== "object" || input === null) return false;
  const i = input as Record<string, unknown>;
  return (
    typeof i.opportunityId === "string" &&
    UUID_RE.test(i.opportunityId) &&
    typeof i.riskId === "string" &&
    UUID_RE.test(i.riskId) &&
    isRowVersion(i.rowVersion) &&
    typeof i.description === "string" &&
    typeof i.likelihood === "string" &&
    RISK_LEVEL_VALUES.includes(i.likelihood) &&
    typeof i.impact === "string" &&
    RISK_LEVEL_VALUES.includes(i.impact) &&
    typeof i.reason === "string"
  );
}

/** `PATCH /api/v1/opportunities/{id}/risks/{rid}` with `If-Match`: a Risk's description,
 * likelihood and impact, with a reason. Never retries or overwrites on 412. */
export async function editRisk(input: unknown): Promise<EstimateItemEditResult> {
  if (!isRiskEditInput(input)) return { kind: "error" };
  const { opportunityId, riskId, rowVersion, description, likelihood, impact, reason } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.PATCH(
      "/api/v1/opportunities/{opportunity_id}/risks/{risk_id}",
      {
        params: {
          path: { opportunity_id: opportunityId, risk_id: riskId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: { description, likelihood, impact, reason },
      },
    );
    if (data) return { kind: "ok", estimate: data };
    return itemEditFailure(response.status, error, "edit risk");
  } catch (thrown) {
    console.error(`edit risk failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

// --- resolving and escalating a Conflict (Story 6.3) ----------------------------------------

export type ConflictChoice = { position: number } | { entered: string };

export type ResolveConflictInput = {
  opportunityId: string;
  conflictId: string;
  /** The `row_version` last seen; sent as `If-Match`. */
  rowVersion: number;
  choice: ConflictChoice;
  reason: string;
};

export type EscalateConflictInput = {
  opportunityId: string;
  conflictId: string;
  rowVersion: number;
  reviewerId: string;
  reason: string;
};

export type ConflictDecisionResult =
  /** The Conflict as it is now. */
  | { kind: "ok"; conflict: Conflict }
  /** 412: someone changed it first; `message` is the API's "Changed by {name} since you
   * opened it." */
  | { kind: "stale"; message: string }
  /** 422: a readable reason. */
  | { kind: "invalid"; detail: string }
  /** 409: already resolved, or already escalated. */
  | { kind: "conflict"; detail: string }
  | { kind: "forbidden" }
  /** 404: the Opportunity can't be read, or the Conflict is gone. */
  | { kind: "not-found" }
  | { kind: "error" };

function isChoice(value: unknown): value is ConflictChoice {
  if (typeof value !== "object" || value === null) return false;
  const choice = value as Record<string, unknown>;
  if ("position" in choice) {
    return (
      typeof choice.position === "number" &&
      Number.isSafeInteger(choice.position) &&
      choice.position >= 1
    );
  }
  return typeof choice.entered === "string";
}

function isDecisionBase(input: Record<string, unknown>): boolean {
  const { opportunityId, conflictId, rowVersion, reason } = input;
  return (
    typeof opportunityId === "string" &&
    UUID_RE.test(opportunityId) &&
    typeof conflictId === "string" &&
    UUID_RE.test(conflictId) &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0 &&
    typeof reason === "string"
  );
}

function isResolveInput(input: unknown): input is ResolveConflictInput {
  if (typeof input !== "object" || input === null) return false;
  const record = input as Record<string, unknown>;
  return isDecisionBase(record) && isChoice(record.choice);
}

function isEscalateInput(input: unknown): input is EscalateConflictInput {
  if (typeof input !== "object" || input === null) return false;
  const record = input as Record<string, unknown>;
  return (
    isDecisionBase(record) &&
    typeof record.reviewerId === "string" &&
    UUID_RE.test(record.reviewerId)
  );
}

function decisionFailure(
  label: string,
  status: number,
  error: unknown,
): ConflictDecisionResult {
  const { detail, code } = problem(error);
  switch (status) {
    case 412:
      return {
        kind: "stale",
        message: detail ?? "Changed by someone else since you opened it.",
      };
    case 422:
      return {
        kind: "invalid",
        detail:
          detail && !detail.startsWith("Invalid fields:") ? detail : "The decision was not accepted.",
      };
    case 409:
      return {
        kind: "conflict",
        detail:
          code === "conflict_not_open"
            ? "This Conflict is already escalated."
            : "This Conflict is already resolved.",
      };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${label} failed: status=${status} code=${String(code)}`);
      return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/conflicts/{cid}/resolution` with `If-Match`: choose a
 * position or enter one, with a reason. Never retries or overwrites on 412. Logs ids and
 * statuses only (never the reason or a position). */
export async function resolveConflict(input: unknown): Promise<ConflictDecisionResult> {
  if (!isResolveInput(input)) return { kind: "error" };
  const { opportunityId, conflictId, rowVersion, choice, reason } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/conflicts/{conflict_id}/resolution",
      {
        params: {
          path: { opportunity_id: opportunityId, conflict_id: conflictId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: {
          choice: "position" in choice ? choice.position : { entered: choice.entered },
          reason,
        },
      },
    );
    if (data) return { kind: "ok", conflict: data };
    return decisionFailure("resolve conflict", response.status, error);
  } catch (thrown) {
    console.error(`resolve conflict failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `POST /api/v1/opportunities/{id}/conflicts/{cid}/escalation` with `If-Match`: escalate to
 * a named reviewer on the Opportunity, with a reason. Logs ids and statuses only. */
export async function escalateConflict(input: unknown): Promise<ConflictDecisionResult> {
  if (!isEscalateInput(input)) return { kind: "error" };
  const { opportunityId, conflictId, rowVersion, reviewerId, reason } = input;
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/conflicts/{conflict_id}/escalation",
      {
        params: {
          path: { opportunity_id: opportunityId, conflict_id: conflictId },
          header: { "If-Match": `"${rowVersion}"` },
        },
        body: { reviewer_id: reviewerId, reason },
      },
    );
    if (data) return { kind: "ok", conflict: data };
    return decisionFailure("escalate conflict", response.status, error);
  } catch (thrown) {
    console.error(
      `escalate conflict failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}
