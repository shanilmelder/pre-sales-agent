import type { ReactNode } from "react";

import { ReportsNav } from "@/components/reports/reports-nav";
import { AppShell } from "@/components/shell/app-shell";
import { PAGE_SUBTITLES, PageContent, PageHeader } from "@/components/shell/page-header";
import type { Me } from "@/lib/api/server";
import { canReadReports } from "@/lib/navigation";
import { NOT_AVAILABLE_YET, type ReportTab } from "@/lib/reports";

export const NO_ACCESS = "You don't have access to Reports.";

/** "No access": a header band titled "No access" (not the section name) and the message. */
export function ReportsNoAccess() {
  return (
    <>
      <PageHeader title="No access" />
      <PageContent>
        <p>{NO_ACCESS}</p>
      </PageContent>
    </>
  );
}

/** The Reports frame: the header and sub-tabs around `children`, or "No access" without
 * `reporting.report.read` (display only: the API decides). */
export function ReportsFrame({
  me,
  current,
  forbidden = false,
  children,
}: {
  me: Me;
  current: ReportTab;
  /** The API answered 403. */
  forbidden?: boolean;
  children?: ReactNode;
}) {
  if (forbidden || !canReadReports(me.permissions)) {
    return (
      <AppShell me={me}>
        <ReportsNoAccess />
      </AppShell>
    );
  }
  return (
    <AppShell me={me}>
      <PageHeader title="Reports" subtitle={PAGE_SUBTITLES.reports} />
      <PageContent>
        <ReportsNav current={current} />
        {children ?? <p className="text-text-secondary">{NOT_AVAILABLE_YET}</p>}
      </PageContent>
    </AppShell>
  );
}
