// Clarification Questions export download (Story 4.6): `POST /api/opportunities/{id}/
// questions-export?format=docx|eml`. Adds the signed-in user's access token, calls the
// backend's `POST /api/v1/opportunities/{id}/clarification-questions/export`, then fetches the
// short-lived signed link it returns server-side and streams the file back as an attachment.
// Failures come back as the backend's problem+json (or a local one). Logs statuses only, never
// the question text. The session itself is guarded by `proxy.ts`.
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";

import { createServerApiClient } from "@/lib/api/server";
import { UUID_RE } from "@/lib/opportunities";

export const dynamic = "force-dynamic";

const PROBLEM_JSON = "application/problem+json";
const DOWNLOADS_PREFIX = "/api/v1/downloads/";

/** The file formats this route serves, with the type the browser gets. */
const MEDIA_TYPES = {
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  eml: "message/rfc822",
} as const;

type FileFormat = keyof typeof MEDIA_TYPES;

function problem(status: number, code: string, detail: string): Response {
  return new Response(
    JSON.stringify({ type: `https://errors.pre-sales-agent/${code}`, title: code, status, code, detail }),
    { status, headers: { "Content-Type": PROBLEM_JSON, "Cache-Control": "no-store" } },
  );
}

function isFormat(value: string | null): value is FileFormat {
  return value === "docx" || value === "eml";
}

/** A file name safe for a `Content-Disposition` header (the API's names are ASCII slugs). */
function safeName(name: string, format: FileFormat): string {
  const cleaned = name.replace(/[^A-Za-z0-9._-]/g, "");
  return cleaned || `clarification-questions.${format}`;
}

function failure(action: string, status: number, error: unknown): Response {
  const body = error as { code?: unknown; detail?: unknown } | undefined;
  const code = typeof body?.code === "string" ? body.code : "export_failed";
  const detail = typeof body?.detail === "string" ? body.detail : "";
  console.error(`${action} failed: status=${status} code=${code}`);
  return problem(status, code, detail);
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  const format = new URL(request.url).searchParams.get("format");
  if (!UUID_RE.test(id) || !isFormat(format)) {
    return problem(422, "validation_error", "Invalid fields: opportunity_id, format");
  }
  let api;
  try {
    api = await createServerApiClient();
  } catch (error) {
    if (error instanceof AccessTokenError) {
      return problem(401, "token_missing", "Sign in again to export.");
    }
    throw error;
  }
  try {
    const exported = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/export",
      { params: { path: { opportunity_id: id } }, body: { format } },
    );
    if (!exported.data) {
      return failure("POST questions export", exported.response.status, exported.error);
    }
    const { url, file_name } = exported.data;
    if (typeof url !== "string" || !url.startsWith(DOWNLOADS_PREFIX)) {
      console.error("POST questions export failed: status=200 code=no_link");
      return problem(502, "export_failed", "The export came back without a file.");
    }
    const token = url.slice(DOWNLOADS_PREFIX.length);
    const downloaded = await api.GET("/api/v1/downloads/{token}", {
      params: { path: { token } },
      parseAs: "stream",
    });
    if (!downloaded.response.ok || !downloaded.data) {
      return failure("GET questions export file", downloaded.response.status || 502, downloaded.error);
    }
    const headers = new Headers({
      "Cache-Control": "no-store",
      "Content-Type": MEDIA_TYPES[format],
      "Content-Disposition": `attachment; filename="${safeName(file_name ?? "", format)}"`,
      "X-Content-Type-Options": "nosniff",
    });
    const length = downloaded.response.headers.get("Content-Length");
    if (length) headers.set("Content-Length", length);
    return new Response(downloaded.data, { status: 200, headers });
  } catch (thrown) {
    const name = thrown instanceof Error ? thrown.name : typeof thrown;
    console.error(`POST questions export failed: status=none code=${name}`);
    return problem(502, "api_unavailable", "The export service couldn't be reached.");
  }
}
