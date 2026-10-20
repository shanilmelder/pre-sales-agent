// @vitest-environment node
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiPost = vi.hoisted(() => vi.fn());
const createServerApiClient = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({ createServerApiClient }));

import { GET } from "./route";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const SOURCE_ID = "00000000-0000-7000-8000-000000000002";

function call(id = OPP_ID, sourceId = SOURCE_ID, version = "1") {
  return GET(new Request(`http://web/api/opportunities/${id}/sources/${sourceId}/versions/${version}/download`), {
    params: Promise.resolve({ id, sourceId, version }),
  });
}

beforeEach(() => {
  apiPost.mockReset();
  createServerApiClient.mockReset();
  createServerApiClient.mockResolvedValue({ POST: apiPost });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GET /api/opportunities/{id}/sources/{sourceId}/versions/{version}/download (Story 2.3)", () => {
  it("asks for a signed link and streams the original file back as an attachment", async () => {
    apiPost.mockResolvedValue({
      data: { url: "/api/v1/downloads/tok.sig", expires_at: "2026-10-21T00:00:00Z" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("original bytes", {
        status: 200,
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Disposition": 'attachment; filename="call.txt"',
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const resp = await call();

    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/sources/{source_id}/versions/{version}/download-link",
      { params: { path: { opportunity_id: OPP_ID, source_id: SOURCE_ID, version: 1 } } },
    );
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/api\/v1\/downloads\/tok\.sig$/);
    // A cancelled download aborts the backend fetch too.
    expect(fetchMock.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);
    expect(resp.status).toBe(200);
    expect(resp.headers.get("Content-Disposition")).toBe('attachment; filename="call.txt"');
    expect(resp.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(await resp.text()).toBe("original bytes");
  });

  it("passes the backend's 404 on as problem+json", async () => {
    apiPost.mockResolvedValue({
      data: undefined,
      error: { code: "not_found", detail: "No such Opportunity." },
      response: new Response(null, { status: 404 }),
    });

    const resp = await call();

    expect(resp.status).toBe(404);
    expect(resp.headers.get("Content-Type")).toBe("application/problem+json");
    expect(await resp.json()).toMatchObject({ code: "not_found" });
  });

  it("passes a refused (403) download on", async () => {
    apiPost.mockResolvedValue({
      data: { url: "/api/v1/downloads/tok.sig", expires_at: "2026-10-21T00:00:00Z" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 403 })));

    const resp = await call();

    expect(resp.status).toBe(403);
    expect(await resp.json()).toMatchObject({ code: "download_failed" });
  });

  it("refuses bad ids or versions without calling the backend", async () => {
    for (const resp of await Promise.all([
      call("nope"),
      call(OPP_ID, "nope"),
      call(OPP_ID, SOURCE_ID, "0"),
      call(OPP_ID, SOURCE_ID, "1.5"),
    ])) {
      expect(resp.status).toBe(422);
    }
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("answers 401 without a session", async () => {
    createServerApiClient.mockRejectedValue(new AccessTokenError("missing_session", "No session"));

    const resp = await call();

    expect(resp.status).toBe(401);
  });
});
