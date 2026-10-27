// Server-only reads for Reports (Story 10.3). Authorization is decided by the API.
import "server-only";

import { createServerApiClient } from "@/lib/api/server";
import { reportQuery, type EstimateVsActualReport, type ReportParams } from "@/lib/reports";

export type ReportResult =
  | { kind: "ok"; report: EstimateVsActualReport }
  | { kind: "forbidden" }
  | { kind: "error" };

/** `GET /api/v1/reports/estimate-vs-actual`: the KPIs and grouped table for `params`. */
export async function loadEstimateVsActual(params: ReportParams): Promise<ReportResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/reports/estimate-vs-actual", {
      params: { query: reportQuery(params) },
    });
    if (data) return { kind: "ok", report: data };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET estimate-vs-actual report failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(
      `GET estimate-vs-actual report failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}
