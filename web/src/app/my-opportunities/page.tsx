import type { Metadata } from "next";

import { OpportunityListPage } from "@/app/opportunities/list-page";

export const metadata: Metadata = { title: "My Opportunities · Pre-Sales Agent" };

/** Opportunities the user owns or collaborates on. */
export default async function MyOpportunitiesPage({
  searchParams,
}: {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}) {
  // Called, not rendered as an element, so the page resolves to its finished tree.
  return OpportunityListPage({
    title: "My Opportunities",
    scope: "mine",
    basePath: "/my-opportunities",
    searchParams,
  });
}
