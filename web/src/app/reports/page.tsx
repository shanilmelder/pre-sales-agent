import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { EstimateVsActual } from "@/components/reports/estimate-vs-actual";
import { getMe } from "@/lib/api/server";
import { canReadReports } from "@/lib/navigation";
import { parseReportParams } from "@/lib/reports";

import { loadEstimateVsActual } from "./data";
import { ReportsFrame } from "./frame";

export const metadata: Metadata = { title: "Reports · Pre Sales Agent Framework" };

/** Reports > Estimate vs actual (Story 10.3): KPIs and the variance table grouped and filtered
 * by the URL's parameters. */
export default async function ReportsPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  if (!canReadReports(result.me.permissions)) return <ReportsFrame me={result.me} current="variance" />;

  const params = parseReportParams(await searchParams);
  const report = await loadEstimateVsActual(params);
  return (
    <ReportsFrame me={result.me} current="variance" forbidden={report.kind === "forbidden"}>
      {report.kind === "ok" ? (
        <EstimateVsActual report={report.report} params={params} />
      ) : (
        <p>The platform is not reachable right now. Try again in a moment.</p>
      )}
    </ReportsFrame>
  );
}
