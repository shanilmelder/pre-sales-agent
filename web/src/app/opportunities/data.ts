// Server-only reads for the Opportunity lists and page. Authorization is decided by the API.
import "server-only";

import { createServerApiClient } from "@/lib/api/server";
import type { Opportunity, OpportunityPage } from "@/lib/opportunities";
import { UUID_RE } from "@/lib/opportunities";

export const PAGE_SIZE = 50;

export type ListScope = "mine" | "all";
export type ListResult = { kind: "ok"; page: OpportunityPage } | { kind: "error" };
export type GetResult =
  | { kind: "ok"; opportunity: Opportunity }
  | { kind: "not-found" }
  | { kind: "error" };

/** `?page=` as a positive integer (1 for anything else). */
export function parsePage(value: string | string[] | undefined): number {
  const raw = Array.isArray(value) ? value[0] : value;
  if (!raw || !/^[1-9]\d{0,5}$/.test(raw)) return 1;
  return Number(raw);
}

/** `GET /api/v1/opportunities?scope=`. */
export async function listOpportunities(scope: ListScope, page: number): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities", {
      params: { query: { scope, page, page_size: PAGE_SIZE } },
    });
    if (data) return { kind: "ok", page: data };
    console.error(`GET opportunities failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET opportunities failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}`. A 404 means "doesn't exist or you may not see it". */
export async function getOpportunity(id: unknown): Promise<GetResult> {
  if (typeof id !== "string" || !UUID_RE.test(id)) return { kind: "not-found" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", opportunity: data };
    if (response.status === 404) return { kind: "not-found" };
    console.error(`GET opportunity failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET opportunity failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}
