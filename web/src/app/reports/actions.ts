"use server";

import { createServerApiClient } from "@/lib/api/server";
import {
  GROUP_BY,
  parseReportParams,
  reportQuery,
  type FailedAssumptionList,
  type GroupBy,
} from "@/lib/reports";

export type FailedListResult =
  | { kind: "ok"; list: FailedAssumptionList }
  | { kind: "forbidden" }
  | { kind: "error" };

const GROUP_KEY_MAX = 200;

/** `GET /api/v1/reports/failed-assumptions` (Story 10.4): one group's failed Assumptions under
 * the report's filters. `search` is the report's URL query (`/reports?…`), parsed again here
 * so a client can't send anything the URL couldn't carry. */
export async function loadFailedAssumptions(
  search: unknown,
  groupBy: unknown,
  groupKey: unknown,
): Promise<FailedListResult> {
  if (
    typeof search !== "string" ||
    typeof groupKey !== "string" ||
    groupKey.length === 0 ||
    groupKey.length > GROUP_KEY_MAX ||
    !GROUP_BY.some((g) => g.value === groupBy)
  ) {
    return { kind: "error" };
  }
  const params = { ...parseReportParams(new URLSearchParams(search)), groupBy: groupBy as GroupBy };
  try {
    const api = await createServerApiClient();
    const { data, response } = await api.GET("/api/v1/reports/failed-assumptions", {
      params: { query: { ...reportQuery(params), group_key: groupKey } },
    });
    if (data) return { kind: "ok", list: data };
    if (response.status === 403) return { kind: "forbidden" };
    console.error(`GET failed-assumptions report failed: status=${response.status}`);
    return { kind: "error" };
  } catch (thrown) {
    console.error(
      `GET failed-assumptions report failed: ${thrown instanceof Error ? thrown.name : "unknown"}`,
    );
    return { kind: "error" };
  }
}
