// The Opportunity's live event stream (Story 5.2): `GET /api/opportunities/{id}/events`.
// Same-origin for the browser's EventSource: adds the signed-in user's access token, calls
// the backend's `GET /api/v1/opportunities/{id}/events` (Server-Sent Events, AD-30) and
// passes the stream through unbuffered, forwarding `Last-Event-ID` so a reconnect replays
// what it missed. Closing the browser's connection aborts the backend request. Failures come
// back as the backend's problem+json (or a local one); the client then falls back to
// polling. The session itself is guarded by `proxy.ts` (as for `estimate-export`).
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";

import { createServerApiClient } from "@/lib/api/server";
import { UUID_RE } from "@/lib/opportunities";

export const dynamic = "force-dynamic";

const PROBLEM_JSON = "application/problem+json";

function problem(status: number, code: string, detail: string): Response {
  return new Response(
    JSON.stringify({
      type: `https://errors.pre-sales-agent/${code}`,
      title: code,
      status,
      code,
      detail,
    }),
    {
      status,
      headers: { "Content-Type": PROBLEM_JSON, "Cache-Control": "no-store" },
    },
  );
}

export async function GET(
  request: Request,
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
      return problem(
        401,
        "token_missing",
        "Sign in again to follow live progress.",
      );
    }
    throw error;
  }
  const lastEventId = request.headers.get("Last-Event-ID");
  try {
    const { data, error, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/events",
      {
        params: {
          path: { opportunity_id: id },
          header: lastEventId ? { "last-event-id": lastEventId } : undefined,
        },
        parseAs: "stream",
        signal: request.signal,
      },
    );
    if (response.ok && data) {
      return new Response(data, {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          "X-Accel-Buffering": "no",
        },
      });
    }
    if (response.ok) {
      console.error(
        `GET events failed: status=${response.status} code=no_body`,
      );
      return problem(502, "events_failed", "The event stream came back empty.");
    }
    const body = error as { code?: unknown; detail?: unknown } | undefined;
    const code = typeof body?.code === "string" ? body.code : "events_failed";
    const detail = typeof body?.detail === "string" ? body.detail : "";
    console.error(`GET events failed: status=${response.status} code=${code}`);
    return problem(response.status, code, detail);
  } catch (thrown) {
    const name = thrown instanceof Error ? thrown.name : typeof thrown;
    if (name === "AbortError") return new Response(null, { status: 499 });
    console.error(`GET events failed: status=none code=${name}`);
    return problem(
      502,
      "api_unavailable",
      "The event stream couldn't be reached.",
    );
  }
}
