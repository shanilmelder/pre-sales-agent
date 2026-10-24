import Link from "next/link";

import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CHECKLISTS_HREF, type CoverageIndustry } from "@/lib/coverage";

export const NO_INDUSTRIES = "No Checklists are scoped only by an industry.";

function countLabel(n: number): string {
  return `${n} ${n === 1 ? "Checklist" : "Checklists"}`;
}

/** The Checklists scoped only by an industry (no products, no Integration Types), so they
 * have no matrix cell: one padded row per industry, with how many and their names. */
export function IndustryChecklists({ industries }: { industries: readonly CoverageIndustry[] }) {
  return (
    <Card data-testid="industry-checklists" className="overflow-hidden">
      <CardHeader>
        <CardTitle>
          <h2 className="text-section">Industry Checklists</h2>
        </CardTitle>
        <CardDescription>
          Checklists scoped only by an industry apply to every Opportunity in it, so they are
          not in the matrix.
        </CardDescription>
      </CardHeader>
      {industries.length === 0 ? (
        <p className="border-t border-border px-5 py-[18px] text-text-secondary">{NO_INDUSTRIES}</p>
      ) : (
        <ul aria-label="Industry Checklists">
          {industries.map((entry) => (
            <li
              key={entry.industry}
              className="grid grid-cols-[200px_minmax(0,1fr)_auto] items-center gap-3 border-t border-border px-5 py-[18px]"
            >
              <span className="truncate text-body-strong" title={entry.industry}>
                {entry.industry}
              </span>
              <span className="truncate text-meta text-text-secondary" title={entry.names.join(", ")}>
                {entry.names.join(", ")}
              </span>
              <Link
                href={CHECKLISTS_HREF}
                aria-label={`${countLabel(entry.checklists)} for ${entry.industry}`}
                className="rounded-sm text-meta text-foreground underline underline-offset-2 outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-primary"
              >
                {countLabel(entry.checklists)}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
