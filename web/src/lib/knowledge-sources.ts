// Knowledge Source display and form helpers (Story 3.2). Safe on server and client.
import type { components } from "@/lib/api/client";
import type { Role } from "@/lib/navigation";
import { UPLOAD_BODY_LIMIT_BYTES } from "@/lib/upload-limits";

export type KnowledgeSource = components["schemas"]["KnowledgeSource"];
export type KnowledgeSourceVersion = components["schemas"]["KnowledgeSourceVersion"];
export type IntegrationTypeTag = components["schemas"]["IntegrationTypeTag"];
export type SourceParse = components["schemas"]["SourceParse"];
export type ParseStatus = components["schemas"]["ParseStatus"];
export type ParseErrorCode = components["schemas"]["ParseErrorCode"];

export const TITLE_MAX = 200;
export const PRODUCT_MAX = 120;
export const PRODUCT_VERSION_MAX = 60;
export const REASON_MAX = 500;

/** The Sources list's empty state. */
export const EMPTY_STATE = "No Knowledge Sources yet. Upload product or integration documentation to start.";
/** Shown when the filters hide every Source. */
export const NO_MATCHES = "No Knowledge Sources match these filters.";

/** What the file picker offers. The API decides what is allowed. */
export const ACCEPTED_FILES = ".pdf,.docx,.txt,.md";
/** The API's sentence for a file over the limit. */
export const TOO_LARGE = "Rejected: larger than 50 MB";
const FRAMING_BYTES = 64 * 1024;

/** True for a file the web server can't carry to the API at all (past its body limit). */
export function exceedsTransportLimit(size: number): boolean {
  return size > UPLOAD_BODY_LIMIT_BYTES - FRAMING_BYTES;
}

/** Only platform administrators register Knowledge Sources (the API decides). */
export function canRegister(roles: readonly Role[]): boolean {
  return roles.includes("platform_administrator");
}

/** True for platform administrators and the Source's owner: the people who may change it.
 * Actions anyone else can't take are hidden (the API refuses them with 403 anyway). */
export function canWrite(
  source: Pick<KnowledgeSource, "owner" | "retired">,
  me: { id: string; roles: readonly Role[] },
): boolean {
  return !source.retired && (me.roles.includes("platform_administrator") || source.owner.id === me.id);
}

/** The parse status labels. */
export const PARSE_STATUS_LABELS: Record<ParseStatus, string> = {
  queued: "Queued",
  parsing: "Parsing",
  parsed: "Parsed",
  failed: "Parse failed",
};

/** Why a parse failed, as the Sources tab says it. */
export const PARSE_FAILURE_REASONS: Record<ParseErrorCode, string> = {
  unreadable: "The file couldn't be read",
  no_text: "No text found — scanned PDF?",
  timeout: "Parsing took too long",
  too_large_output: "Too much text to process",
  not_supported: "This file type can't be parsed yet",
};

export function parseFailureReason(code: ParseErrorCode | null | undefined): string {
  return (code ? PARSE_FAILURE_REASONS[code] : undefined) ?? PARSE_FAILURE_REASONS.unreadable;
}

/** True while the Source's latest version is still waiting for or being parsed. */
export function isParsePending(source: Pick<KnowledgeSource, "parse">): boolean {
  return source.parse.status === "queued" || source.parse.status === "parsing";
}

/** How often the Sources tab re-reads the list while a parse is pending (polling, no SSE). */
export const PARSE_POLL_MS = 2000;
/** Polling stops after this long with a parse continuously pending (a reload resumes it). */
export const PARSE_POLL_LIMIT_MS = 15 * 60 * 1000;

export type Filters = {
  product: string;
  integrationTypeId: string;
  ownerId: string;
  staleOnly: boolean;
};

export const NO_FILTERS: Filters = { product: "", integrationTypeId: "", ownerId: "", staleOnly: false };

export function hasFilters(filters: Filters): boolean {
  return (
    filters.product !== "" ||
    filters.integrationTypeId !== "" ||
    filters.ownerId !== "" ||
    filters.staleOnly
  );
}

/** The Sources that match every filter set (product compares ignoring case). */
export function applyFilters(
  sources: readonly KnowledgeSource[],
  filters: Filters,
): KnowledgeSource[] {
  return sources.filter(
    (s) =>
      (filters.product === "" || s.product.toLowerCase() === filters.product.toLowerCase()) &&
      (filters.integrationTypeId === "" ||
        s.integration_types.some((t) => t.id === filters.integrationTypeId)) &&
      (filters.ownerId === "" || s.owner.id === filters.ownerId) &&
      (!filters.staleOnly || s.stale),
  );
}

/** The distinct products of the Sources, sorted, ignoring case. */
export function productsOf(sources: readonly KnowledgeSource[]): string[] {
  const byKey = new Map<string, string>();
  for (const s of sources) if (!byKey.has(s.product.toLowerCase())) byKey.set(s.product.toLowerCase(), s.product);
  return [...byKey.values()].sort((a, b) => a.localeCompare(b));
}

/** The distinct owners of the Sources, sorted by name. */
export function ownersOf(sources: readonly KnowledgeSource[]): { id: string; name: string }[] {
  const byId = new Map<string, string>();
  for (const s of sources) byId.set(s.owner.id, s.owner.name);
  return [...byId].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name));
}

/** `source` replaced in the list (matching id), or added. Keeps the longest-unreviewed
 * first order the API uses. */
export function upsert(
  sources: readonly KnowledgeSource[],
  source: KnowledgeSource,
): KnowledgeSource[] {
  return [...sources.filter((s) => s.id !== source.id), source].sort(
    (a, b) =>
      a.last_reviewed_on.localeCompare(b.last_reviewed_on) ||
      a.title.toLowerCase().localeCompare(b.title.toLowerCase()),
  );
}

/** The list as re-read from the API (`server`), keeping what this page changed since that
 * read began: a Source it doesn't have yet, or a newer row version than it shows. */
export function mergeSources(
  server: readonly KnowledgeSource[],
  local: readonly KnowledgeSource[],
): KnowledgeSource[] {
  let merged = [...server];
  for (const source of local) {
    const known = merged.find((s) => s.id === source.id);
    if (!known || known.row_version < source.row_version) merged = upsert(merged, source);
  }
  return merged;
}

/** Characters as the API counts them (code points), after trimming. */
function length(text: string): number {
  return Array.from(text.trim()).length;
}

/** The reason a field can't be saved, or null. Mirrors the API's rules; the API decides. */
export function fieldError(
  field: "title" | "product" | "product version" | "reason",
  value: string,
): string | null {
  const max = {
    title: TITLE_MAX,
    product: PRODUCT_MAX,
    "product version": PRODUCT_VERSION_MAX,
    reason: REASON_MAX,
  }[field];
  const size = length(value);
  if (size === 0) return `The ${field} is required.`;
  if (size > max) return `The ${field} must be at most ${max.toLocaleString("en-US")} characters.`;
  return null;
}

/** The 412 notice. */
export function staleChangeMessage(): string {
  return "Changed by someone else since you opened it. Reload to see their change.";
}

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

/** An ISO date ("2026-10-07") as "7 Oct 2026", the same on server and client. */
export function formatDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? value : DATE_FORMAT.format(date);
}

const DATE_TIME_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZone: "UTC",
});

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${DATE_TIME_FORMAT.format(date)} UTC`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
