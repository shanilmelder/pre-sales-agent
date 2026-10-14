// @vitest-environment node
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.hoisted(() => vi.fn());
const createServerApiClient = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({ createServerApiClient }));

import { GET } from "./route";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const FRAME =
  'id: 1\nevent: workflows.task.started\ndata: {"summary": "pm_agent running"}\n\n';

function call(id: string, headers: Record<string, string> = {}) {
  return GET(
    new Request(`http://web/api/opportunities/${id}/events`, { headers }),
    {
      params: Promise.resolve({ id }),
    },
  );
}

beforeEach(() => {
  apiGet.mockReset();
  createServerApiClient.mockReset();
  createServerApiClient.mockResolvedValue({ GET: apiGet });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("GET /api/opportunities/{id}/events", () => {
  it("passes the backend's event stream through", async () => {
    const backend = new Response(FRAME, {
      headers: { "Content-Type": "text/event-stream" },
    });
    apiGet.mockResolvedValue({
      data: backend.body,
      error: undefined,
      response: backend,
    });

    const resp = await call(OPP_ID);

    expect(apiGet).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/events",
      {
        params: { path: { opportunity_id: OPP_ID }, header: undefined },
        parseAs: "stream",
        signal: expect.any(AbortSignal),
      },
    );
    expect(resp.status).toBe(200);
    expect(resp.headers.get("Content-Type")).toBe("text/event-stream");
    expect(resp.headers.get("Cache-Control")).toBe("no-cache, no-transform");
    expect(await resp.text()).toBe(FRAME);
  });

  it("forwards Last-Event-ID so a reconnect replays what it missed", async () => {
    const backend = new Response(FRAME);
    apiGet.mockResolvedValue({
      data: backend.body,
      error: undefined,
      response: backend,
    });

    await call(OPP_ID, { "Last-Event-ID": "01a1-last" });

    expect(apiGet.mock.calls[0][1].params.header).toEqual({
      "last-event-id": "01a1-last",
    });
  });

  it("passes a backend 404 on as problem+json", async () => {
    apiGet.mockResolvedValue({
      data: undefined,
      error: { code: "not_found", detail: "No such Opportunity." },
      response: new Response(null, { status: 404 }),
    });

    const resp = await call(OPP_ID);

    expect(resp.status).toBe(404);
    expect(resp.headers.get("Content-Type")).toBe("application/problem+json");
    expect(await resp.json()).toMatchObject({ status: 404, code: "not_found" });
  });

  it("answers 502 when the backend can't be reached", async () => {
    apiGet.mockRejectedValue(new TypeError("fetch failed"));

    const resp = await call(OPP_ID);

    expect(resp.status).toBe(502);
    expect(await resp.json()).toMatchObject({ code: "api_unavailable" });
  });

  it("refuses an id that isn't a UUID without calling the backend", async () => {
    const resp = await call("not-a-uuid");

    expect(resp.status).toBe(422);
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("answers 401 without a session", async () => {
    createServerApiClient.mockRejectedValue(
      new AccessTokenError("missing_session", "No session"),
    );

    const resp = await call(OPP_ID);

    expect(resp.status).toBe(401);
    expect(apiGet).not.toHaveBeenCalled();
  });
});
