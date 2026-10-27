// Server-only reads for the Opportunity lists and page. Authorization is decided by the API.
import "server-only";

import { cache } from "react";

import type { Filters } from "@/app/opportunities/filters";
import { createServerApiClient } from "@/lib/api/server";
import type { Opportunity, OpportunityFacets, OpportunityPage } from "@/lib/opportunities";
import { UUID_RE } from "@/lib/opportunities";
import type { ActualsView } from "@/lib/actuals";
import type { AssessmentsView } from "@/lib/assessments";
import type { ConflictsView } from "@/lib/conflicts";
import type { CriticView } from "@/lib/critic";
import type { EstimateView, VersionListItem } from "@/lib/estimates";
import type { GapList, GapsContext } from "@/lib/gaps";
import type { RedTeamView } from "@/lib/red-team";
import type { ReviewPanel, ReviewRequestsView } from "@/lib/reviews";
import type { OutdatedAssessment, RequirementList } from "@/lib/requirements";
import type { Source } from "@/lib/sources";
import type { SubmissionBlockersView } from "@/lib/submission";
import { TRACE_PAGE_SIZE, type TraceFilters, type TracePage } from "@/lib/trace";

export const PAGE_SIZE = 50;

export type ListScope = "mine" | "all";
export type ListResult = { kind: "ok"; page: OpportunityPage } | { kind: "error" };
export type FacetsResult = { kind: "ok"; facets: OpportunityFacets } | { kind: "error" };
export type SourcesResult = { kind: "ok"; sources: Source[] } | { kind: "error" };
export type RequirementsResult = { kind: "ok"; list: RequirementList } | { kind: "error" };
export type OutdatedAssessmentsResult =
  | { kind: "ok"; items: OutdatedAssessment[] }
  | { kind: "error" };
export type GapsResult = { kind: "ok"; list: GapList } | { kind: "error" };
export type GapsContextResult = { kind: "ok"; context: GapsContext } | { kind: "error" };
/** An active catalogue Integration Type, for tagging a Requirement (Story 4.1). */
export type IntegrationTypeOption = { id: string; name: string };
export type EstimateResult = { kind: "ok"; estimate: EstimateView } | { kind: "error" };
/** Story 10.1: the Actuals tab. */
export type ActualsResult = { kind: "ok"; actuals: ActualsView } | { kind: "error" };
/** Story 10.1: the active catalogue entries Unplanned work may name. */
export type CatalogueOptions = {
  integrationTypes: IntegrationTypeOption[];
  workPackages: IntegrationTypeOption[];
};
/** Story 9.7: the Opportunity's Estimate Versions, the Baseline first. */
export type EstimateVersionsResult =
  | { kind: "ok"; versions: VersionListItem[] }
  | { kind: "error" };
export type ReviewRequestsResult =
  | { kind: "ok"; reviews: ReviewRequestsView }
  | { kind: "error" };
export type TraceResult = { kind: "ok"; page: TracePage } | { kind: "error" };
export type RedTeamResult = { kind: "ok"; redTeam: RedTeamView } | { kind: "error" };
export type CriticResult = { kind: "ok"; critic: CriticView } | { kind: "error" };
export type ConflictsResult = { kind: "ok"; conflicts: ConflictsView } | { kind: "error" };
export type AssessmentsResult =
  | { kind: "ok"; assessments: AssessmentsView }
  | { kind: "error" };
export type GetResult =
  | { kind: "ok"; opportunity: Opportunity }
  | { kind: "not-found" }
  | { kind: "error" };

export { parsePage } from "@/lib/pagination";

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

/** `GET /api/v1/opportunities/{id}/assessments/outdated`: the current Assessments that used
 * Requirement versions that have changed since (Story 2.7). */
export async function listOutdatedAssessments(id: string): Promise<OutdatedAssessmentsResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/assessments/outdated",
      { params: { path: { opportunity_id: id } } },
    );
    if (data) return { kind: "ok", items: data.items };
    console.error(`GET outdated assessments failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(
      `GET outdated assessments failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
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

/** `GET /api/v1/opportunities/{id}/gaps/context` (Story 4.1): the applicable Checklists, the
 * untagged integration Requirements and the uncovered scope. Logs statuses only. */
export async function getGapsContext(id: string): Promise<GapsContextResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/gaps/context",
      { params: { path: { opportunity_id: id } } },
    );
    if (data) return { kind: "ok", context: data };
    console.error(`GET gaps context failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET gaps context failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** The active catalogue Integration Types (Story 4.1: the Requirement inspector's picker);
 * null when they can't be read. */
export async function listActiveIntegrationTypes(): Promise<IntegrationTypeOption[] | null> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/catalogue/entries", {
      params: { query: { kind: "integration_type" } },
    });
    if (data) return data.items.map((entry) => ({ id: entry.id, name: entry.name }));
    console.error(`GET integration types failed: status=${response.status}`);
    return null;
  } catch (thrown) {
    console.error(
      `GET integration types failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return null;
  }
}

