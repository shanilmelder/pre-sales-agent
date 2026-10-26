import Link from "next/link";

import { getOpportunity, getReviewPanel } from "@/app/opportunities/data";
import { hasAccess } from "@/components/access-gate";
import { ReviewPanelLoader } from "@/components/opportunities/review-panel";
import { PAGE_PADDING } from "@/components/shell/page-header";
import { Card } from "@/components/ui/card";
import { getMe } from "@/lib/api/server";
import { PANEL_NOT_LOADED } from "@/lib/reviews";
import { tabHref } from "@/lib/workspace";

/** `/opportunities/{id}/estimate/reviews/{rid}` (Story 9.3, **Open in tab**): a Review
 * Request's review panel full width inside the workspace, the same panel the Inspector and the
 * Inbox show. Renders nothing when the user may not read the Opportunity; the workspace layout
 * shows why. */
export default async function ReviewPanelPage({
  params,
}: {
  params: Promise<{ id: string; rid: string }>;
}) {
  const result = await getMe();
  if (!hasAccess(result)) return null;
  const { id, rid } = await params;
  const loaded = await getOpportunity(id);
  if (loaded.kind !== "ok") return null;
  const { opportunity } = loaded;
  const panel = await getReviewPanel(opportunity.id, rid);

  return (
    <div className={`flex flex-col gap-4 ${PAGE_PADDING}`}>
      <Link
        href={tabHref(opportunity.id, "estimate")}
        className="self-start text-label text-primary-text outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
      >
        Back to the Estimate
      </Link>
      <Card className="p-6">
        {panel.kind === "ok" ? (
          <ReviewPanelLoader
            opportunityId={opportunity.id}
            requestId={panel.panel.request.id}
            initial={panel.panel}
            layout="page"
          />
        ) : (
          <p className="text-muted-foreground">{PANEL_NOT_LOADED}</p>
        )}
      </Card>
    </div>
  );
}
