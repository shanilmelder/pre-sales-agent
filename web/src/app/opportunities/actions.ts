"use server";

import { getOpportunity } from "@/app/opportunities/data";
import { createServerApiClient } from "@/lib/api/server";
import {
  codePointLength,
  sliceCodePoints,
  TITLE_MAX,
  UUID_RE,
  type Opportunity,
  type UserSummary,
} from "@/lib/opportunities";
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

/** A 422's sentence: the API's own "Rejected: ..." detail, or a general one. */
function rejectionReason(detail: string | undefined): string {
  if (detail?.startsWith("Rejected:")) return detail;
  return "Rejected: the file couldn't be read";
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
    if (data) return { kind: "ok", source: data };
    switch (response.status) {
      case 422:
        return { kind: "rejected", reason: rejectionReason(problem(error).detail) };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(
          `add source failed: status=${response.status} code=${String(problem(error).code)}`,
        );
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(`add source failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}
