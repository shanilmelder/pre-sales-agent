// Server-only reads for the Opportunity lists and page. Authorization is decided by the API.
import "server-only";

import { cache } from "react";

import type { Filters } from "@/app/opportunities/filters";
import { createServerApiClient } from "@/lib/api/server";
import type { Opportunity, OpportunityFacets, OpportunityPage } from "@/lib/opportunities";
import { UUID_RE } from "@/lib/opportunities";
import type { AssessmentsView } from "@/lib/assessments";
import type { EstimateView } from "@/lib/estimates";
import type { GapList } from "@/lib/gaps";
import type { RedTeamView } from "@/lib/red-team";
import type { RequirementList } from "@/lib/requirements";
import type { Source } from "@/lib/sources";
import { TRACE_PAGE_SIZE, type TraceFilters, type TracePage } from "@/lib/trace";

export const PAGE_SIZE = 50;

export type ListScope = "mine" | "all";
export type ListResult = { kind: "ok"; page: OpportunityPage } | { kind: "error" };
export type FacetsResult = { kind: "ok"; facets: OpportunityFacets } | { kind: "error" };
export type SourcesResult = { kind: "ok"; sources: Source[] } | { kind: "error" };
export type RequirementsResult = { kind: "ok"; list: RequirementList } | { kind: "error" };
export type GapsResult = { kind: "ok"; list: GapList } | { kind: "error" };
export type EstimateResult = { kind: "ok"; estimate: EstimateView } | { kind: "error" };
export type TraceResult = { kind: "ok"; page: TracePage } | { kind: "error" };
export type RedTeamResult = { kind: "ok"; redTeam: RedTeamView } | { kind: "error" };
export type AssessmentsResult =
  | { kind: "ok"; assessments: AssessmentsView }
  | { kind: "error" };
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

/** `GET /api/v1/opportunities?scope=`. Filters apply to `scope=all` only (the API ignores
 * them for `mine`, so they aren't sent). */
export async function listOpportunities(
  scope: ListScope,
  page: number,
  filters: Filters = {},
): Promise<ListResult> {
  try {
    const api = await createServerApiClient();
    const query = { scope, page, page_size: PAGE_SIZE, ...(scope === "all" ? filters : {}) };
    const { data, response } = await api.GET("/api/v1/opportunities", { params: { query } });
    if (data) return { kind: "ok", page: data };
    console.error(`GET opportunities failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET opportunities failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/facets`: the owner and product choices for the filters. */
export async function getFacets(): Promise<FacetsResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/facets");
    if (data) return { kind: "ok", facets: data };
    console.error(`GET opportunity facets failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(
      `GET opportunity facets failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}`. A 404 means "doesn't exist or you may not see it".
 * Cached per request, so the workspace layout and its tab page share one fetch. */
export const getOpportunity = cache(async (id: unknown): Promise<GetResult> => {
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
});

/** `GET /api/v1/opportunities/{id}/sources`: the Opportunity's Sources, newest first. */
export async function listSources(id: string): Promise<SourcesResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/sources", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", sources: data.items };
    console.error(`GET sources failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET sources failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/requirements`: the active Requirements and the latest
 * extraction. */
export async function listRequirements(id: string): Promise<RequirementsResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/requirements",
      { params: { path: { opportunity_id: id } } },
    );
    if (data) return { kind: "ok", list: data };
    console.error(`GET requirements failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET requirements failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/gaps`: the open Gaps, ranked, and the latest detection
 * (Story 4.3). */
export async function listGaps(id: string): Promise<GapsResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/gaps", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", list: data };
    console.error(`GET gaps failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET gaps failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/estimate`: the current draft Estimate Version with its
 * server-calculated totals, and the latest draft run (Story 8.1). */
export async function getEstimate(id: string): Promise<EstimateResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/estimate", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", estimate: data };
    console.error(`GET estimate failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET estimate failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/red-team`: the current Red Team Review and latest run
 * (Story 6.5). Logs statuses only. */
export async function getRedTeam(id: string): Promise<RedTeamResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/red-team", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", redTeam: data };
    console.error(`GET red-team failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET red-team failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/assessments`: the latest assessment run with its tasks and
 * each specialist agent's current Assessment (Epic 5 slice 5A). Logs statuses only. */
export async function getAssessments(id: string): Promise<AssessmentsResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/assessments",
      { params: { path: { opportunity_id: id } } },
    );
    if (data) return { kind: "ok", assessments: data };
    console.error(`GET assessments failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET assessments failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/trace`: one page of the Decision Trace, newest first,
 * filtered by the URL's subject, actor and event types (Story 9.8). */
export async function listTrace(
  id: string,
  page: number,
  filters: TraceFilters = {},
): Promise<TraceResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const query = {
      page,
      page_size: TRACE_PAGE_SIZE,
      ...(filters.subject ? { subject_type: filters.subject } : {}),
      ...(filters.actor ? { actor_type: filters.actor } : {}),
      ...(filters.event ? { event_type: filters.event } : {}),
    };
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/trace", {
      params: { path: { opportunity_id: id }, query },
    });
    if (data) return { kind: "ok", page: data };
    console.error(`GET trace failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET trace failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}
