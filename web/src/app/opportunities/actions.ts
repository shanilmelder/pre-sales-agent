"use server";

import {
  getEstimate,
  getOpportunity,
  getRedTeam,
  listGaps,
  listRequirements,
  listSources,
  type EstimateResult,
  type GapsResult,
  type RedTeamResult,
  type RequirementsResult,
  type SourcesResult,
} from "@/app/opportunities/data";
import { createServerApiClient } from "@/lib/api/server";
import type { Assumption, EstimateDraft } from "@/lib/estimates";
import type { Detection } from "@/lib/gaps";
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
};

export type CreateResult =
  | { kind: "ok"; id: string }
  /** 422: the fields the API rejected (empty when it named none we know). */
  | { kind: "invalid"; fields: CreateField[] }
  | { kind: "forbidden" }
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
  return (
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
      },
    });
    if (data) return { kind: "ok", id: data.id };
    if (response.status === 422) return { kind: "invalid", fields: invalidFields(problem(error).detail) };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`create opportunity failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`create opportunity failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
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

export type RequirementWriteResult =
  | { kind: "ok"; requirement: Requirement }
  /** 412: someone changed the Requirement first. `changedBy` is null when unknown. */
  | { kind: "stale"; changedBy: string | null }
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

/** Who last changed the Requirement, read again after a 412 (null when unknown). */
async function requirementChanger(
  opportunityId: string,
  requirementId: string,
): Promise<string | null> {
  const current = await listRequirements(opportunityId);
  if (current.kind !== "ok") return null;
  return (
    current.list.items.find((item) => item.id === requirementId)?.last_changed_by?.name ?? null
  );
}

async function requirementWriteFailure(
  action: string,
  input: RequirementConfirmInput,
  status: number,
  error: unknown,
): Promise<RequirementWriteResult> {
  switch (status) {
    case 412:
      return {
        kind: "stale",
        changedBy: await requirementChanger(input.opportunityId, input.requirementId),
      };
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
  /** 409 `gap_not_open`: the Gap was converted or replaced; nothing changed. */
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
