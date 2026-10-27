import type { Metadata } from "next";
import Link from "next/link";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { CoverageMatrix } from "@/components/knowledge/coverage-matrix";
import { IndustryChecklists } from "@/components/knowledge/industry-checklists";
import { KnowledgeNav } from "@/components/knowledge/knowledge-nav";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";
import { canAuthor } from "@/lib/checklists";
import { COVERAGE_HREF, narrowCoverage, seededFilters } from "@/lib/coverage";

import { loadCoverage } from "./actions";

export const metadata: Metadata = { title: "Coverage · Knowledge · Pre-Sales Agent" };

/** Knowledge → Coverage (Story 3.5): products by active Integration Types, and the
 * industry-only Checklists. `?product=` or `?integration_type=` (the Graph's View coverage)
 * narrows the matrix to that row or column. */
export default async function KnowledgeCoveragePage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
} = {}) {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;
  const filter = seededFilters(await searchParams);
  const narrowed = filter.product !== "" || filter.integrationTypeId !== "";

  const coverage = await loadCoverage();

  return (
    <AppShell me={result.me}>
      <PageHeader title="Knowledge" subtitle={PAGE_SUBTITLES.knowledge} />
      <PageContent>
        <KnowledgeNav current="coverage" showGraph={canAuthor(result.me.permissions)} />
        {coverage.kind === "ok" ? (
          <>
            {narrowed ? (
              <p className="text-meta text-text-secondary">
                Showing one {filter.product !== "" ? "product" : "Integration Type"}.{" "}
                <Link href={COVERAGE_HREF} className="text-link underline-offset-2 hover:underline">
                  Show all coverage
                </Link>
              </p>
            ) : null}
            <CoverageMatrix
              coverage={narrowed ? narrowCoverage(coverage.coverage, filter) : coverage.coverage}
            />
            <IndustryChecklists industries={coverage.coverage.industries} />
          </>
        ) : coverage.kind === "forbidden" ? (
          <p>You do not have access to Knowledge coverage.</p>
        ) : (
          <p>The platform is not reachable right now. Try again in a moment.</p>
        )}
      </PageContent>
    </AppShell>
  );
}
