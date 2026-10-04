// @vitest-environment node
import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";
import { UPLOAD_BODY_LIMIT_BYTES, UPLOAD_MAX_BYTES } from "./upload-limits";

const OPP_ID = "00000000-0000-7000-8000-000000000001";

/** The bytes a Server Action call carries for one upload: the multipart body the browser
 * builds for the form data (Next adds a few small fields of its own on top). */
async function uploadBodyBytes(fileSize: number): Promise<number> {
  const form = new FormData();
  form.append("opportunityId", OPP_ID);
  form.append("file", new File([new Uint8Array(fileSize)], `${"x".repeat(251)}.pdf`));
  const request = new Request("http://localhost/opportunities/x/sources", {
    method: "POST",
    body: form,
  });
  return (await request.arrayBuffer()).byteLength;
}

describe("upload body limits", () => {
  it("the API limit is 50 MB", () => {
    expect(UPLOAD_MAX_BYTES).toBe(52_428_800);
  });

  it("next.config raises the Server Action and proxy body limits to the upload limit", () => {
    expect(nextConfig.experimental?.serverActions?.bodySizeLimit).toBe(UPLOAD_BODY_LIMIT_BYTES);
    expect(nextConfig.experimental?.proxyClientMaxBodySize).toBe(UPLOAD_BODY_LIMIT_BYTES);
  });

  it("a 50 MB file's whole request fits through proxy.ts and the Server Action", async () => {
    const body = await uploadBodyBytes(UPLOAD_MAX_BYTES);
    expect(body).toBeGreaterThan(UPLOAD_MAX_BYTES);
    // Room left for the fields Next's action encoding adds.
    expect(body + 64 * 1024).toBeLessThanOrEqual(UPLOAD_BODY_LIMIT_BYTES);
  });

  it("a file just over 50 MB still reaches the API, which rejects it", async () => {
    const body = await uploadBodyBytes(UPLOAD_MAX_BYTES + 1);
    expect(body + 64 * 1024).toBeLessThanOrEqual(UPLOAD_BODY_LIMIT_BYTES);
  });
});
