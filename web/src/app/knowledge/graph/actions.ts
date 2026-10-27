"use server";

import { createServerApiClient } from "@/lib/api/server";
import type { KnowledgeGraph } from "@/lib/knowledge-graph";

export type GraphResult =
  | { kind: "ok"; graph: KnowledgeGraph }
  | { kind: "forbidden" }
  | { kind: "error" };

/** `GET /api/v1/knowledge/graph`: Products, Integration Types, Knowledge Sources and
 * Checklists with their status, score and links. Admins and Checklist editors only. */
export async function loadGraph(): Promise<GraphResult> {
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/knowledge/graph", {});
    if (data) return { kind: "ok", graph: data };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET knowledge graph failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(`GET knowledge graph failed: ${thrown instanceof Error ? thrown.name : "unknown"}`);
    return { kind: "error" };
  }
}
