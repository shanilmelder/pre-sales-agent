"use client";

import {
  ArrowDownIcon,
  ArrowUpDownIcon,
  ArrowUpIcon,
  InfoIcon,
  TriangleAlertIcon,
} from "lucide-react";
import { useCallback, useId, useState } from "react";

import {
  closeDelivery,
  loadActuals,
  saveActuals,
} from "@/app/opportunities/actions";
import type { CatalogueOptions } from "@/app/opportunities/data";
import {
  ActualInspector,
  type ActualTarget,
} from "@/components/opportunities/actual-inspector";
import { ActualsImport } from "@/components/opportunities/actuals-import";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { useAnnounce } from "@/components/shell/live-region";
import { RightPaneContent, useShell } from "@/components/shell/shell-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyTabCard } from "@/components/ui/empty-tab-card";
import { InlineAlert } from "@/components/ui/inline-alert";
import {
  ACTUALS_REASON_MAX,
  ACTUALS_TITLE,
  CLOSE_DELIVERY,
  CLOSE_WARNING,
  DASH,
  EMPTY_BODY,
  EMPTY_TITLE,
  FOOTNOTE,
  LOAD_FAILED,
  NO_BASELINE,
  NOT_RECORDED,
  UNSAVED_EDITS,
  REASON_LABEL,
  REASON_REQUIRED,
  RECORD_ACTUALS,
  SAVE_ACTUALS,
  SAVE_FAILED,
  STALE_LEAD,
  actualsSubtitle,
  causeLabel,
  changedItems,
  draftOf,
  errorsByLine,
  formatLocalDate,
  hasNoActuals,
  HOURS_NEEDED,
  hours,
  invalidLines,
  needsReason,
  nextSort,
  sortLines,
  varianceTone,
  type ActualError,
  type ActualsLine,
  type ActualsView,
  type LineDraft,
  type SortOrder,
  type VarianceCause,
} from "@/lib/actuals";
import { useActualsEvents } from "@/lib/opportunity-events";

/** The mockup's five columns: Line, Estimate h, Actual h, Variance, Variance cause. */
const GRID = "grid-cols-[minmax(0,1fr)_90px_100px_130px_220px]";
const ROW = `grid ${GRID} items-center gap-4 px-5`;
/** Row padding: the density's 12px (6px compact) plus 4px, as the mockup. */
const BODY_PAD = "py-4 [[data-density=compact]_&]:py-2.5";
const BOX = "rounded-lg border border-border-strong bg-background px-2.5 py-[5px]";

function VarianceText({ line }: { line: ActualsLine }) {
  if (line.variance === null) return <span className="text-text-secondary">{DASH}</span>;
  return (
    <span className={`font-semibold ${varianceTone(line.variance)}`}>
      {line.variance.label}
      <span className="sr-only">{`, ${line.variance.direction_label}`}</span>
    </span>
  );
}

/** Tab 8: the Actuals of the Opportunity's Baseline lines (Story 10.1), as the mockup draws it:
 * a header with **Import from file** (Story 10.2) and **Save Actuals**, a five-column table where a
 * delivery manager edits hours and cause inline, the footnote, and the Inspector's full form.
 * Everyone else sees it read only. Variance always comes from the server. */
