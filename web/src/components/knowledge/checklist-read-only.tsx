import { ChecklistItemView } from "@/components/knowledge/checklist-item-editor";
import { scopeText, type ChecklistVersion } from "@/lib/checklists";

/** A published Checklist version, read-only: its scope (unless `showScope` is false) and its
 * items in order. Shared by the Knowledge inspector and the Gaps tab (Story 4.1), which also
 * labels optional items. */
export function ChecklistReadOnly({
  checklist,
  showScope = true,
  optionalLabels = false,
}: {
  checklist: Pick<ChecklistVersion, "products" | "industry" | "integration_types" | "items">;
  showScope?: boolean;
  optionalLabels?: boolean;
}) {
  return (
    <>
      {showScope ? (
        <p className="text-meta">
          <span className="text-muted-foreground">Scope: </span>
          {scopeText(checklist)}
        </p>
      ) : null}
      <ol className="flex flex-col">
        {checklist.items.map((item, index) => (
          <ChecklistItemView
            key={item.id}
            item={item}
            index={index}
            optionalLabel={optionalLabels}
          />
        ))}
      </ol>
    </>
  );
}
