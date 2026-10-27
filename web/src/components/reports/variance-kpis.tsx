import { KpiTile } from "@/components/ui/kpi-tile";
import { formatWholeHours, plural, type VarianceKpis as Kpis } from "@/lib/reports";

const Note = ({ children }: { children: string }) => (
  <span className="text-meta text-muted-foreground">{children}</span>
);

/** The three KPI tiles: closed Opportunities, total variance, failed Assumptions. */
export function VarianceKpis({ kpis }: { kpis: Kpis }) {
  const kinds = kpis.failed_by_kind.map((k) => `${k.count} ${k.label}`).join(", ");
  return (
    <section aria-label="Estimate accuracy" className="grid grid-cols-3 gap-4">
      <KpiTile label="Closed Opportunities" value={kpis.closed_opportunities}>
        <Note>{`Actuals recorded on ${plural(kpis.opportunities, "Opportunity", "Opportunities")}`}</Note>
      </KpiTile>
      <KpiTile
        label="Total variance"
        value={
          <>
            {kpis.variance.display}
            <span className="sr-only">{` ${kpis.variance.sr_label}`}</span>
          </>
        }
      >
        <Note>{`${formatWholeHours(kpis.estimate_hours)} estimated, ${formatWholeHours(kpis.actual_hours)} actual`}</Note>
      </KpiTile>
      <KpiTile label="Failed Assumptions" value={kpis.failed_assumptions}>
        <Note>{kinds}</Note>
      </KpiTile>
    </section>
  );
}
