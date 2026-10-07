"use server";

import { createServerApiClient } from "@/lib/api/server";
import type { KnowledgeSource, KnowledgeSourceVersion } from "@/lib/knowledge-sources";
import { UUID_RE } from "@/lib/opportunities";

const FILE_UNREADABLE = "Rejected: the file couldn't be read";
const SOURCES = "/api/v1/knowledge/sources";

/** A write's outcome, by status. */
export type SourceResult =
  | { kind: "ok"; source: KnowledgeSource }
  /** 412: someone changed the Source first. */
  | { kind: "stale" }
  /** 422 for a file: the API's `Rejected: …` sentence. */
  | { kind: "rejected"; reason: string }
  /** 422 for a field or tag, with the API's sentence. */
  | { kind: "invalid"; detail: string }
  /** 409 `knowledge_source_retired` or `parse_not_failed`. */
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type SourcesResult =
  | { kind: "ok"; sources: KnowledgeSource[]; staleMonths: number }
  | { kind: "error" };

export type DetailResult =
  | { kind: "ok"; source: KnowledgeSource; versions: KnowledgeSourceVersion[] }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type TextResult =
  | { kind: "ok"; text: string; charCount: number }
  | { kind: "unavailable" }
  | { kind: "error" };

export type OwnersResult =
  | { kind: "ok"; users: { id: string; name: string; email: string }[] }
  | { kind: "error" };

function isObject(input: unknown): input is Record<string, unknown> {
  return typeof input === "object" && input !== null;
}

function isId(value: unknown): value is string {
  return typeof value === "string" && UUID_RE.test(value);
}

function isRowVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function problem(error: unknown): { detail?: string; code?: string } {
  const body = error as { detail?: unknown; code?: unknown } | undefined;
  return {
    detail: typeof body?.detail === "string" ? body.detail : undefined,
    code: typeof body?.code === "string" ? body.code : undefined,
  };
}

function failed(what: string, thrown: unknown): { kind: "error" } {
  console.error(`${what} failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
  return { kind: "error" };
}

type Outcome = { data?: KnowledgeSource; error?: unknown; response: Response };

/** Maps a write's outcome. A 422 whose sentence starts "Rejected:" is a file rejection. */
function outcome(result: Outcome, what: string): SourceResult {
  if (result.data) return { kind: "ok", source: result.data };
  const { detail, code } = problem(result.error);
  switch (result.response.status) {
    case 412:
      return { kind: "stale" };
    case 422:
      return detail?.startsWith("Rejected:")
        ? { kind: "rejected", reason: detail }
        : { kind: "invalid", detail: detail ?? "This value is not valid." };
    case 409:
      return { kind: "conflict" };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${what} failed: status=${result.response.status} code=${String(code)}`);
      return { kind: "error" };
  }
}

/** The Sources (retired ones too), longest-unreviewed first. */
export async function loadSources(): Promise<SourcesResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(SOURCES, {
      params: { query: { include_retired: true } },
    });
    if (data) return { kind: "ok", sources: data.items, staleMonths: data.stale_months };
    console.error(`GET knowledge sources failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET knowledge sources", thrown);
  }
}

/** One Source and its versions (newest first). Authorization is decided by the API. */
export async function loadSource(sourceId: unknown): Promise<DetailResult> {
  if (!isId(sourceId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const params = { params: { path: { source_id: sourceId } } };
    const [source, versions] = await Promise.all([
      api.GET("/api/v1/knowledge/sources/{source_id}", params),
      api.GET("/api/v1/knowledge/sources/{source_id}/versions", params),
    ]);
    if (source.data && versions.data) {
      return { kind: "ok", source: source.data, versions: versions.data.items };
    }
    const status = (source.data ? versions.response : source.response).status;
    if (status === 403) return { kind: "forbidden" };
    if (status === 404) return { kind: "not-found" };
    console.error(`GET knowledge source failed: status=${status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET knowledge source", thrown);
  }
}

