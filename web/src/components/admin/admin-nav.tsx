import { SegmentedNav } from "@/components/ui/segmented-nav";

const SECTIONS = [
  { href: "/admin/users", label: "Users & roles" },
  { href: "/admin/catalogue", label: "Catalogue" },
  { href: "/admin/evals", label: "Evals" },
] as const;

export const ADMIN_SUBTITLE = "Users and roles, the catalogue and evaluation results.";

/** Admin's sub-navigation: the sections as a segmented control, the current one marked. */
export function AdminNav({ current }: { current: (typeof SECTIONS)[number]["href"] }) {
  return <SegmentedNav label="Admin sections" items={SECTIONS} current={current} />;
}
