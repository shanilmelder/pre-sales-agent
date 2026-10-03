// The Opportunity workspace tabs: the one list behind the tab strip, the tab routes, the
// `1`–`9` keys and the cheat-sheet entry (EXPERIENCE.md, Opportunity workspace tabs).

export const WORKSPACE_TABS = [
  { slug: "overview", label: "Overview", key: "1" },
  { slug: "sources", label: "Sources", key: "2" },
  { slug: "requirements", label: "Requirements", key: "3" },
  { slug: "gaps", label: "Gaps", key: "4" },
  { slug: "assessments", label: "Assessments", key: "5" },
  { slug: "conflicts", label: "Conflicts", key: "6" },
  { slug: "estimate", label: "Estimate", key: "7" },
  { slug: "trace", label: "Trace", key: "8" },
  { slug: "actuals", label: "Actuals", key: "9" },
] as const;

export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];
export type WorkspaceTabSlug = WorkspaceTab["slug"];

/** The tab `/opportunities/{id}` itself shows. */
export const DEFAULT_TAB: WorkspaceTabSlug = "overview";

/** What an unbuilt tab shows. Never hidden or disabled. */
export const TAB_NOT_AVAILABLE = "Not available yet.";

export function isWorkspaceTab(slug: unknown): slug is WorkspaceTabSlug {
  return WORKSPACE_TABS.some((tab) => tab.slug === slug);
}

/** `/opportunities/{id}/{slug}`. */
export function tabHref(id: string, slug: WorkspaceTabSlug): string {
  return `/opportunities/${encodeURIComponent(id)}/${slug}`;
}

/** The tab for the workspace's selected route segment (`null` is `/opportunities/{id}`). */
export function activeTab(segment: string | null): WorkspaceTabSlug | null {
  if (segment === null) return DEFAULT_TAB;
  return isWorkspaceTab(segment) ? segment : null;
}
