import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { getMe } from "@/lib/api/server";

import { ReportsFrame } from "../frame";

export const metadata: Metadata = { title: "Cost and usage · Reports · Pre Sales Agent Framework" };

/** Reports > Cost and usage: "Not available yet." until Story 7.5. */
export default async function ReportsCostPage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  return <ReportsFrame me={result.me} current="cost" />;
}
