import { SegmentedNav } from "@/components/ui/segmented-nav";

export const KNOWLEDGE_SUBTITLE = "The sources the Agents draw on, and how fresh they are.";

/** Knowledge's sub-navigation: Sources is the one built section. */
export function KnowledgeNav() {
  return (
    <SegmentedNav
      label="Knowledge sections"
      items={[{ href: "/knowledge", label: "Sources" }]}
      current="/knowledge"
    />
  );
}
