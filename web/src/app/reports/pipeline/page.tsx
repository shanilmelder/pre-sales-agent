import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { getMe } from "@/lib/api/server";

import { ReportsFrame } from "../frame";

export const metadata: Metadata = { title: "Pipeline · Reports · Pre Sales Agent Framework" };

/** Reports > Pipeline: "Not available yet." until Story 10.7. */
export default async function ReportsPipelinePage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  return <ReportsFrame me={result.me} current="pipeline" />;
}
