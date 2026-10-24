"use client";

import { CircleAlertIcon, CircleCheckIcon, TriangleAlertIcon } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

import { Card } from "@/components/ui/card";
import { Pill } from "@/components/ui/pill";
import { Skeleton } from "@/components/ui/skeleton";
import {
  checklistsHref,
  checklistsText,
  COVERAGE_STATUSES,
  sourcesHref,
  sourcesText,
  type CoverageCell,
  type CoverageStatus,
  type KnowledgeCoverage,
} from "@/lib/coverage";
import { useSkeletonDone } from "@/lib/use-skeleton-done";

const SKELETON_ROWS = 3;
export const NO_TYPES =
  "No active Integration Types yet. An administrator can add them under Admin → Catalogue.";
export const NO_PRODUCTS =
  "No products yet. Register a Knowledge Source, publish a Checklist or create an Opportunity to see its coverage.";

const ICONS: Record<CoverageStatus, ReactNode> = {
  ready: <CircleCheckIcon />,
  partial: <TriangleAlertIcon />,
  missing: <CircleAlertIcon />,
};

/** The mockup's grid: a 200px Product column, then equal columns, 12px apart. Each column
 * keeps at least 168px; the card scrolls sideways when there are many. */
function columns(count: number): CSSProperties {
  return { gridTemplateColumns: `200px repeat(${count}, minmax(168px, 1fr))` };
}

const ROW = "grid w-max min-w-full items-center gap-3 px-5";
const HEADER_BAND = `${ROW} bg-surface-alt py-2.5 text-[12px] font-medium text-text-secondary`;
const BODY_ROW = `${ROW} border-t border-border py-[18px]`;

/** The status pill: icon and label in the status tint. */
export function CoverageStatusPill({ status, id }: { status: CoverageStatus; id?: string }) {
  const { label, tone } = COVERAGE_STATUSES[status];
  return (
    <Pill id={id} tone={tone} icon={ICONS[status]} data-status={status}>
      {label}
    </Pill>
  );
}

function Message({ children }: { children: ReactNode }) {
  return (
    <Card data-testid="coverage-card" className="px-6 py-14 text-center text-text-secondary">
      <p>{children}</p>
    </Card>
  );
}

/** Products (rows) by active Integration Types (columns), in a card with the mockup's header
 * band. Each cell shows the status pill and the Source and Checklist counts ("None" for a
 * missing kind, "Stale" when every Source is stale).
 *
 * The cells are an ARIA grid, one Tab stop (roving tabindex): the arrow keys move between
 * cells (Home and End to the row's ends, with Ctrl to the grid's), and each cell is named by
 * its row and column headers. Enter or a click opens Sources filtered to the cell's product
 * and Integration Type; the Checklists count is its own link (Tab from the cell) to
 * Checklists with the same filter. Skeleton cells show for at least 150 ms on first load. */
