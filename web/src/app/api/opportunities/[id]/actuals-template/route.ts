// Actuals import template download (Story 10.2): `GET /api/opportunities/{id}/actuals-template`.
// Adds the signed-in user's access token, calls the backend's `GET /api/v1/opportunities/{id}/
// actuals/template` (which stores the .xlsx and traces the download with the Opportunity), then
// fetches the short-lived signed link it returns server-side and streams the file back as an
// attachment. Failures come back as the backend's problem+json (or a local one). Logs statuses
// only. The session itself is guarded by `proxy.ts`.
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";

import { createServerApiClient } from "@/lib/api/server";
import { UUID_RE } from "@/lib/opportunities";

export const dynamic = "force-dynamic";

const PROBLEM_JSON = "application/problem+json";
const DOWNLOADS_PREFIX = "/api/v1/downloads/";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const FALLBACK_NAME = "actuals-template.xlsx";

function problem(status: number, code: string, detail: string): Response {
  return new Response(
    JSON.stringify({ type: `https://errors.pre-sales-agent/${code}`, title: code, status, code, detail }),
    { status, headers: { "Content-Type": PROBLEM_JSON, "Cache-Control": "no-store" } },
  );
}

/** A file name safe for a `Content-Disposition` header (the API's names are ASCII slugs). */
function safeName(name: string): string {
  const cleaned = name.replace(/[^A-Za-z0-9._-]/g, "");
  return cleaned || FALLBACK_NAME;
}

function failure(action: string, status: number, error: unknown): Response {
  const body = error as { code?: unknown; detail?: unknown } | undefined;
  const code = typeof body?.code === "string" ? body.code : "export_failed";
  const detail = typeof body?.detail === "string" ? body.detail : "";
  console.error(`${action} failed: status=${status} code=${code}`);
  return problem(status, code, detail);
}

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id } = await params;
  if (!UUID_RE.test(id)) {
    return problem(422, "validation_error", "Invalid fields: opportunity_id");
  }
  let api;
  try {
    api = await createServerApiClient();
  } catch (error) {
    if (error instanceof AccessTokenError) {
      return problem(401, "token_missing", "Sign in again to download the template.");
    }
    throw error;
  }
  try {
    const exported = await api.GET("/api/v1/opportunities/{opportunity_id}/actuals/template", {
      params: { path: { opportunity_id: id } },
    });
    if (!exported.data) {
      return failure("GET actuals template", exported.response.status, exported.error);
    }
    const { url, file_name } = exported.data;
    if (typeof url !== "string" || !url.startsWith(DOWNLOADS_PREFIX)) {
      console.error("GET actuals template failed: status=200 code=no_link");
      return problem(502, "export_failed", "The template came back without a file.");
    }
    const token = url.slice(DOWNLOADS_PREFIX.length);
    const downloaded = await api.GET("/api/v1/downloads/{token}", {
      params: { path: { token } },
      parseAs: "stream",
    });
    if (!downloaded.response.ok || !downloaded.data) {
      return failure("GET actuals template file", downloaded.response.status || 502, downloaded.error);
    }
    const headers = new Headers({
      "Cache-Control": "no-store",
      "Content-Type": XLSX,
      "Content-Disposition": `attachment; filename="${safeName(file_name)}"`,
      "X-Content-Type-Options": "nosniff",
    });
    const length = downloaded.response.headers.get("Content-Length");
    if (length) headers.set("Content-Length", length);
    return new Response(downloaded.data, { status: 200, headers });
  } catch (thrown) {
    const name = thrown instanceof Error ? thrown.name : typeof thrown;
    console.error(`GET actuals template failed: status=none code=${name}`);
    return problem(502, "api_unavailable", "The template service couldn't be reached.");
  }
}
