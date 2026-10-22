"use server";

import { createServerApiClient } from "@/lib/api/server";
import type {
  Checklist,
  ChecklistVersion,
  ChecklistVersionSummary,
  DraftInput,
} from "@/lib/checklists";
import { UUID_RE } from "@/lib/opportunities";

const CHECKLISTS = "/api/v1/knowledge/checklists";
const ONE = "/api/v1/knowledge/checklists/{checklist_id}";

/** A write's outcome, by status. */
export type ChecklistResult =
  | { kind: "ok"; checklist: Checklist }
  /** 412: someone changed the Checklist first. Nothing was overwritten. */
  | { kind: "stale" }
  /** 422, with the API's sentence. */
  | { kind: "invalid"; detail: string }
  /** 409 `knowledge_checklist_retired`, `checklist_draft_exists` or `checklist_no_draft`. */
  | { kind: "conflict"; code?: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type ChecklistsResult = { kind: "ok"; checklists: Checklist[] } | { kind: "error" };

export type DetailResult =
  | { kind: "ok"; checklist: Checklist; versions: ChecklistVersionSummary[] }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type VersionResult =
  | { kind: "ok"; version: ChecklistVersion }
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

function isVersion(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 1;
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((v) => typeof v === "string");
}

function isItem(value: unknown): boolean {
  if (!isObject(value)) return false;
  const { id, kind, text, why_it_matters, affected_entry_id, impact, mandatory } = value;
  return (
    (id === null || isId(id)) &&
    (kind === "question" || kind === "risk") &&
    typeof text === "string" &&
    typeof why_it_matters === "string" &&
    (affected_entry_id === null || isId(affected_entry_id)) &&
    (impact === "high" || impact === "medium" || impact === "low") &&
    typeof mandatory === "boolean"
  );
}

/** A `PUT …/draft` body of the right shape (the API checks the rules). */
function isDraft(value: unknown): value is DraftInput {
  if (!isObject(value)) return false;
  const { name, domain, products, industry, integration_type_ids, items } = value;
  return (
    typeof name === "string" &&
    typeof domain === "string" &&
    isStringList(products) &&
    (industry === null || typeof industry === "string") &&
    Array.isArray(integration_type_ids) &&
    integration_type_ids.every(isId) &&
    Array.isArray(items) &&
    items.every(isItem)
  );
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

type Outcome = { data?: Checklist; error?: unknown; response: Response };

function outcome(result: Outcome, what: string): ChecklistResult {
  if (result.data) return { kind: "ok", checklist: result.data };
  const { detail, code } = problem(result.error);
  switch (result.response.status) {
    case 412:
      return { kind: "stale" };
    case 422:
      return { kind: "invalid", detail: detail ?? "This value is not valid." };
    case 409:
      return code ? { kind: "conflict", code } : { kind: "conflict" };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${what} failed: status=${result.response.status} code=${String(code)}`);
      return { kind: "error" };
  }
}

function ifMatch(rowVersion: number) {
  return { "If-Match": `"${rowVersion}"` };
}

/** Every Checklist, retired ones too, by name. */
export async function loadChecklists(): Promise<ChecklistsResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(CHECKLISTS, {
      params: { query: { include_retired: true } },
    });
    if (data) return { kind: "ok", checklists: data.items };
    console.error(`GET checklists failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET checklists", thrown);
  }
}

/** One Checklist and its published versions (newest first). */
export async function loadChecklist(checklistId: unknown): Promise<DetailResult> {
  if (!isId(checklistId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const params = { params: { path: { checklist_id: checklistId } } };
    const [checklist, versions] = await Promise.all([
      api.GET(ONE, params),
      api.GET("/api/v1/knowledge/checklists/{checklist_id}/versions", params),
    ]);
    if (checklist.data && versions.data) {
      return { kind: "ok", checklist: checklist.data, versions: versions.data.items };
    }
    const status = (checklist.data ? versions.response : checklist.response).status;
    if (status === 403) return { kind: "forbidden" };
    if (status === 404) return { kind: "not-found" };
    console.error(`GET checklist failed: status=${status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET checklist", thrown);
  }
}

/** One published version, read-only. */
export async function loadChecklistVersion(
  checklistId: unknown,
  version: unknown,
): Promise<VersionResult> {
  if (!isId(checklistId) || !isVersion(version)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/knowledge/checklists/{checklist_id}/versions/{version}", {
      params: { path: { checklist_id: checklistId, version } },
    });
    if (data) return { kind: "ok", version: data };
    if (response.status === 404) return { kind: "not-found" };
    console.error(`GET checklist version failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return failed("GET checklist version", thrown);
  }
}

/** `POST /api/v1/knowledge/checklists`: a new Checklist with an empty draft. */
export async function createChecklist(input: unknown): Promise<ChecklistResult> {
  if (!isObject(input)) return { kind: "error" };
  const { name, domain } = input;
  if (typeof name !== "string" || typeof domain !== "string") return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST(CHECKLISTS, {
      body: { name, domain: domain as DraftInput["domain"] },
    });
    return outcome(result, "create checklist");
  } catch (thrown) {
    return failed("create checklist", thrown);
  }
}

/** `PUT …/draft`: the whole draft, with the row version as `If-Match`. Never retries or
 * overwrites on 412. */
export async function saveDraft(input: unknown): Promise<ChecklistResult> {
  if (!isObject(input)) return { kind: "error" };
  const { checklistId, rowVersion, draft } = input;
  if (!isId(checklistId) || !isRowVersion(rowVersion) || !isDraft(draft)) {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const result = await api.PUT("/api/v1/knowledge/checklists/{checklist_id}/draft", {
      params: { path: { checklist_id: checklistId }, header: ifMatch(rowVersion) },
      body: draft,
    });
    return outcome(result, "save checklist draft");
  } catch (thrown) {
    return failed("save checklist draft", thrown);
  }
}

async function post(
  path: "/api/v1/knowledge/checklists/{checklist_id}/draft" | "/api/v1/knowledge/checklists/{checklist_id}/publish",
  input: unknown,
  what: string,
): Promise<ChecklistResult> {
  if (!isObject(input)) return { kind: "error" };
  const { checklistId, rowVersion } = input;
  if (!isId(checklistId) || !isRowVersion(rowVersion)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST(path, {
      params: { path: { checklist_id: checklistId }, header: ifMatch(rowVersion) },
    });
    return outcome(result, what);
  } catch (thrown) {
    return failed(what, thrown);
  }
}

/** `POST …/draft`: start a draft from the latest published version. */
export async function openDraft(input: unknown): Promise<ChecklistResult> {
  return post("/api/v1/knowledge/checklists/{checklist_id}/draft", input, "open checklist draft");
}

/** `POST …/publish`: the draft becomes the next version. */
export async function publishChecklist(input: unknown): Promise<ChecklistResult> {
  return post("/api/v1/knowledge/checklists/{checklist_id}/publish", input, "publish checklist");
}

/** `POST …/retire` with a reason. */
export async function retireChecklist(input: unknown): Promise<ChecklistResult> {
  if (!isObject(input)) return { kind: "error" };
  const { checklistId, rowVersion, reason } = input;
  if (!isId(checklistId) || !isRowVersion(rowVersion) || typeof reason !== "string") {
    return { kind: "error" };
  }
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/knowledge/checklists/{checklist_id}/retire", {
      params: { path: { checklist_id: checklistId }, header: ifMatch(rowVersion) },
      body: { reason },
    });
    return outcome(result, "retire checklist");
  } catch (thrown) {
    return failed("retire checklist", thrown);
  }
}