/** Story 10.1: the active Integration Types and Work Packages, for Unplanned work; empty lists
 * when they can't be read. */
export async function listActiveCatalogue(): Promise<CatalogueOptions> {
  try {
    const api = await createServerApiClient();
    const [types, packages] = await Promise.all(
      (["integration_type", "work_package"] as const).map((kind) =>
        api.GET("/api/v1/catalogue/entries", { params: { query: { kind } } }),
      ),
    );
    const options = (found: typeof types) =>
      found.data?.items.map((entry) => ({ id: entry.id, name: entry.name })) ?? [];
    if (!types.data || !packages.data) {
      console.error(
        `GET catalogue failed: status=${types.response.status},${packages.response.status}`,
      );
    }
    return { integrationTypes: options(types), workPackages: options(packages) };
  } catch (thrown) {
    console.error(`GET catalogue failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { integrationTypes: [], workPackages: [] };
  }
}

/** Story 10.1: `GET /api/v1/opportunities/{id}/actuals`, the Actuals tab with server-calculated
 * variance. Logs statuses only. */
export async function getActuals(id: string): Promise<ActualsResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/actuals", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", actuals: data };
    console.error(`GET actuals failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET actuals failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/estimate`: the current Estimate Version (the draft, else
 * the latest submitted one) with its server-calculated totals and submission blockers, and
 * the latest draft run (Stories 8.1, 8.6). */
export async function getEstimate(id: string, version?: number | null): Promise<EstimateResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    // Story 9.7: `?version=n` reads that version, read only unless it is the current one.
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/estimate", {
      params: { path: { opportunity_id: id }, ...(version ? { query: { version } } : {}) },
    });
    if (data) return { kind: "ok", estimate: data };
    console.error(`GET estimate failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET estimate failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** Story 9.7: `GET /api/v1/opportunities/{id}/estimate-versions`, every Estimate Version with
 * the Baseline first. Logs statuses only. */
export async function getEstimateVersions(id: string): Promise<EstimateVersionsResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/estimate-versions",
      { params: { path: { opportunity_id: id } } },
    );
    if (data) return { kind: "ok", versions: data };
    console.error(`GET estimate versions failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(
      `GET estimate versions failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/review-requests`: the current Estimate Version's Review
 * Requests (Story 9.1). Logs statuses only. */
export async function getReviewRequests(id: string): Promise<ReviewRequestsResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/review-requests",
      { params: { path: { opportunity_id: id } } },
    );
    if (data) return { kind: "ok", reviews: data };
    console.error(`GET review requests failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(
      `GET review requests failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}

export type ReviewPanelResult =
  | { kind: "ok"; panel: ReviewPanel }
  | { kind: "not-found" }
  | { kind: "error" };

/** Story 9.3: `GET …/review-requests/{rid}/panel`. 404 (an unknown request, or one the caller
 * may no longer read, e.g. after escalating it) is `not-found`. */
export async function getReviewPanel(id: string, requestId: string): Promise<ReviewPanelResult> {
  if (!UUID_RE.test(id) || !UUID_RE.test(requestId)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/review-requests/{request_id}/panel",
      { params: { path: { opportunity_id: id, request_id: requestId } } },
    );
    if (data) return { kind: "ok", panel: data };
    if (response.status === 404) return { kind: "not-found" };
    console.error(`GET review panel failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET review panel failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

export type SubmissionBlockersResult =
  | { kind: "ok"; blockers: SubmissionBlockersView }
  | { kind: "error" };

/** `GET /api/v1/opportunities/{id}/submission-blockers`: the current Estimate Version's
 * submission blockers and whether the caller may submit it (Story 8.6). Logs statuses only. */
export async function getSubmissionBlockers(id: string): Promise<SubmissionBlockersResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET(
      "/api/v1/opportunities/{opportunity_id}/submission-blockers",
      { params: { path: { opportunity_id: id } } },
    );
    if (data) return { kind: "ok", blockers: data };
    console.error(`GET submission blockers failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(
      `GET submission blockers failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
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

/** `GET /api/v1/opportunities/{id}/critic`: the current Critic Review (Story 6.4). Logs
 * statuses only. */
export async function getCritic(id: string): Promise<CriticResult> {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/critic", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", critic: data };
    console.error(`GET critic failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET critic failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}

/** `GET /api/v1/opportunities/{id}/conflicts`: the Conflicts between the specialist
 * Assessments, open first, and the open-plus-escalated count (Story 6.1). Cached per
 * request, so the workspace layout's tab badge and the Conflicts tab share one fetch. Logs
 * statuses only. */
export const getConflicts = cache(async (id: string): Promise<ConflictsResult> => {
  if (!UUID_RE.test(id)) return { kind: "error" };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/opportunities/{opportunity_id}/conflicts", {
      params: { path: { opportunity_id: id } },
    });
    if (data) return { kind: "ok", conflicts: data };
    console.error(`GET conflicts failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET conflicts failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
});

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
