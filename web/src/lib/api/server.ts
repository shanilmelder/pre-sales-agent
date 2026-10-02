// Server-only API access: attaches the signed-in user's Auth0 access token.
import "server-only";

import { AccessTokenError } from "@auth0/nextjs-auth0/errors";
import { cache } from "react";

import { auth0 } from "@/lib/auth0";

import { createApiClient, type ApiClient, type components } from "./client";

export type Me = components["schemas"]["UserProfile"];

export type MeResult =
  | { kind: "ok"; me: Me }
  | { kind: "signed-out" }
  | { kind: "unavailable" };

/** An API client that sends `Authorization: Bearer <access token>`. Throws
 * `AccessTokenError` when there is no session or the token can't be refreshed. */
export async function createServerApiClient(): Promise<ApiClient> {
  const { token } = await auth0.getAccessToken();
  return createApiClient(undefined, { Authorization: `Bearer ${token}` });
}

/** The signed-in user from `GET /api/v1/me`, fetched once per request. */
export const getMe = cache(async (): Promise<MeResult> => {
  let api: ApiClient;
  try {
    api = await createServerApiClient();
  } catch (error) {
    if (error instanceof AccessTokenError) return { kind: "signed-out" };
    throw error;
  }
  try {
    const { data, error, response } = await api.GET("/api/v1/me");
    if (data) return { kind: "ok", me: data };
    const code = (error as { code?: unknown } | undefined)?.code;
    // Only a missing or expired token means "sign in again"; any other failure (e.g.
    // token_invalid from a misconfigured tenant) would loop sign-in forever.
    if (response.status === 401 && (code === "token_missing" || code === "token_expired")) {
      return { kind: "signed-out" };
    }
    console.error(`GET /api/v1/me failed: status=${response.status} code=${String(code)}`);
    return { kind: "unavailable" };
  } catch (thrown) {
    const name = thrown instanceof Error ? thrown.name : typeof thrown;
    console.error(`GET /api/v1/me failed: status=none code=${name}`);
    return { kind: "unavailable" };
  }
});
