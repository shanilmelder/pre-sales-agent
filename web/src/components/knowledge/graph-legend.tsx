/** The mockup's legend, bottom left of the canvas: solid for documented or linked, dashed
 * amber for missing coverage, a dashed ring for stale, failed or missing nodes. */
export function GraphLegend() {
  return (
    <div
      data-testid="graph-legend"
      className="absolute bottom-4 left-4 flex flex-wrap gap-4 rounded-lg border border-graph-chip-off-border bg-graph-chip-background px-3.5 py-2 text-meta text-graph-legend-text"
    >
      <span className="inline-flex items-center gap-1.5">
        <svg aria-hidden="true" width="26" height="8">
          <line x1="0" y1="4" x2="26" y2="4" strokeWidth="2" style={{ stroke: "var(--graph-edge)" }} />
        </svg>
        Documented or linked
      </span>
      <span className="inline-flex items-center gap-1.5">
        <svg aria-hidden="true" width="26" height="8">
          <line
            x1="0"
            y1="4"
            x2="26"
            y2="4"
            strokeWidth="2"
            strokeDasharray="4 3"
            style={{ stroke: "var(--graph-edge-gap)" }}
          />
        </svg>
        Missing coverage
      </span>
      <span className="inline-flex items-center gap-1.5">
        <svg aria-hidden="true" width="16" height="16" viewBox="-20 -20 40 40">
          <circle
            r="17"
            fill="none"
            strokeWidth="3"
            strokeDasharray="6 4"
            style={{ stroke: "var(--graph-missing)" }}
          />
        </svg>
        Stale, failed or missing
      </span>
    </div>
  );
}