export function ActualsSection({
  opportunityId,
  initial,
  catalogue,
}: {
  opportunityId: string;
  initial: ActualsView;
  catalogue: CatalogueOptions;
}) {
  const announce = useAnnounce();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const ids = useId();
  const [view, setView] = useState(initial);
  const [drafts, setDrafts] = useState<Record<string, LineDraft>>({});
  const [sort, setSort] = useState<SortOrder>("none");
  const [recording, setRecording] = useState(false);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [errors, setErrors] = useState<{ byLine: Record<string, ActualError[]>; general: ActualError[] }>(
    { byLine: {}, general: [] },
  );
  const [stale, setStale] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [target, setTarget] = useState<ActualTarget | null>(null);
  const [targetKey, setTargetKey] = useState(0);
  const [inspectorDirty, setInspectorDirty] = useState(false);
  const [confirmClose, setConfirmClose] = useState(false);

  const editable = view.can_record;
  const items = changedItems(view.lines, drafts);
  const badLines = invalidLines(drafts);
  const liveProblems = badLines;
  const dirty = items.length > 0 || badLines.length > 0;

  const apply = useCallback((next: ActualsView) => {
    setView(next);
    setTarget((current) => {
      if (current === null) return null;
      if (current.kind === "line") {
        const line = next.lines.find((l) => l.line_id === current.line.line_id);
        return line ? { kind: "line", line } : null;
      }
      if (current.actual === null) return null;
      const actual = next.unplanned.find((a) => a.group_id === current.actual!.group_id);
      return actual ? { kind: "unplanned", actual } : null;
    });
    setTargetKey((k) => k + 1);
  }, []);

  const reload = useCallback(async () => {
    const loaded = await loadActuals(opportunityId);
    if (loaded.kind === "ok") {
      apply(loaded.actuals);
      setDrafts({});
      setStale(false);
      setFailure(null);
      setErrors({ byLine: {}, general: [] });
    } else {
      setFailure(LOAD_FAILED);
    }
  }, [apply, opportunityId]);

  // Live: another delivery manager's change re-reads the tab, unless this one has unsaved
  // edits (their Save then answers 412 and offers Reload).
  useActualsEvents(opportunityId, () => {
    if (!dirty && !inspectorDirty && !busy) void reload();
  });

  function select(next: ActualTarget) {
    setTarget(next);
    setTargetKey((k) => k + 1);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function draftFor(line: ActualsLine): LineDraft {
    return drafts[line.line_id] ?? draftOf(line);
  }

  function edit(line: ActualsLine, change: Partial<LineDraft>) {
    setDrafts((current) => ({
      ...current,
      [line.line_id]: { ...(current[line.line_id] ?? draftOf(line)), ...change },
    }));
  }

  async function save(withReason: string | null) {
    setBusy(true);
    try {
      const result = await saveActuals({
        opportunityId,
        rowVersion: view.row_version,
        items,
        ...(withReason ? { reason: withReason } : {}),
      });
      if (result.kind === "ok") {
        const { recorded, corrected } = result.saved;
        apply(result.saved.view);
        setDrafts({});
        setAsking(false);
        setReason("");
        setErrors({ byLine: {}, general: [] });
        setFailure(null);
        announce(
          `Actuals saved: ${recorded} recorded, ${corrected} corrected`,
        );
        return;
      }
      if (result.kind === "invalid") {
        const found = errorsByLine(result.errors, items);
        setErrors(found);
        const reasonIssue = found.general.find((e) => e.field === "reason");
        if (reasonIssue) {
          setAsking(true);
          setReasonError(reasonIssue.message);
        }
        announce("Some Actuals could not be saved.");
      } else if (result.kind === "stale") {
        setStale(true);
      } else if (result.kind === "conflict") {
        setFailure(result.detail ?? SAVE_FAILED);
      } else if (result.kind === "forbidden") {
        setFailure("You can't record Actuals here.");
      } else {
        setFailure(SAVE_FAILED);
      }
    } finally {
      setBusy(false);
    }
  }

  function onSave() {
    if (busy) return;
    if (badLines.length > 0) {
      setErrors({
        byLine: Object.fromEntries(
          badLines.map(({ lineId, message }) => [
            lineId,
            [{ item: null, field: "effort_hours", message }],
          ]),
        ),
        general: [],
      });
      return;
    }
    if (items.length === 0) return;
    if (needsReason(view.lines, items) && !asking) {
      setAsking(true);
      setReasonError(null);
      return;
    }
    if (asking) {
      if (reason.trim() === "") {
        setReasonError(REASON_REQUIRED);
        return;
      }
      void save(reason);
      return;
    }
    void save(null);
  }

  async function onClose() {
    if (!view.can_close || busy) return;
    setBusy(true);
    try {
      const result = await closeDelivery({ opportunityId, rowVersion: view.row_version });
      setConfirmClose(false);
      if (result.kind === "ok") {
        apply(result.actuals);
        announce("Delivery closed");
      } else if (result.kind === "stale") {
        setStale(true);
      } else if (result.kind === "conflict") {
        setFailure(result.detail ?? SAVE_FAILED);
      } else if (result.kind === "forbidden") {
        setFailure("You can't record Actuals here.");
      } else {
        setFailure(SAVE_FAILED);
      }
    } finally {
      setBusy(false);
    }
  }

  const header = (
    <div className="flex items-center gap-2.5">
      <div className="min-w-0 flex-1">
        <h2 className="text-[16px] leading-6 font-semibold">{ACTUALS_TITLE}</h2>
        {view.baseline ? (
          <p className="text-[13px] text-text-secondary">{actualsSubtitle(view.baseline.version)}</p>
        ) : null}
      </div>
      {editable ? (
        <>
          <ActualsImport
            opportunityId={opportunityId}
            causes={view.causes}
            disabledReason={dirty ? UNSAVED_EDITS : null}
            onApplied={(next) => {
              apply(next);
              setDrafts({});
              setStale(false);
              setFailure(null);
            }}
          />
          <Button
            type="button"
            aria-disabled={!dirty || busy || undefined}
            aria-describedby={asking ? `${ids}-reason` : undefined}
            onClick={onSave}
          >
            {SAVE_ACTUALS}
          </Button>
        </>
      ) : null}
    </div>
  );

  if (view.baseline === null) {
    return (
      <div className="flex flex-col gap-4">
        {header}
        <p className="text-text-secondary">{NO_BASELINE}</p>
      </div>
    );
  }

  const empty = hasNoActuals(view) && !recording && !dirty;
  const lines = sortLines(view.lines, sort);
  const SortIcon = sort === "descending" ? ArrowDownIcon : sort === "ascending" ? ArrowUpIcon : ArrowUpDownIcon;

  return (
    <div className="flex flex-col gap-4">
      {header}
      {view.version_mismatch ? (
        <p
          role="status"
          className="flex items-center gap-2 rounded-lg border border-border bg-surface-alt px-3 py-2 text-meta"
        >
          <InfoIcon className="size-4 shrink-0 text-text-secondary" aria-hidden="true" />
          {view.version_mismatch.message}
        </p>
      ) : null}
      {stale ? (
        <InlineAlert lead={STALE_LEAD} onReload={() => void reload()}>
          <p className="text-meta">Reload to see the latest Actuals. Your unsaved edits are dropped.</p>
        </InlineAlert>
      ) : null}
      {failure ? (
        <p role="alert" className="text-meta text-destructive">
          {failure}
        </p>
      ) : null}
      {asking ? (
        <div
          id={`${ids}-reason`}
          className="flex max-w-md flex-col gap-2 rounded-lg border border-border bg-surface p-3"
        >
          <p className="text-meta">Some lines already have an Actual. Saving corrects them as a new version.</p>
          <ReasonInput
            label={REASON_LABEL}
            value={reason}
            onChange={setReason}
            error={reasonError}
            disabled={busy}
            max={ACTUALS_REASON_MAX}
          />
          <div className="flex gap-2">
            <Button type="button" onClick={onSave} aria-disabled={busy || undefined}>
              {SAVE_ACTUALS}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setAsking(false);
                setReasonError(null);
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {empty ? (
        <EmptyTabCard
          title={EMPTY_TITLE}
          body={EMPTY_BODY}
          {...(editable ? { actionLabel: RECORD_ACTUALS, onClick: () => setRecording(true) } : {})}
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-[12px] border border-border bg-surface shadow-card">
            <div className="overflow-x-auto">
              <div role="table" aria-label="Actuals per Estimate line" className="min-w-[680px]">
                <div role="rowgroup">
                  <div
                    role="row"
                    className={`${ROW} bg-surface-alt py-2.5 text-[12px] font-medium text-text-secondary`}
                  >
                    <span role="columnheader">Line</span>
                    <span role="columnheader" className="text-right">
                      Estimate h
                    </span>
                    <span role="columnheader" className="text-right">
                      Actual h
                    </span>
                    <span
                      role="columnheader"
                      aria-sort={sort === "none" ? "none" : sort}
                      className="text-right"
                    >
                      <button
                        type="button"
                        onClick={() => setSort(nextSort(sort))}
                        className="inline-flex items-center gap-1 rounded outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-primary"
                      >
                        Variance
                        <SortIcon className="size-3.5" aria-hidden="true" />
                        <span className="sr-only">, sort by variance</span>
                      </button>
                    </span>
                    <span role="columnheader">Variance cause</span>
                  </div>
                </div>
                <div role="rowgroup">
                  {lines.map((line) => {
                    const draft = draftFor(line);
                    const lineErrors = errors.byLine[line.line_id] ?? [];
                    const effortError =
                      lineErrors.find((e) => e.field === "effort_hours") ??
                      liveProblems.find(
                        (p) => p.lineId === line.line_id && p.message === HOURS_NEEDED,
                      );
                    const causeError = lineErrors.find((e) => e.field === "variance_cause");
                    const otherErrors = lineErrors.filter(
                      (e) => e !== effortError && e !== causeError,
                    );
                    const name = `${line.label} ${line.title}`;
                    const selected = target?.kind === "line" && target.line.line_id === line.line_id;
                    const recorded = line.actual !== null;
                    return (
                      <div
                        key={line.line_id}
                        role="row"
                        data-line-id={line.line_id}
                        className={`${ROW} ${BODY_PAD} border-t border-border ${selected ? "bg-primary-tint" : ""}`}
                      >
                        <span role="rowheader" className="min-w-0">
                          <button
                            type="button"
                            aria-current={selected ? "true" : undefined}
                            onClick={() => select({ kind: "line", line })}
                            className="block max-w-full truncate text-left font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
                          >
                            {name}
                          </button>
                          {otherErrors.map((e) => (
                            <span key={e.field} className="block text-meta text-destructive">
                              {e.message}
                            </span>
                          ))}
                        </span>
                        <span role="cell" className="text-right tabular-nums">
                          {hours(line.estimate_hours)}
                        </span>
                        <span role="cell" className="text-right tabular-nums">
                          {editable ? (
                            <>
                              <input
                                aria-label={`Actual hours, ${name}`}
                                inputMode="decimal"
                                placeholder={DASH}
                                value={draft.effort}
                                aria-invalid={effortError ? true : undefined}
                                aria-describedby={effortError ? `${ids}-${line.line_id}-effort` : undefined}
                                onChange={(event) => edit(line, { effort: event.target.value })}
                                className={`${BOX} w-full text-right tabular-nums text-foreground outline-none placeholder:text-text-secondary focus-visible:ring-2 focus-visible:ring-primary aria-[invalid=true]:border-destructive`}
                              />
                              {effortError ? (
                                <span
                                  id={`${ids}-${line.line_id}-effort`}
                                  className="block text-left text-meta text-destructive"
                                >
                                  {effortError.message}
                                </span>
                              ) : null}
                            </>
                          ) : (
                            <span className={recorded ? "" : "text-text-secondary"}>
                              {recorded ? hours(line.actual!.effort_hours) : DASH}
                            </span>
                          )}
                        </span>
                        <span role="cell" className="text-right tabular-nums">
                          <VarianceText line={line} />
                        </span>
                        <span role="cell" className="min-w-0">
                          {editable ? (
                            <>
                              <select
                                aria-label={`Variance cause, ${name}`}
                                value={draft.cause}
                                aria-invalid={causeError ? true : undefined}
                                aria-describedby={causeError ? `${ids}-${line.line_id}-cause` : undefined}
                                onChange={(event) =>
                                  edit(line, { cause: event.target.value as VarianceCause | "" })
                                }
                                className={`${BOX} w-full bg-background text-[13px] outline-none focus-visible:ring-2 focus-visible:ring-primary aria-[invalid=true]:border-destructive ${draft.cause === "" ? "text-text-secondary" : "text-foreground"}`}
                              >
                                <option value="">{recorded || draft.effort.trim() ? "No cause" : NOT_RECORDED}</option>
                                {view.causes.map((cause) => (
                                  <option key={cause.value} value={cause.value}>
                                    {cause.label}
                                  </option>
                                ))}
                              </select>
                              {causeError ? (
                                <span
                                  id={`${ids}-${line.line_id}-cause`}
                                  className="block text-meta text-destructive"
                                >
                                  {causeError.message}
                                </span>
                              ) : null}
                            </>
                          ) : (
                            <span className={`text-[13px] ${recorded ? "" : "text-text-secondary"}`}>
                              {recorded
                                ? causeLabel(line.actual!.variance_cause, view.causes)
                                : NOT_RECORDED}
                            </span>
                          )}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
          <p className="text-[12px] text-text-secondary">{FOOTNOTE}</p>
          {errors.general.filter((e) => e.field !== "reason").map((e) => (
            <p key={e.field} role="alert" className="text-meta text-destructive">
              {e.message}
            </p>
          ))}

          {view.unplanned.length > 0 || editable ? (
            <section aria-labelledby={`${ids}-unplanned`} className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <h3 id={`${ids}-unplanned`} className="flex-1 text-section">
                  Unplanned work
                </h3>
                {editable ? (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => select({ kind: "unplanned", actual: null })}
                  >
                    Add Unplanned work
                  </Button>
                ) : null}
              </div>
              {view.unplanned.length === 0 ? (
                <p className="text-meta text-text-secondary">No Unplanned work recorded.</p>
              ) : (
                <ul className="flex flex-col divide-y divide-border rounded-[12px] border border-border bg-surface">
                  {view.unplanned.map((actual) => (
                    <li key={actual.group_id} className="flex items-center gap-4 px-5 py-3 tabular-nums">
                      <button
                        type="button"
                        onClick={() => select({ kind: "unplanned", actual })}
                        className="min-w-0 flex-1 truncate text-left font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-primary"
                      >
                        {[...actual.integration_types, ...(actual.work_package ? [actual.work_package] : [])]
                          .map((ref) => ref.name)
                          .join(", ") || "Unplanned work"}
                      </button>
                      <span>{`${hours(actual.effort_hours)} h`}</span>
                      <span className={`font-semibold ${varianceTone(actual.variance)}`}>
                        {actual.variance.label}
                        <span className="sr-only">{`, ${actual.variance.direction_label}`}</span>
                      </span>
                      <span className="text-[13px]">{causeLabel(actual.variance_cause, view.causes)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            {view.totals.variance ? (
              <p className="flex-1 text-meta tabular-nums">
                <span className="text-text-secondary">Total variance </span>
                <span className={`font-semibold ${varianceTone(view.totals.variance)}`}>
                  {view.totals.variance.label}
                </span>
                <span className="sr-only">{`, ${view.totals.variance.direction_label}`}</span>
              </p>
            ) : (
              <span className="flex-1" />
            )}
            {view.delivery ? (
              <p role="status" className="text-meta text-resolved">
                {`Delivery closed on ${formatLocalDate(view.delivery.closed_at)} by ${view.delivery.closed_by_name}.`}
              </p>
            ) : editable ? (
              <>
                {view.close_blocked_reason ? (
                  <span id={`${ids}-close`} className="text-meta text-text-secondary">
                    {view.close_blocked_reason}
                  </span>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  aria-disabled={!view.can_close || busy || undefined}
                  aria-describedby={view.close_blocked_reason ? `${ids}-close` : undefined}
                  onClick={() => {
                    if (view.can_close && !busy) setConfirmClose(true);
                  }}
                >
                  {CLOSE_DELIVERY}
                </Button>
                <Dialog open={confirmClose} onOpenChange={setConfirmClose}>
                  <DialogContent showCloseButton={false} className="w-[480px]">
                    <DialogHeader>
                      <DialogTitle className="text-[20px] leading-7 font-semibold">
                        {`Close delivery for Estimate v${view.baseline.version}?`}
                      </DialogTitle>
                    </DialogHeader>
                    <p className="flex items-start gap-2.5 rounded-[10px] bg-gap-tint px-3.5 py-2.5 text-control text-gap">
                      <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                      {CLOSE_WARNING}
                    </p>
                    <DialogFooter>
                      <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                      <Button type="button" disabled={busy} onClick={() => void onClose()}>
                        {CLOSE_DELIVERY}
                      </Button>
                    </DialogFooter>
                  </DialogContent>
                </Dialog>
              </>
            ) : null}
          </div>
        </>
      )}

      {target ? (
        <RightPaneContent>
          <ActualInspector
            key={targetKey}
            opportunityId={opportunityId}
            view={view}
            target={target}
            catalogue={catalogue}
            onDirtyChange={setInspectorDirty}
            onSaved={(next) => {
              apply(next);
              setRecording(true);
            }}
            onReload={() => void reload()}
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}