/** The extracted text of a version, once parsed. */
export async function loadText(sourceId: unknown, version: unknown): Promise<TextResult> {
  if (!isId(sourceId) || typeof version !== "number" || !Number.isSafeInteger(version)) {
    return { kind: "unavailable" };
  }
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/knowledge/sources/{source_id}/versions/{version}/text",
      { params: { path: { source_id: sourceId, version } } },
    );
    if (data) return { kind: "ok", text: data.text, charCount: data.char_count };
    if (response.status === 404) return { kind: "unavailable" };
    console.error(`GET knowledge source text failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET knowledge source text", thrown);
  }
}

/** `POST /api/v1/knowledge/sources` with the `file` and fields from `formData`: `title`,
 * `product`, `productVersion`, `ownerId` (optional) and one `tagId` per Integration Type.
 * The API checks who may register, the tags, the type, the size and the content. */
export async function registerSource(formData: unknown): Promise<SourceResult> {
  if (!(formData instanceof FormData)) return { kind: "error" };
  const file = formData.get("file");
  const title = formData.get("title");
  const product = formData.get("product");
  const productVersion = formData.get("productVersion");
  const ownerId = formData.get("ownerId");
  const tagIds = formData.getAll("tagId");
  if (!(file instanceof File)) return { kind: "error" };
  if (typeof title !== "string" || typeof product !== "string") return { kind: "error" };
  if (typeof productVersion !== "string") return { kind: "error" };
  if (ownerId !== null && !isId(ownerId)) return { kind: "error" };
  if (!tagIds.every((id): id is string => typeof id === "string")) return { kind: "error" };
  const upload = new FormData();
  upload.append("file", file, file.name);
  try {
    const api = await createServerApiClient();
    const result = await api.POST(SOURCES, {
      params: {
        query: {
          title,
          product,
          product_version: productVersion,
          integration_type_ids: tagIds,
          owner_id: ownerId,
        },
      },
      // The generated type describes the multipart field; the body sent is the FormData.
      body: { file: "" },
      bodySerializer: () => upload,
    });
    const mapped = outcome(result, "register knowledge source");
    return mapped.kind === "invalid" && mapped.detail === "Invalid fields: body.file"
      ? { kind: "rejected", reason: FILE_UNREADABLE }
      : mapped;
  } catch (thrown) {
    return failed("register knowledge source", thrown);
  }
}

/** `POST …/versions` with the `file` from `formData` (plus `sourceId`, `rowVersion` and
 * `productVersion`): the next version of the Source. */
export async function addVersion(formData: unknown): Promise<SourceResult> {
  if (!(formData instanceof FormData)) return { kind: "error" };
  const file = formData.get("file");
  const sourceId = formData.get("sourceId");
  const rowVersion = Number(formData.get("rowVersion"));
  const productVersion = formData.get("productVersion");
  if (!(file instanceof File) || !isId(sourceId) || !isRowVersion(rowVersion)) {
    return { kind: "error" };
  }
  if (typeof productVersion !== "string") return { kind: "error" };
  const upload = new FormData();
  upload.append("file", file, file.name);
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/knowledge/sources/{source_id}/versions", {
      params: {
        path: { source_id: sourceId },
        query: { product_version: productVersion },
        header: { "If-Match": `"${rowVersion}"` },
      },
      body: { file: "" },
      bodySerializer: () => upload,
    });
    return outcome(result, "add knowledge source version");
  } catch (thrown) {
    return failed("add knowledge source version", thrown);
  }
}

/** `PATCH` the title, product, tags and/or owner, with the row version as `If-Match`. Never
 * retries or overwrites on 412. */
export async function editSource(input: unknown): Promise<SourceResult> {
  if (!isObject(input)) return { kind: "error" };
  const { sourceId, rowVersion, title, product, integrationTypeIds, ownerId } = input;
  if (!isId(sourceId) || !isRowVersion(rowVersion)) return { kind: "error" };
  if (title !== undefined && typeof title !== "string") return { kind: "error" };
  if (product !== undefined && typeof product !== "string") return { kind: "error" };
  if (ownerId !== undefined && !isId(ownerId)) return { kind: "error" };
  if (
    integrationTypeIds !== undefined &&
    !(Array.isArray(integrationTypeIds) && integrationTypeIds.every(isId))
  ) {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const result = await api.PATCH("/api/v1/knowledge/sources/{source_id}", {
      params: { path: { source_id: sourceId }, header: { "If-Match": `"${rowVersion}"` } },
      body: { title, product, owner_id: ownerId, integration_type_ids: integrationTypeIds },
    });
    return outcome(result, "edit knowledge source");
  } catch (thrown) {
    return failed("edit knowledge source", thrown);
  }
}

/** `POST …/review`: last reviewed becomes today. */
export async function markReviewed(input: unknown): Promise<SourceResult> {
  if (!isObject(input)) return { kind: "error" };
  const { sourceId, rowVersion } = input;
  if (!isId(sourceId) || !isRowVersion(rowVersion)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/knowledge/sources/{source_id}/review", {
      params: { path: { source_id: sourceId }, header: { "If-Match": `"${rowVersion}"` } },
    });
    return outcome(result, "mark knowledge source reviewed");
  } catch (thrown) {
    return failed("mark knowledge source reviewed", thrown);
  }
}

/** `POST …/retire` with a reason. */
export async function retireSource(input: unknown): Promise<SourceResult> {
  if (!isObject(input)) return { kind: "error" };
  const { sourceId, rowVersion, reason } = input;
  if (!isId(sourceId) || !isRowVersion(rowVersion) || typeof reason !== "string") {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/knowledge/sources/{source_id}/retire", {
      params: { path: { source_id: sourceId }, header: { "If-Match": `"${rowVersion}"` } },
      body: { reason },
    });
    return outcome(result, "retire knowledge source");
  } catch (thrown) {
    return failed("retire knowledge source", thrown);
  }
}

/** `POST …/parse`: parse the failed latest version again. */
export async function retryParse(sourceId: unknown): Promise<SourceResult> {
  if (!isId(sourceId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/knowledge/sources/{source_id}/parse", {
      params: { path: { source_id: sourceId } },
    });
    return outcome(result, "retry knowledge source parse");
  } catch (thrown) {
    return failed("retry knowledge source parse", thrown);
  }
}

/** Users an administrator may name as owner. */
export async function searchOwners(query: unknown): Promise<OwnersResult> {
  if (typeof query !== "string") return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/knowledge/sources/owner-candidates", {
      params: { query: { q: query } },
    });
    if (data) return { kind: "ok", users: data.items };
    if (response.status !== 403) {
      console.error(`GET knowledge owner candidates failed: status=${response.status}`);
    }
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET knowledge owner candidates", thrown);
  }
}
