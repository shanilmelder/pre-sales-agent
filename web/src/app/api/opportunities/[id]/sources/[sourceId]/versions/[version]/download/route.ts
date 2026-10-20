// Opportunity Source file download (Story 2.3): `GET /api/opportunities/{id}/sources/
// {sourceId}/versions/{version}/download`. Mirrors the Knowledge download route: asks the
// backend for a short-lived signed link to the version's original file (as the signed-in
// user, so the backend checks that they can read the Opportunity), fetches it and streams it
// back as an attachment. Failures come back as problem+json. Logs carry status codes only,
// never file names. The session itself is guarded by `proxy.ts`.
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";

import { createServerApiClient } from "@/lib/api/server";
import { UUID_RE } from "@/lib/opportunities";

export const dynamic = "force-dynamic";

const PROBLEM_JSON = "application/problem+json";
const API_URL = process.env.PSA_API_URL ?? "http://localhost:8000";

function problem(status: number, code: string, detail: string): Response {
  return new Response(
    JSON.stringify({ type: `https://errors.pre-sales-agent/${code}`, title: code, status, code, detail }),
    { status, headers: { "Content-Type": PROBLEM_JSON, "Cache-Control": "no-store" } },
  );
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string; sourceId: string; version: string }> },
): Promise<Response> {
  const { id, sourceId, version } = await params;
  const versionNumber = Number(version);
  if (
    !UUID_RE.test(id) ||
    !UUID_RE.test(sourceId) ||
    !Number.isSafeInteger(versionNumber) ||
    versionNumber < 1
  ) {
    return problem(422, "validation_error", "Invalid fields: opportunity_id, source_id, version");
  }
  let api;
  try {
    api = await createServerApiClient();
  } catch (error) {
    if (error instanceof AccessTokenError) {
      return problem(401, "token_missing", "Sign in again to download.");
    }
    throw error;
  }
  try {
    const link = await api.POST(
      "/api/v1/opportunities/{opportunity_id}/sources/{source_id}/versions/{version}/download-link",
      { params: { path: { opportunity_id: id, source_id: sourceId, version: versionNumber } } },
    );
    if (!link.data) {
      const body = link.error as { code?: unknown; detail?: unknown } | undefined;
      const code = typeof body?.code === "string" ? body.code : "download_failed";
      const detail = typeof body?.detail === "string" ? body.detail : "";
      console.error(`POST source download link failed: status=${link.response.status} code=${code}`);
      return problem(link.response.status, code, detail);
    }
    const file = await fetch(new URL(link.data.url, API_URL), {
      cache: "no-store",
      signal: request.signal,
    });
    if (!file.ok || !file.body) {
      console.error(`GET source download failed: status=${file.status}`);
      return problem(file.ok ? 502 : file.status, "download_failed", "The file couldn't be downloaded.");
    }
    const headers = new Headers({ "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of ["Content-Type", "Content-Disposition", "Content-Length"]) {
      const value = file.headers.get(name);
      if (value) headers.set(name, value);
    }
    return new Response(file.body, { status: 200, headers });
  } catch (thrown) {
    const name = thrown instanceof Error ? thrown.name : typeof thrown;
    console.error(`GET source download failed: status=none code=${name}`);
    return problem(502, "api_unavailable", "The download service couldn't be reached.");
  }
}
