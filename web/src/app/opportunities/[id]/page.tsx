import { OverviewTab } from "@/app/opportunities/[id]/overview";

/** `/opportunities/{id}`: the workspace's Overview tab. */
export default async function OpportunityPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // Awaited here (not rendered as an element) so the page resolves to plain JSX.
  return await OverviewTab({ id });
}
