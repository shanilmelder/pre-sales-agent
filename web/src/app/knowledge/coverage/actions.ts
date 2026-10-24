"use server";

import { createServerApiClient } from "@/lib/api/server";
import type { KnowledgeCoverage } from "@/lib/coverage";

export type CoverageResult =
  | { kind: "ok"; coverage: KnowledgeCoverage }
  | { kind: "forbidden" }
  | { kind: "error" };

/** `GET /api/v1/knowledge/coverage`: products by active Integration Types, and the
 * industry-only Checklists. */
export async function loadCoverage(): Promise<CoverageResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/knowledge/coverage", {});
    if (data) return { kind: "ok", coverage: data };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET coverage failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET coverage failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}
