"use server";

import { createServerApiClient } from "@/lib/api/server";
import type { ApprovedModel, ModelProfile } from "@/lib/model-profiles";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ProfileResult =
  | { kind: "ok"; profile: ModelProfile }
  /** 409, with the API's sentence: a duplicate name, in use, or not retestable. */
  | { kind: "conflict"; detail: string }
  /** 422, with the API's sentence: a bad field or a model off the allowlist. */
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type ApprovedResult =
  | { kind: "ok"; model: ApprovedModel }
  | { kind: "conflict"; detail: string }
  | { kind: "invalid"; detail: string }
  | { kind: "forbidden" }
  | { kind: "error" };

export type RemoveResult = { kind: "ok" } | { kind: "forbidden" } | { kind: "error" };

export type ProfilesResult =
  | { kind: "ok"; profiles: ModelProfile[] }
  | { kind: "forbidden" }
  | { kind: "error" };

function detailOf(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : undefined;
}

function logged(what: string, thrown: unknown): { kind: "error" } {
  console.error(`${what} failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
  return { kind: "error" };
}

/** `GET /api/v1/registry/model-profiles`: re-read while a test is pending. */
export async function loadProfiles(): Promise<ProfilesResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/registry/model-profiles");
    if (data) return { kind: "ok", profiles: data.items };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET model profiles failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return logged("GET model profiles", thrown);
  }
}

function profileOutcome(
  result: { data?: ModelProfile; error?: unknown; response: Response },
  what: string,
): ProfileResult {
  if (result.data) return { kind: "ok", profile: result.data };
  switch (result.response.status) {
    case 409:
      return { kind: "conflict", detail: detailOf(result.error) ?? "This can't be done now." };
    case 422:
      return { kind: "invalid", detail: detailOf(result.error) ?? "This value is not valid." };
    case 403:
      return { kind: "forbidden" };
    case 404:
      return { kind: "not-found" };
    default:
      console.error(`${what} failed: status=${result.response.status}`);
      return { kind: "error" };
  }
}

export type NewProfileInput = {
  name: string;
  provider: ModelProfile["provider"];
  model: string;
  num_ctx: number;
  temperature: number | null;
  reasoning_effort: "low" | "medium" | "high" | null;
};

/** `POST /api/v1/registry/model-profiles`. The API validates everything again. */
export async function createProfile(input: NewProfileInput): Promise<ProfileResult> {
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/registry/model-profiles", { body: input });
    return profileOutcome(result, "create model profile");
  } catch (thrown) {
    return logged("create model profile", thrown);
  }
}

/** `POST …/test`: a `failed` profile back to pending. */
export async function retestProfile(profileId: unknown): Promise<ProfileResult> {
  if (typeof profileId !== "string" || !UUID_RE.test(profileId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/registry/model-profiles/{profile_id}/test", {
      params: { path: { profile_id: profileId } },
    });
    return profileOutcome(result, "retest model profile");
  } catch (thrown) {
    return logged("retest model profile", thrown);
  }
}

/** `POST …/retire`. */
export async function retireProfile(profileId: unknown): Promise<ProfileResult> {
  if (typeof profileId !== "string" || !UUID_RE.test(profileId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const result = await api.POST("/api/v1/registry/model-profiles/{profile_id}/retire", {
      params: { path: { profile_id: profileId } },
    });
    return profileOutcome(result, "retire model profile");
  } catch (thrown) {
    return logged("retire model profile", thrown);
  }
}

/** `POST /api/v1/registry/approved-models`. */
export async function addApprovedModel(input: {
  provider: ApprovedModel["provider"];
  model: string;
}): Promise<ApprovedResult> {
  try {
    const api = await createServerApiClient();
    const { data, error, response } = await api.POST("/api/v1/registry/approved-models", {
      body: input,
    });
    if (data) return { kind: "ok", model: data };
    switch (response.status) {
      case 409:
        return { kind: "conflict", detail: detailOf(error) ?? "This model is already approved." };
      case 422:
        return { kind: "invalid", detail: detailOf(error) ?? "This value is not valid." };
      case 403:
        return { kind: "forbidden" };
      default:
        console.error(`add approved model failed: status=${response.status}`);
        return { kind: "error" };
    }
  } catch (thrown) {
    return logged("add approved model", thrown);
  }
}

/** `DELETE /api/v1/registry/approved-models/{id}`. An entry already gone counts as removed. */
export async function removeApprovedModel(approvedId: unknown): Promise<RemoveResult> {
  if (typeof approvedId !== "string" || !UUID_RE.test(approvedId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { response } = await api.DELETE("/api/v1/registry/approved-models/{approved_id}", {
      params: { path: { approved_id: approvedId } },
    });
    if (response.ok || response.status === 404) return { kind: "ok" };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`remove approved model failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    return logged("remove approved model", thrown);
  }
}