export function CoverageMatrix({ coverage }: { coverage: KnowledgeCoverage }) {
  const router = useRouter();
  const skeletonDone = useSkeletonDone();
  const grid = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<{ row: number; col: number }>({ row: 0, col: 0 });
  const baseId = useId();
  const types = coverage.integration_types;
  const rows = coverage.rows;
  const template = columns(types.length);

  if (!skeletonDone) {
    return (
      <Card data-testid="coverage-card" className="overflow-hidden">
        <div aria-busy="true" className="overflow-x-auto">
          <p className="sr-only">Loading coverage</p>
          <div aria-hidden="true" className={HEADER_BAND} style={template}>
            <span>Product</span>
            {types.map((type) => (
              <span key={type.id} className="truncate">
                {type.name}
              </span>
            ))}
          </div>
          {Array.from({ length: Math.max(1, Math.min(rows.length, SKELETON_ROWS)) }, (_, r) => (
            <div key={r} data-skeleton-row="" aria-hidden="true" className={BODY_ROW} style={template}>
              <Skeleton className="h-3.5 w-3/5 rounded-sm" />
              {types.map((type) => (
                <span key={type.id} data-skeleton-cell="" className="flex flex-col gap-1.5">
                  <Skeleton className="h-5 w-20 rounded-full" />
                  <Skeleton className="h-3 w-32 rounded-sm" />
                </span>
              ))}
            </div>
          ))}
        </div>
      </Card>
    );
  }

  if (types.length === 0) return <Message>{NO_TYPES}</Message>;
  if (rows.length === 0) return <Message>{NO_PRODUCTS}</Message>;

  const rowHeaderId = (r: number) => `${baseId}-row-${r}`;
  const colHeaderId = (c: number) => `${baseId}-col-${c}`;
  const cellId = (r: number, c: number) => `${baseId}-cell-${r}-${c}`;
  // A row or column can disappear on a refresh; keep the tab stop inside the grid.
  const current = {
    row: Math.min(active.row, rows.length - 1),
    col: Math.min(active.col, types.length - 1),
  };

  function focusCell(row: number, col: number) {
    grid.current
      ?.querySelector<HTMLElement>(`[data-coverage-cell][data-row="${row}"][data-col="${col}"]`)
      ?.focus();
  }

  function open(product: string, typeId: string) {
    router.push(sourcesHref(product, typeId));
  }

  function onCellKeyDown(event: KeyboardEvent<HTMLDivElement>, row: number, col: number) {
    // Keys pressed on the Checklists link inside the cell are the link's.
    if (event.target !== event.currentTarget) return;
    if (event.altKey || event.metaKey) return;
    const lastRow = rows.length - 1;
    const lastCol = types.length - 1;
    let next: [number, number] | null = null;
    switch (event.key) {
      case "ArrowRight":
        next = [row, Math.min(lastCol, col + 1)];
        break;
      case "ArrowLeft":
        next = [row, Math.max(0, col - 1)];
        break;
      case "ArrowDown":
        next = [Math.min(lastRow, row + 1), col];
        break;
      case "ArrowUp":
        next = [Math.max(0, row - 1), col];
        break;
      case "Home":
        next = event.ctrlKey ? [0, 0] : [row, 0];
        break;
      case "End":
        next = event.ctrlKey ? [lastRow, lastCol] : [row, lastCol];
        break;
      case "Enter":
        event.preventDefault();
        open(rows[row].product, types[col].id);
        return;
      default:
        return;
    }
    event.preventDefault();
    focusCell(next[0], next[1]);
  }

  /** A plain left click opens Sources here; Ctrl, Cmd or Shift with it, or a middle click,
   * opens it in a new tab. Clicks on the Checklists link are the link's. */
  function onCellClick(event: MouseEvent<HTMLDivElement>, product: string, typeId: string) {
    if (event.button !== 0 && event.button !== 1) return;
    if ((event.target as Element).closest("a")) return;
    if (event.button === 1 || event.metaKey || event.ctrlKey || event.shiftKey) {
      event.preventDefault();
      window.open(sourcesHref(product, typeId), "_blank", "noopener");
      return;
    }
    open(product, typeId);
  }

  function cell(c: CoverageCell, product: string, row: number, col: number) {
    const isActive = row === current.row && col === current.col;
    const id = cellId(row, col);
    return (
      <div
        key={c.integration_type_id}
        role="gridcell"
        tabIndex={isActive ? 0 : -1}
        data-coverage-cell=""
        data-row={row}
        data-col={col}
        aria-colindex={col + 2}
        aria-labelledby={`${rowHeaderId(row)} ${colHeaderId(col)} ${id}-status ${id}-sources ${id}-checklists`}
        onFocus={(event) => {
          if (event.target === event.currentTarget) setActive({ row, col });
        }}
        onKeyDown={(event) => onCellKeyDown(event, row, col)}
        onClick={(event) => onCellClick(event, product, c.integration_type_id)}
        onAuxClick={(event) => onCellClick(event, product, c.integration_type_id)}
        // A middle click opens a new tab (onAuxClick), not Windows' autoscroll.
        onMouseDown={(event) => {
          if (event.button === 1) event.preventDefault();
        }}
        className="-m-1.5 flex min-w-0 cursor-pointer flex-col items-start gap-1 rounded-md p-1.5 outline-none hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-primary"
      >
        <CoverageStatusPill status={c.status} id={`${id}-status`} />
        <span className="flex flex-wrap items-center gap-x-1.5 text-meta text-text-secondary">
          <span id={`${id}-sources`}>Sources: {sourcesText(c)}</span>
          <span aria-hidden="true">·</span>
          <Link
            id={`${id}-checklists`}
            href={checklistsHref(product, c.integration_type_id)}
            tabIndex={isActive ? 0 : -1}
            data-checklists-link=""
            className="rounded-sm text-foreground underline underline-offset-2 outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-primary"
          >
            Checklists: {checklistsText(c)}
          </Link>
        </span>
      </div>
    );
  }

  return (
    <Card data-testid="coverage-card" className="overflow-hidden">
      <p id={`${baseId}-hint`} className="sr-only">
        Arrow keys move between cells. Enter opens the Sources for the cell; Tab reaches its
        Checklists link.
      </p>
      <div className="overflow-x-auto">
        <div
          ref={grid}
          role="grid"
          aria-readonly="true"
          aria-label="Knowledge coverage by product and Integration Type"
          aria-describedby={`${baseId}-hint`}
          aria-rowcount={rows.length + 1}
          aria-colcount={types.length + 1}
        >
          <div role="row" aria-rowindex={1} className={HEADER_BAND} style={template}>
            <span role="columnheader" aria-colindex={1}>
              Product
            </span>
            {types.map((type, col) => (
              <span
                key={type.id}
                id={colHeaderId(col)}
                role="columnheader"
                aria-colindex={col + 2}
                title={type.name}
                className="truncate"
              >
                {type.name}
              </span>
            ))}
          </div>
          {rows.map((row, r) => (
            <div
              key={row.product}
              role="row"
              aria-rowindex={r + 2}
              className={BODY_ROW}
              style={template}
            >
              <span
                id={rowHeaderId(r)}
                role="rowheader"
                aria-colindex={1}
                title={row.product}
                className="truncate font-medium"
              >
                {row.product}
              </span>
              {row.cells.map((c, col) => cell(c, row.product, r, col))}
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
