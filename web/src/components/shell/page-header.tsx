import type { ReactNode } from "react";

/** The shared title row of pages outside the workspace: the `h1`, a one-line subtitle and
 * an optional primary action. The right-pane toggle stays in the shell bar. */
export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 p-gutter">
      <div className="flex min-w-0 flex-col gap-1">
        <h1 className="text-title">{title}</h1>
        <p className="text-body text-muted-foreground">{subtitle}</p>
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}
