import type { Metadata } from "next";

import { OpportunityListPage } from "@/app/opportunities/list-page";

export const metadata: Metadata = { title: "Opportunities · Pre Sales Agent Framework" };

/** Every Opportunity the user can read, with filters for status, owner, product and target
 * proposal date (in the URL query); `?view=mine` narrows it to the user's own. */
export default async function OpportunitiesPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Called, not rendered as an element, so the page resolves to its finished tree.
  return OpportunityListPage({ searchParams });
}
