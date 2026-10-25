import {
  changedFields,
  configValue,
  fieldLabel,
  permissionChanges,
  type AgentConfigVersion,
} from "@/lib/admin";

function Line({ sign, label, children }: { sign: "−" | "+"; label: string; children: string }) {
  return (
    <p className="flex gap-2 rounded-sm bg-diff-tint px-1.5 py-0.5">
      <span aria-hidden="true" className="shrink-0 text-muted-foreground">
        {sign}
      </span>
      <span className="sr-only">{`${label}: `}</span>
      <span className="min-w-0 font-mono text-meta break-words">{children}</span>
    </p>
  );
}

/** The fields that differ between two config versions (Story 7.3): each as a `−` line (the
 * `before` value) and a `+` line (the `after` value) on the diff tint, never green or red.
 * Tool permissions are shown as removed (`−`) and granted (`+`). */
export function AgentConfigDiff({
  before,
  after,
}: {
  before: AgentConfigVersion;
  after: AgentConfigVersion;
}) {
  const fields = changedFields(before, after);
  if (fields.length === 0) {
    return <p className="text-meta text-muted-foreground">No config differences.</p>;
  }
  return (
    <dl className="flex flex-col gap-2" data-testid="agent-config-diff">
      {fields.map((field) => {
        if (field === "tool_permissions") {
          const { granted, removed } = permissionChanges(
            before.tool_permissions,
            after.tool_permissions,
          );
          return (
            <div key={field} data-changed={field} className="flex flex-col gap-0.5">
              <dt className="text-label">{fieldLabel(field)}</dt>
              <dd className="flex flex-col gap-0.5">
                {removed.map((p) => (
                  <Line key={`-${p}`} sign="−" label="Removed">
                    {p}
                  </Line>
                ))}
                {granted.map((p) => (
                  <Line key={`+${p}`} sign="+" label="Granted">
                    {p}
                  </Line>
                ))}
              </dd>
            </div>
          );
        }
        return (
          <div key={field} data-changed={field} className="flex flex-col gap-0.5">
            <dt className="text-label">{fieldLabel(field)}</dt>
            <dd className="flex flex-col gap-0.5">
              <Line sign="−" label="Before">
                {configValue(field, before)}
              </Line>
              <Line sign="+" label="After">
                {configValue(field, after)}
              </Line>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
