import { ReportFilters } from "@/components/reports/report-filters";
import { VarianceKpis } from "@/components/reports/variance-kpis";
import { VarianceTable } from "@/components/reports/variance-table";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import {
  CALIBRATION_TITLE,
  EMPTY_BODY,
  EMPTY_TITLE,
  NO_MATCH,
  type EstimateVsActualReport,
  type ReportParams,
} from "@/lib/reports";

/** Reports > Estimate vs actual: the toolbar, three KPI tiles, the grouped table and the
 * calibration strip, or the empty state when no Actual is recorded yet. */
export function EstimateVsActual({
  report,
  params,
}: {
  report: EstimateVsActualReport;
  params: ReportParams;
}) {
  if (!report.has_actuals) return <EmptyTabCard title={EMPTY_TITLE} body={EMPTY_BODY} />;
  return (
    <>
      <ReportFilters params={params} options={report.options} />
      {report.kpis ? (
        <>
          <VarianceKpis kpis={report.kpis} />
          <VarianceTable
            groups={report.groups}
            groupBy={report.group_by}
            closedOpportunities={report.kpis.closed_opportunities}
            params={params}
          />
        </>
      ) : (
        <p className="text-text-secondary">{NO_MATCH}</p>
      )}
      <div
        role="note"
        className="flex flex-wrap items-center gap-3 rounded-[10px] bg-primary-tint px-4 py-3 text-[13px] text-primary-text"
      >
        <span className="font-semibold">{CALIBRATION_TITLE}</span>
        <span className="text-foreground">{report.calibration.message}</span>
      </div>
    </>
  );
}
