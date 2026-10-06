"use server";

import { createServerApiClient } from "@/lib/api/server";
import type { CatalogueEntry, CatalogueVersion } from "@/lib/catalogue";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type EntryResult =
  | { kind: "ok"; entry: CatalogueEntry }
  /** 412: someone changed the entry first. `changedBy` is null when unknown. */
  | { kind: "stale"; changedBy: string | null }
  /** 409 `catalogue_duplicate`, with the API's sentence. */
  | { kind: "duplicate"; detail: string }
  /** 422, with the API's sentence. */
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type DetailResult =
  | { kind: "ok"; entry: CatalogueEntry; versions: CatalogueVersion[] }
  | { kind: "forbidden" }
  | { kind: "not-found" }
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

function detailOf(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : undefined;
}

function codeOf(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | undefined)?.code;
  return typeof code === "string" ? code : undefined;
}

/** The entry and its versions (newest first). Authorization is decided by the API. */
export async function loadEntry(entryId: unknown): Promise<DetailResult> {
  if (!isId(entryId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const params = { params: { path: { entry_id: entryId } } };
    const [entry, versions] = await Promise.all([
      api.GET("/api/v1/catalogue/entries/{entry_id}", params),
      api.GET("/api/v1/catalogue/entries/{entry_id}/versions", params),
    ]);
    if (entry.data && versions.data) {
      return { kind: "ok", entry: entry.data, versions: versions.data.items };
    }
    const status = (entry.data ? versions.response : entry.response).status;
    if (status === 403) return { kind: "forbidden" };
    if (status === 404) return { kind: "not-found" };
    console.error(`GET catalogue entry failed: status=${status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET catalogue entry failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

type Outcome = {
  data?: CatalogueEntry;
  error?: unknown;
  response: Response;
};

/** Maps a write's outcome; a 412 looks up who saved the latest version. */
async function outcome(result: Outcome, entryId: string, what: string): Promise<EntryResult> {
  if (result.data) return { kind: "ok", entry: result.data };
  switch (result.response.status) {
    case 412: {
      const current = await loadEntry(entryId);
      return {
        kind: "stale",
        changedBy: current.kind === "ok" ? (current.versions[0]?.changed_by_name ?? null) : null,
      };
    }
    case 409:
      return { kind: "duplicate", detail: detailOf(result.error) ?? "This entry already exists." };
    case 422:
      return { kind: "invalid", detail: detailOf(result.error) ?? "This value is not valid." };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(
        `${what} failed: status=${result.response.status} code=${String(codeOf(result.error))}`,
      );
      return { kind: "error" };
  }
}

function failed(what: string, thrown: unknown): EntryResult {
  console.error(`${what} failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
  return { kind: "error" };
}

/** `POST /api/v1/catalogue/entries`. */
export async function createEntry(input: unknown): Promise<EntryResult> {
  if (!isObject(input)) return { kind: "error" };
  const { kind, code, name, definition } = input;
  if (
    (kind !== "integration_type" && kind !== "work_package") ||
    typeof code !== "string" ||
    typeof name !== "string" ||
    typeof definition !== "string"
  ) {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/catalogue/entries", {
      body: { kind, code, name, definition },
    });
    return await outcome(result, "", "create catalogue entry");
  } catch (thrown) {
    return failed("create catalogue entry", thrown);
  }
}

/** `PATCH` with the row version as `If-Match`. Never retries or overwrites on 412. */
export async function editEntry(input: unknown): Promise<EntryResult> {
  if (!isObject(input)) return { kind: "error" };
  const { entryId, rowVersion, name, definition } = input;
  if (!isId(entryId) || !isRowVersion(rowVersion)) return { kind: "error" };
  if (name !== undefined && typeof name !== "string") return { kind: "error" };
  if (definition !== undefined && typeof definition !== "string") return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const result = await api.PATCH("/api/v1/catalogue/entries/{entry_id}", {
      params: { path: { entry_id: entryId }, header: { "If-Match": `"${rowVersion}"` } },
      body: { name, definition },
    });
    return await outcome(result, entryId, "edit catalogue entry");
  } catch (thrown) {
    return failed("edit catalogue entry", thrown);
  }
}

/** `POST …/retire` with a reason. */
export async function retireEntry(input: unknown): Promise<EntryResult> {
  if (!isObject(input)) return { kind: "error" };
  const { entryId, rowVersion, reason } = input;
  if (!isId(entryId) || !isRowVersion(rowVersion) || typeof reason !== "string") {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/catalogue/entries/{entry_id}/retire", {
      params: { path: { entry_id: entryId }, header: { "If-Match": `"${rowVersion}"` } },
      body: { reason },
    });
    return await outcome(result, entryId, "retire catalogue entry");
  } catch (thrown) {
    return failed("retire catalogue entry", thrown);
  }
}

/** `POST …/reactivate`. */
export async function reactivateEntry(input: unknown): Promise<EntryResult> {
  if (!isObject(input)) return { kind: "error" };
  const { entryId, rowVersion } = input;
  if (!isId(entryId) || !isRowVersion(rowVersion)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/catalogue/entries/{entry_id}/reactivate", {
      params: { path: { entry_id: entryId }, header: { "If-Match": `"${rowVersion}"` } },
    });
    return await outcome(result, entryId, "reactivate catalogue entry");
  } catch (thrown) {
    return failed("reactivate catalogue entry", thrown);
  }
}
