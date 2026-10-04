// Opportunity Source display helpers. Safe on server and client.
import type { components } from "@/lib/api/client";
import { UPLOAD_BODY_LIMIT_BYTES } from "@/lib/upload-limits";

export type Source = components["schemas"]["Source"];
export type SourceKind = components["schemas"]["SourceKind"];

export const SOURCE_KIND_LABELS: Record<SourceKind, string> = {
  email: "Email",
  note: "Note",
  transcript: "Transcript",
  document: "Document",
};

/** What the file picker offers. The API decides what is allowed. */
export const ACCEPTED_FILES = ".eml,.msg,.txt,.vtt,.docx,.pdf";

/** The API's sentence for a file over the limit. */
export const TOO_LARGE = "Rejected: larger than 50 MB";

/** Room the multipart framing needs on top of the file inside the body limit. */
const FRAMING_BYTES = 64 * 1024;

/** True for a file the web server can't carry to the API at all (past its body limit). The
 * API enforces the 50 MB limit; this only avoids sending a body that would be cut off. */
export function exceedsTransportLimit(size: number): boolean {
  return size > UPLOAD_BODY_LIMIT_BYTES - FRAMING_BYTES;
}

/** The empty-state sentence. */
export const NO_SOURCES = "No Sources yet.";

/** `source` first when it is new; in place when it is a newer version of a listed one. */
export function withSource(sources: readonly Source[], source: Source): Source[] {
  const index = sources.findIndex((s) => s.id === source.id);
  if (index === -1) return [source, ...sources];
  return sources.map((s, i) => (i === index ? source : s));
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

/** An ISO timestamp as "4 Oct 2026, 13:05 UTC", the same on server and client. */
export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `${DATE_TIME_FORMAT.format(date)} UTC`;
}

export type SourceParse = components["schemas"]["SourceParse"];
export type ParseStatus = components["schemas"]["ParseStatus"];
export type ParseErrorCode = components["schemas"]["ParseErrorCode"];

/** The parse status pill labels. */
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
  not_supported: "Outlook .msg files aren't supported yet — paste the text instead",
};

/** The reason sentence for a failed parse (a general one for a code this build doesn't know). */
export function parseFailureReason(code: ParseErrorCode | null | undefined): string {
  return (code ? PARSE_FAILURE_REASONS[code] : undefined) ?? PARSE_FAILURE_REASONS.unreadable;
}

/** True while the Source's latest version is still waiting for or being parsed. */
export function isParsePending(source: Source): boolean {
  const status = source.parse?.status;
  return status === "queued" || status === "parsing";
}

/** How often the Sources tab re-reads the list while a parse is pending. */
export const PARSE_POLL_MS = 2000;

/** The list as re-read from the API (`server`), keeping what this page added since that
 * read began: a Source it doesn't have yet, or a newer version than it shows. */
export function mergeSources(server: readonly Source[], local: readonly Source[]): Source[] {
  let merged = [...server];
  for (const source of [...local].reverse()) {
    const known = merged.find((s) => s.id === source.id);
    if (!known || known.version < source.version) merged = withSource(merged, source);
  }
  return merged;
}

/** Polling stops after this long with a parse continuously pending (a reload resumes it). */
export const PARSE_POLL_LIMIT_MS = 15 * 60 * 1000;
