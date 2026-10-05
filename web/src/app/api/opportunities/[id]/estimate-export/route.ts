// Estimate export download (Story 8.8): `GET /api/opportunities/{id}/estimate-export?format=
// xlsx|docx`. Adds the signed-in user's access token, calls the backend's
// `GET /api/v1/opportunities/{id}/estimate/export` and streams the file back with its
// `Content-Disposition`. Failures come back as the backend's problem+json (or a local one).
// The session itself is guarded by `proxy.ts`.
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";

import { createServerApiClient } from "@/lib/api/server";
import { EXPORT_FORMATS, type ExportFormat } from "@/lib/estimates";
import { UUID_RE } from "@/lib/opportunities";

export const dynamic = "force-dynamic";

const PROBLEM_JSON = "application/problem+json";

function problem(status: number, code: string, detail: string): Response {
  return new Response(
    JSON.stringify({ type: `https://errors.pre-sales-agent/${code}`, title: code, status, code, detail }),
    { status, headers: { "Content-Type": PROBLEM_JSON, "Cache-Control": "no-store" } },
  );
}

function isFormat(value: string | null): value is ExportFormat {
  return EXPORT_FORMATS.some((f) => f.value === value);
}

export async function GET(
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
    const { data, error, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/estimate/export",
      {
        params: { path: { opportunity_id: id }, query: { format } },
        parseAs: "stream",
      },
    );
    if (response.ok && data) {
      const headers = new Headers({ "Cache-Control": "no-store" });
      for (const name of ["Content-Type", "Content-Disposition", "Content-Length"]) {
        const value = response.headers.get(name);
        if (value) headers.set(name, value);
      }
      return new Response(data, { status: 200, headers });
    }
    if (response.ok) {
      console.error(`GET estimate export failed: status=${response.status} code=no_body`);
      return problem(502, "export_failed", "The export came back empty.");
    }
    const body = error as { code?: unknown; detail?: unknown } | undefined;
    const code = typeof body?.code === "string" ? body.code : "export_failed";
    const detail = typeof body?.detail === "string" ? body.detail : "";
    console.error(`GET estimate export failed: status=${response.status} code=${code}`);
    return problem(response.status, code, detail);
  } catch (thrown) {
    const name = thrown instanceof Error ? thrown.name : typeof thrown;
    console.error(`GET estimate export failed: status=none code=${name}`);
    return problem(502, "api_unavailable", "The export service couldn't be reached.");
  }
}
