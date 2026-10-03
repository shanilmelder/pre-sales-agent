"use server";

import { createServerApiClient } from "@/lib/api/server";
import type { components } from "@/lib/api/client";
import type { Role } from "@/lib/navigation";
import { isRole } from "@/lib/roles";

export type AdminUser = components["schemas"]["AdminUser"];

export type ChangeRoleInput = {
  userId: string;
  role: Role;
  /** True to assign the role, false to remove it. */
  assigned: boolean;
  /** The `row_version` the inspector was opened with; sent as `If-Match`. */
  rowVersion: number;
};

export type ChangeRoleResult =
  | { kind: "ok"; user: AdminUser }
  /** 412: someone changed the user first. `changedBy` is null when nobody is recorded. */
  | { kind: "stale"; changedBy: string | null }
  /** 409, e.g. `last_administrator`, with the API's detail text. */
  | { kind: "conflict"; detail: string }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

export type LoadUserResult =
  | { kind: "ok"; user: AdminUser }
  | { kind: "forbidden" }
  | { kind: "not-found" }
  | { kind: "error" };

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isInput(input: unknown): input is ChangeRoleInput {
  if (typeof input !== "object" || input === null) return false;
  const { userId, role, assigned, rowVersion } = input as Record<string, unknown>;
  return (
    typeof userId === "string" &&
    UUID_RE.test(userId) &&
    isRole(role) &&
    typeof assigned === "boolean" &&
    typeof rowVersion === "number" &&
    Number.isSafeInteger(rowVersion) &&
    rowVersion >= 0
  );
}

function problemCode(error: unknown): string | undefined {
  const code = (error as { code?: unknown } | undefined)?.code;
  return typeof code === "string" ? code : undefined;
}

function problemDetail(error: unknown): string | undefined {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  return typeof detail === "string" ? detail : undefined;
}

/** `GET /api/v1/admin/users/{id}`. Authorization is decided by the API. */
export async function loadUser(userId: unknown): Promise<LoadUserResult> {
  if (typeof userId !== "string" || !UUID_RE.test(userId)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/admin/users/{user_id}", {
      params: { path: { user_id: userId } },
    });
    if (data) return { kind: "ok", user: data };
    if (response.status === 403) return { kind: "forbidden" };
    if (response.status === 404) return { kind: "not-found" };
    console.error(`GET admin user failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET admin user failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** Assigns or removes one role with `If-Match`. Never retries or overwrites on 412. */
export async function changeRole(input: unknown): Promise<ChangeRoleResult> {
  if (!isInput(input)) return { kind: "error" };
  const { userId, role, assigned, rowVersion } = input;
  try {
    const api = await createServerApiClient();
    const init = {
      params: {
        path: { user_id: userId, role },
        header: { "If-Match": `"${rowVersion}"` },
      },
    };
    const { data, error, response } = assigned
      ? await api.PUT("/api/v1/admin/users/{user_id}/roles/{role}", init)
      : await api.DELETE("/api/v1/admin/users/{user_id}/roles/{role}", init);
    if (data) return { kind: "ok", user: data };
    switch (response.status) {
      case 412: {
        const current = await loadUser(userId);
        return { kind: "stale", changedBy: current.kind === "ok" ? current.user.last_changed_by : null };
      }
      case 409:
        return { kind: "conflict", detail: problemDetail(error) ?? "This change is not allowed." };
      case 403:
        return { kind: "forbidden" };
      case 404:
        return { kind: "not-found" };
      default:
        console.error(`change role failed: status=${response.status} code=${String(problemCode(error))}`);
        return { kind: "error" };
    }
  } catch (thrown) {
    console.error(`change role failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}
