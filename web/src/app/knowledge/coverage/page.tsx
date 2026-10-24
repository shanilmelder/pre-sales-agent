import type { Metadata } from "next";

import { AccessGate, hasAccess } from "@/components/access-gate";
import { CoverageMatrix } from "@/components/knowledge/coverage-matrix";
import { IndustryChecklists } from "@/components/knowledge/industry-checklists";
import { KnowledgeNav } from "@/components/knowledge/knowledge-nav";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import { getMe } from "@/lib/api/server";

import { loadCoverage } from "./actions";

export const metadata: Metadata = { title: "Coverage · Knowledge · Pre-Sales Agent" };

/** Knowledge → Coverage (Story 3.5): products by active Integration Types, and the
 * industry-only Checklists. */
export default async function KnowledgeCoveragePage() {
  const result = await getMe();
  if (!hasAccess(result)) return <AccessGate result={result} />;

  const coverage = await loadCoverage();

  return (
    <AppShell me={result.me}>
      <PageHeader title="Knowledge" subtitle={PAGE_SUBTITLES.knowledge} />
      <PageContent>
        <KnowledgeNav current="coverage" />
        {coverage.kind === "ok" ? (
          <>
            <CoverageMatrix coverage={coverage.coverage} />
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
