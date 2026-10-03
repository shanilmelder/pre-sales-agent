import type { Metadata } from "next";

import { OpportunityListPage } from "@/app/opportunities/list-page";

export const metadata: Metadata = { title: "All Opportunities · Pre-Sales Agent" };

/** Every Opportunity the user can read. Filters arrive in Story 1.7 Part B. */
export default async function OpportunitiesPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Called, not rendered as an element, so the page resolves to its finished tree.
  return OpportunityListPage({
    title: "All Opportunities",
    scope: "all",
    basePath: "/opportunities",
    searchParams,
  });
}
