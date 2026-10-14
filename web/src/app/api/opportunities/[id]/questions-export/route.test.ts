// @vitest-environment node
import { AccessTokenError } from "@auth0/nextjs-auth0/errors";
import { beforeEach, describe, expect, it, vi } from "vitest";

const apiGet = vi.hoisted(() => vi.fn());
const apiPost = vi.hoisted(() => vi.fn());
const createServerApiClient = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/server", () => ({ createServerApiClient }));

import { POST } from "./route";

const OPP_ID = "00000000-0000-7000-8000-000000000001";
const DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const TOKEN = "eyJoIjoiYSJ9.sig";

function call(id: string, format: string | null) {
  const query = format === null ? "" : `?format=${format}`;
  return POST(
    new Request(`http://web/api/opportunities/${id}/questions-export${query}`, { method: "POST" }),
    { params: Promise.resolve({ id }) },
  );
}

function exported(format: string, fileName: string) {
  return {
    data: {
      format,
      question_count: 2,
      text: null,
      url: `/api/v1/downloads/${TOKEN}`,
      file_name: fileName,
      expires_at: "2026-10-14T10:00:00Z",
    },
    error: undefined,
    response: new Response(null, { status: 200 }),
  };
}

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  createServerApiClient.mockReset();
  createServerApiClient.mockResolvedValue({ GET: apiGet, POST: apiPost });
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("POST /api/opportunities/{id}/questions-export", () => {
  it("exports, fetches the signed link server-side and streams the file back", async () => {
    apiPost.mockResolvedValue(exported("docx", "clarification-questions-acme-2026-10-14.docx"));
    const file = new Response("PK-bytes", {
      headers: { "Content-Type": "application/octet-stream", "Content-Length": "8" },
    });
    apiGet.mockResolvedValue({ data: file.body, error: undefined, response: file });

    const resp = await call(OPP_ID, "docx");

    expect(apiPost).toHaveBeenCalledWith(
      "/api/v1/opportunities/{opportunity_id}/clarification-questions/export",
      { params: { path: { opportunity_id: OPP_ID } }, body: { format: "docx" } },
    );
    expect(apiGet).toHaveBeenCalledWith("/api/v1/downloads/{token}", {
      params: { path: { token: TOKEN } },
      parseAs: "stream",
    });
    expect(resp.status).toBe(200);
    expect(resp.headers.get("Content-Type")).toBe(DOCX);
    expect(resp.headers.get("Content-Disposition")).toBe(
      'attachment; filename="clarification-questions-acme-2026-10-14.docx"',
    );
    expect(resp.headers.get("Cache-Control")).toBe("no-store");
    expect(await resp.text()).toBe("PK-bytes");
  });

  it("serves the email draft as message/rfc822", async () => {
    apiPost.mockResolvedValue(exported("eml", "clarification-questions-acme-2026-10-14.eml"));
    const file = new Response("X-Unsent: 1");
    apiGet.mockResolvedValue({ data: file.body, error: undefined, response: file });

    const resp = await call(OPP_ID, "eml");

    expect(resp.headers.get("Content-Type")).toBe("message/rfc822");
    expect(await resp.text()).toBe("X-Unsent: 1");
  });

  it("passes a backend 409 on as problem+json, fetching no file", async () => {
    apiPost.mockResolvedValue({
      data: undefined,
      error: { code: "no_approved_questions", detail: "Approve some first." },
      response: new Response(null, { status: 409 }),
    });

    const resp = await call(OPP_ID, "docx");

    expect(resp.status).toBe(409);
    expect(resp.headers.get("Content-Type")).toBe("application/problem+json");
    expect(await resp.json()).toMatchObject({ status: 409, code: "no_approved_questions" });
    expect(apiGet).not.toHaveBeenCalled();
  });

  it("a failed download is passed on", async () => {
    apiPost.mockResolvedValue(exported("docx", "x.docx"));
    apiGet.mockResolvedValue({
      data: undefined,
      error: { code: "forbidden", detail: "Expired." },
      response: new Response(null, { status: 403 }),
    });

    const resp = await call(OPP_ID, "docx");

    expect(resp.status).toBe(403);
    expect(await resp.json()).toMatchObject({ code: "forbidden" });
  });

  it("refuses a bad id or format, and copy, without calling the API", async () => {
    for (const [id, format] of [
      ["nope", "docx"],
      [OPP_ID, "copy"],
      [OPP_ID, null],
    ] as const) {
      const resp = await call(id, format);
      expect(resp.status).toBe(422);
    }
    expect(createServerApiClient).not.toHaveBeenCalled();
  });

  it("asks to sign in again without a session", async () => {
    createServerApiClient.mockRejectedValue(new AccessTokenError("missing_session", "No session"));

    const resp = await call(OPP_ID, "eml");

    expect(resp.status).toBe(401);
    expect(await resp.json()).toMatchObject({ code: "token_missing" });
  });

  it("a thrown fetch is a 502", async () => {
    apiPost.mockRejectedValue(new TypeError("fetch failed"));

    const resp = await call(OPP_ID, "docx");

    expect(resp.status).toBe(502);
    expect(await resp.json()).toMatchObject({ code: "api_unavailable" });
  });
});
