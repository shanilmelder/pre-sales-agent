import type { ReactNode } from "react";

/** The column-header row of an Admin card table: 12px/500 secondary text on `surface-alt`. */
export const HEAD_ROW = "grid items-center gap-4 bg-surface-alt px-5 py-2.5 text-label text-text-secondary";

/** A body row of an Admin card table: a top border and 20px side padding. */
export const BODY_ROW = "grid items-center gap-4 border-t border-border px-5";

/** The 12px secondary note under an Admin card. */
export const FOOTNOTE = "text-meta text-text-secondary";

/** An ARIA table laid out as a CSS grid: `grid` is the `grid-cols-[…]` class every row
 * shares, so the header and body columns line up. The rows go in `children`. Below 640px the
 * table scrolls sideways instead of clipping; `scrollable` makes that scroll area a Tab stop
 * for tables with no focusable rows. */
export function CardTable({
  label,
  grid,
  columns,
  scrollable = false,
  children,
}: {
  label: string;
  grid: string;
  columns: readonly string[];
  scrollable?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      role={scrollable ? "region" : undefined}
      aria-label={scrollable ? label : undefined}
      tabIndex={scrollable ? 0 : undefined}
      className="overflow-x-auto outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset"
    >
      <div role="table" aria-label={label} className="min-w-[640px]">
        <div role="rowgroup">
          <div role="row" className={`${HEAD_ROW} ${grid}`}>
            {columns.map((column) => (
              <span key={column} role="columnheader" className="min-w-0">
                {column}
              </span>
            ))}
          </div>
        </div>
        <div role="rowgroup">{children}</div>
      </div>
    </div>
  );
}
