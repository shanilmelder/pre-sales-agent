"use client";

import { CircleAlertIcon, ListChecksIcon, PencilIcon } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import {
  editEstimateLine,
  loadEstimate,
  startEstimateDraft,
  type EstimateLineEditResult,
  type StartEstimateDraftResult,
} from "@/app/opportunities/actions";
import {
  AssumptionsRegister,
  OriginGapInspector,
} from "@/components/opportunities/assumptions-register";
import { EstimateExport } from "@/components/opportunities/estimate-export";
import { EstimateInspector } from "@/components/opportunities/estimate-inspector";
import { ReasonPrompt, RoleMixEditor } from "@/components/opportunities/estimate-line-edit";
import { InlineInput } from "@/components/opportunities/inline-field";
import { useAnnounce } from "@/components/shell/live-region";
import { RIGHT_PANE_TOGGLE_ID, RightPaneContent, useShell } from "@/components/shell/shell-context";
import {
  COLUMNS,
  DRAFT_POLL_LIMIT_MS,
  DRAFT_POLL_MS,
  DRAFTING,
  draftFailure,
  EDIT_NOT_ALLOWED,
  EDIT_SAVE_FAILED,
  EFFORT_RULE,
  editedLabel,
  hours,
  isDrafting,
  isProposing,
  NO_ESTIMATE,
  keepReason,
  NEW_VERSION_ARRIVED,
  NOTHING_TO_ESTIMATE,
  parseEffort,
  readKeptReason,
  roleMixLabel,
  roundedHours,
  roundHours,
  ROLES,
  sectionLabel,
  STILL_DRAFTING,
  UNALLOCATED_CONTINGENCY,
  uncarriedEditsNote,
  uncoveredLabel,
  registerSummary,
  VERSION_REPLACED,
  versionLabel,
  type Assumption,
  type EstimateDraft,
  type EstimateLine,
  type EstimateVersion,
  type EstimateView,
  type RoleMix,
  type Totals,
} from "@/lib/estimates";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import { cn } from "@/lib/utils";

export const RETRY = "Retry";
const RETRY_FAILED = "The retry failed. Try again.";
const RETRY_NOT_ALLOWED =
  "Only the owner and collaborators, except sales representatives, can draft the Estimate.";

const actionClass =
  "h-6 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

const num = "px-2.5 text-right text-numeric whitespace-nowrap";
/** The left rule that sets the Contingency column apart. */
const cont = "border-l border-border";
const headCell = "h-[30px] bg-background px-2.5 text-label text-muted-foreground whitespace-nowrap";

/** The version pill: "Draft v2". 20px, fully rounded, neutral outline. */
export function VersionPill({ version }: { version: Pick<EstimateVersion, "status" | "version"> }) {
  return (
    <span className="inline-flex h-5 shrink-0 items-center whitespace-nowrap rounded-full border border-border bg-background px-2 text-label text-foreground">
      {versionLabel(version)}
    </span>
  );
}

/** The Covers cell: how many Requirements the line covers, as a chip. */
export function CoversChip({ count }: { count: number }) {
  return (
    <span className="inline-flex h-5 items-center gap-1 rounded-sm border border-border bg-background px-1.5 text-meta text-muted-foreground">
      <ListChecksIcon aria-hidden="true" className="size-3 shrink-0" />
      <span className="[font-variant-numeric:tabular-nums]">{count}</span>
      <span className="sr-only">{count === 1 ? " Requirement" : " Requirements"}</span>
    </span>
  );
}

function TotalsCells({ totals }: { totals: Totals }) {
  return (
    <>
      <td className={num}>{hours(totals.effort_hours)}</td>
      <td className={cn(num, cont)}>{hours(totals.contingency_hours)}</td>
      <td className={num}>{hours(totals.total_hours)}</td>
    </>
  );
}

/** "Engineer 31.7 h · Project manager 10.6 h · QA 10.7 h". */
function roleTotalsLabel(totals: Totals): string {
  return ROLES.map((role) => `${role.label} ${hours(totals.role_hours[role.value])} h`).join(" · ");
}

/** A change to a line, before its reason is given. */
export type LineChange = { effortHours?: number; roleMix?: RoleMix };

/** What saving a change came to: on failure, the sentence to show under the line, and
 * whether a Reload is offered (stale or replaced version). */
export type EditOutcome = { ok: true } | { ok: false; message: string; reload?: boolean };

/** The line as it was when editing started: its `row_version` goes in `If-Match`, so a
 * colleague's save in between is a 412, never silently overwritten. */
type Snapshot = {
  lineId: string;
  rowVersion: number;
  effort: number;
  mix: RoleMix;
};
type Editing = Snapshot & { kind: "effort" | "mix" };
type Pending = Snapshot & {
  change: LineChange;
  summary: string;
  initialReason: string;
};
type Notice = { lineId: string; message: string; reload: boolean };

/** The "Edited" marker: an icon plus its label, never the icon alone. */
export function EditedMarker({ line }: { line: EstimateLine }) {
  const label = editedLabel(line);
  if (!label) return null;
  return (
    <span
      data-edited=""
      className="inline-flex shrink-0 items-center gap-1 text-meta whitespace-nowrap text-muted-foreground"
    >
      <PencilIcon aria-hidden="true" className="size-3 shrink-0" />
      {label}
    </span>
  );
}

const cellButton =
  "rounded-sm px-1 outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";

/** The Estimate Version as a dense grid: lines grouped by section in template order, each
 * section closed by its subtotal row; a sticky header and sticky totals (the overall totals
 * and, under them, the per-role totals). Numbers are right-aligned tabular figures from the
 * server; the Contingency column has a left rule. Edited lines carry an "Edited" marker.
 *
 * The lines are one Tab stop (roving tabindex: the last focused, else the selected, else the
 * first line); j/k (with single-key shortcuts on) or the arrow keys move between lines, and
 * Enter, Space or a click opens the line.
 *
 * With `canEdit` (on a draft) the Effort cell is an inline field (Enter or blur to save, Esc
 * to cancel; `e` on a focused line starts it) and the Role mix cell opens a compact editor;
 * either then asks for a reason before `onSave` runs. While saving the cell is disabled; a
 * failure leaves the stored value and shows `onSave`'s sentence under the line (with Reload
 * when offered). */
export function EstimateGrid({
  version,
  selectedId = null,
  onOpen,
  canEdit = false,
  onSave,
  onReload,
  opportunityId,
}: {
  version: EstimateVersion;
  selectedId?: string | null;
  /** `viaKeyboard` is true when opened with Enter or Space, not a pointer. */
  onOpen?: (line: EstimateLine, viaKeyboard: boolean) => void;
  canEdit?: boolean;
  /** `rowVersion` is the line's `row_version` when editing started (for `If-Match`). */
  onSave?: (
    line: EstimateLine,
    change: LineChange,
    reason: string,
    rowVersion: number,
  ) => Promise<EditOutcome>;
  onReload?: () => void;
  /** Where the last reason is kept in the browser (one key per Opportunity). */
  opportunityId?: string;
}) {
  const { singleKeyShortcuts } = useShell();
  const container = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  /** A selector to focus after the next render (e.g. back to a cell after Esc). */
  const [focusTarget, setFocusTarget] = useState<string | null>(null);
  /** A new version replaced the lines an open editor was changing. */
  const [replaced, setReplaced] = useState(false);
  const [seenVersionId, setSeenVersionId] = useState(version.id);
  if (seenVersionId !== version.id) {
    setSeenVersionId(version.id);
    setReplaced(editing !== null || pending !== null);
    setEditing(null);
    setPending(null);
    setNotice(null);
  }
  const reasonKey = opportunityId ?? version.id;
  const lines = version.sections.flatMap((section) => section.lines);
  const editable = canEdit && version.status === "draft" && onSave !== undefined;
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && lines.some((l) => l.id === id)) ??
    lines[0]?.id;

  useEffect(() => {
    if (!focusTarget) return;
    container.current?.querySelector<HTMLElement>(focusTarget)?.focus();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a one-shot request
    setFocusTarget(null);
  }, [focusTarget]);

  function startEdit(line: EstimateLine, kind: Editing["kind"]) {
    if (!editable || saving) return;
    setNotice(null);
    setReplaced(false);
    setPending(null);
    setEditing({
      lineId: line.id,
      kind,
      rowVersion: line.row_version,
      effort: line.effort_hours,
      mix: line.role_mix,
    });
  }

  function cancel(line: EstimateLine, kind: Editing["kind"], viaKey: boolean) {
    setEditing(null);
    setPending(null);
    if (viaKey) setFocusTarget(`[data-edit-${kind}="${line.id}"]`);
  }

  function commitEffort(line: EstimateLine, text: string, viaKey: boolean) {
    const from = editing;
    setEditing(null);
    if (!from || from.lineId !== line.id) return;
    const effort = parseEffort(text);
    if (effort === null) {
      setNotice({ lineId: line.id, message: EFFORT_RULE, reload: false });
      if (viaKey) setFocusTarget(`[data-edit-effort="${line.id}"]`);
      return;
    }
    if (roundHours(effort) === roundHours(from.effort)) {
      if (viaKey) setFocusTarget(`[data-edit-effort="${line.id}"]`);
      return; // unchanged: nothing to save
    }
    setPending({
      ...from,
      change: { effortHours: effort },
      summary: `Effort ${hours(from.effort)} h → ${roundedHours(effort)} h`,
      initialReason: readKeptReason(reasonKey, version.id),
    });
  }

  function commitMix(line: EstimateLine, mix: RoleMix) {
    const from = editing;
    setEditing(null);
    if (!from || from.lineId !== line.id) return;
    if (ROLES.every((role) => mix[role.value] === from.mix[role.value])) {
      setFocusTarget(`[data-edit-mix="${line.id}"]`);
      return;
    }
    setPending({
      ...from,
      change: { roleMix: mix },
      summary: `Role mix ${roleMixLabel(from.mix)} → ${roleMixLabel(mix)}`,
      initialReason: readKeptReason(reasonKey, version.id),
    });
  }

  async function save(line: EstimateLine, edit: Pending, reason: string) {
    if (!onSave || saving) return;
    const { change } = edit;
    setSaving(true);
    let outcome: EditOutcome;
    try {
      outcome = await onSave(line, change, reason, edit.rowVersion);
    } catch {
      outcome = { ok: false, message: EDIT_SAVE_FAILED };
    }
    setSaving(false);
    setPending(null);
    if (outcome.ok) {
      keepReason(reasonKey, version.id, reason);
      setNotice(null);
    } else {
      setNotice({
        lineId: line.id,
        message: outcome.message,
        reload: outcome.reload ?? false,
      });
    }
    setFocusTarget(`[data-edit-${change.roleMix ? "mix" : "effort"}="${line.id}"]`);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const target = event.target as HTMLElement;
    if (
      editable &&
      singleKeyShortcuts &&
      event.key === "e" &&
      target.matches("button[data-line-row]")
    ) {
      const line = lines.find((l) => l.id === target.dataset.lineId);
      if (line) {
        event.preventDefault();
        startEdit(line, "effort");
      }
      return;
    }
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      container.current?.querySelectorAll<HTMLButtonElement>("button[data-line-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === event.target);
    if (index === -1) return;
    const next = Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  function editorRow(line: EstimateLine) {
    const showMixEditor = editing?.lineId === line.id && editing.kind === "mix";
    const prompt = pending?.lineId === line.id ? pending : null;
    const shownNotice = notice?.lineId === line.id ? notice : null;
    if (!editable || (!showMixEditor && !prompt && !shownNotice)) return null;
    return (
      <tr key={`${line.id}-editor`} data-line-editor={line.id}>
        <td colSpan={COLUMNS.length} className="border-b border-border bg-muted/40 px-2.5 py-1.5">
          {showMixEditor ? (
            <RoleMixEditor
              lineTitle={line.title}
              initial={editing?.mix ?? line.role_mix}
              onSave={(mix) => commitMix(line, mix)}
              onCancel={() => cancel(line, "mix", true)}
            />
          ) : prompt ? (
            <ReasonPrompt
              summary={prompt.summary}
              initial={prompt.initialReason}
              busy={saving}
              onSave={(reason) => void save(line, prompt, reason)}
              onCancel={() => cancel(line, prompt.change.roleMix ? "mix" : "effort", true)}
            />
          ) : shownNotice ? (
            <div className="flex flex-wrap items-center gap-2">
              <p className="flex items-center gap-1.5 text-meta text-destructive">
                <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
                {shownNotice.message}
              </p>
              {shownNotice.reload && onReload ? (
                <button
                  type="button"
                  onClick={() => {
                    setNotice(null);
                    onReload();
                  }}
                  className={actionClass}
                >
                  Reload
                </button>
              ) : null}
            </div>
          ) : null}
        </td>
      </tr>
    );
  }

  return (
    <div
      ref={container}
      onKeyDown={onKeyDown}
      aria-busy={saving || undefined}
      className="max-h-[70vh] overflow-auto rounded-md border border-border"
    >
      {replaced ? (
        <p className="flex items-center gap-1.5 px-2.5 py-1.5 text-meta text-destructive">
          <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
          {NEW_VERSION_ARRIVED}
        </p>
      ) : null}
      <table className="w-full border-separate border-spacing-0 text-body">
        <caption className="sr-only">{`Estimate ${versionLabel(version)}`}</caption>
        <thead className="sticky top-0 z-10 bg-background">
          <tr>
            {COLUMNS.map((column, i) => (
              <th
                key={column}
                scope="col"
                className={cn(
                  headCell,
                  "border-b border-border",
                  i >= 3 ? "text-right" : "text-left",
                  i === 4 && cont,
                )}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        {version.sections.map((section) => (
          <tbody key={section.section} data-section={section.section}>
            <tr>
              <th
                scope="rowgroup"
                colSpan={COLUMNS.length}
                className="h-7 border-b border-border bg-muted px-2.5 text-left text-label text-muted-foreground"
              >
                {sectionLabel(section.section)}
              </th>
            </tr>
            {section.lines.flatMap((line) => {
              const selected = line.id === selectedId;
              const savingThis = saving && pending?.lineId === line.id;
              const shownMix = (savingThis && pending?.change.roleMix) || line.role_mix;
              const shownEffort =
                savingThis && pending?.change.effortHours !== undefined
                  ? roundHours(pending.change.effortHours)
                  : line.effort_hours;
              const editingEffort = editing?.lineId === line.id && editing.kind === "effort";
              const editingMix = editing?.lineId === line.id && editing.kind === "mix";
              const row = (
                <tr
                  key={line.id}
                  aria-selected={selected}
                  className={cn(
                    "h-row border-b border-border",
                    selected ? "bg-muted" : "hover:bg-muted/60",
                  )}
                >
                  <th
                    scope="row"
                    className={cn(
                      "max-w-0 border-b border-border px-1 text-left font-normal",
                      selected && "shadow-[inset_2px_0_0_var(--primary)]",
                    )}
                  >
                    <div className="flex min-w-0 items-center gap-1.5">
                      <button
                        type="button"
                        data-line-row=""
                        data-line-id={line.id}
                        tabIndex={line.id === tabStopId ? 0 : -1}
                        onFocus={() => setFocusedId(line.id)}
                        // A keyboard-activated click has no pointer clicks (detail 0).
                        onClick={(event) => onOpen?.(line, event.detail === 0)}
                        className="block min-h-row min-w-0 flex-1 truncate rounded-sm px-1.5 text-left text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
                      >
                        {line.title}
                      </button>
                      <EditedMarker line={line} />
                    </div>
                  </th>
                  <td className="w-24 border-b border-border px-2.5">
                    <CoversChip count={line.requirements.length} />
                  </td>
                  <td className="w-44 border-b border-border px-2.5 text-label whitespace-nowrap text-muted-foreground [font-variant-numeric:tabular-nums]">
                    {editable ? (
                      <button
                        type="button"
                        data-edit-mix={line.id}
                        aria-label={`Edit role mix of ${line.title}: ${roleMixLabel(shownMix)}`}
                        aria-expanded={editingMix}
                        disabled={saving}
                        onClick={() => startEdit(line, "mix")}
                        className={cellButton}
                      >
                        {roleMixLabel(shownMix)}
                      </button>
                    ) : (
                      roleMixLabel(line.role_mix)
                    )}
                  </td>
                  <td className={cn(num, "w-24 border-b border-border")}>
                    {editable && editingEffort ? (
                      <InlineInput
                        label={`Effort (h) of ${line.title}`}
                        initial={hours(line.effort_hours)}
                        onCommit={(text, viaKey) => commitEffort(line, text, viaKey)}
                        onCancel={(viaKey) => cancel(line, "effort", viaKey)}
                        className="h-6 w-20 rounded-md border border-input bg-background px-1.5 text-right text-numeric outline-none focus-visible:ring-2 focus-visible:ring-primary"
                      />
                    ) : editable ? (
                      <button
                        type="button"
                        data-edit-effort={line.id}
                        aria-label={`Edit effort of ${line.title}: ${hours(shownEffort)} hours`}
                        disabled={saving}
                        onClick={() => startEdit(line, "effort")}
                        className={cn(cellButton, "text-numeric")}
                      >
                        {hours(shownEffort)}
                      </button>
                    ) : (
                      hours(line.effort_hours)
                    )}
                  </td>
                  <td className={cn(num, cont, "w-28 border-b border-border")}>
                    {hours(line.contingency_hours)}
                  </td>
                  <td className={cn(num, "w-24 border-b border-border")}>
                    {hours(line.total_hours)}
                  </td>
                </tr>
              );
              const extra = editorRow(line);
              return extra ? [row, extra] : [row];
            })}
            <tr data-subtotal="" className="h-7">
              <th
                scope="row"
                colSpan={3}
                className="border-b border-border px-2.5 text-left text-label text-muted-foreground"
              >
                {`${sectionLabel(section.section)} subtotal`}
              </th>
              <TotalsCells totals={section.subtotal} />
            </tr>
          </tbody>
        ))}
        {version.unallocated_contingency_hours > 0 ? (
          <tbody data-unallocated="">
            <tr className="h-row">
              <th
                scope="row"
                colSpan={3}
                className="border-b border-border px-2.5 text-left text-body font-normal"
              >
                {UNALLOCATED_CONTINGENCY}
              </th>
              <td className={cn(num, "border-b border-border text-muted-foreground")}>
                <span aria-hidden="true">–</span>
                <span className="sr-only">None</span>
              </td>
              <td className={cn(num, cont, "border-b border-border")}>
                {hours(version.unallocated_contingency_hours)}
              </td>
              <td className={cn(num, "border-b border-border")}>
                {hours(version.unallocated_contingency_hours)}
              </td>
            </tr>
          </tbody>
        ) : null}
        <tfoot className="sticky bottom-0 z-10 bg-muted">
          <tr data-totals="" className="h-row">
            <th
              scope="row"
              colSpan={3}
              className="border-t border-border px-2.5 text-left text-body-strong"
            >
              Total
            </th>
            <td className={cn(num, "border-t border-border font-semibold")}>
              {hours(version.totals.effort_hours)}
            </td>
            <td className={cn(num, cont, "border-t border-border font-semibold")}>
              {hours(version.totals.contingency_hours)}
            </td>
            <td className={cn(num, "border-t border-border font-semibold")}>
              {hours(version.totals.total_hours)}
            </td>
          </tr>
          <tr data-role-totals="" className="h-7">
            <th
              scope="row"
              colSpan={3}
              className="px-2.5 text-left text-label text-muted-foreground"
            >
              Effort by role
            </th>
            <td
              colSpan={3}
              className="px-2.5 text-right text-label whitespace-nowrap [font-variant-numeric:tabular-nums]"
            >
              {roleTotalsLabel(version.totals)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

/** The header above the grid: the version pill and how many Requirements no line covers;
 * "Drafting Estimate" with a running dot while a draft is queued or running ("Still
 * drafting — reload to check." once polling has stopped); "Estimate draft failed:
 * <reason>" with **Retry** (only for those who may start a draft) once failed; and **Export**
 * (Story 8.8) when there is a version and the caller may export it. */
export function EstimateHeader({
  version,
  draft,
  canStart = false,
  opportunityId,
  canExport = false,
  busy = false,
  message = null,
  stalled = false,
  onRetry,
}: {
  version: EstimateVersion | null;
  draft: EstimateDraft | null;
  canStart?: boolean;
  /** Needed for **Export**; without it the control is hidden. */
  opportunityId?: string;
  canExport?: boolean;
  /** A Retry is in flight. */
  busy?: boolean;
  /** A Retry's failure sentence. */
  message?: string | null;
  /** Polling has stopped while still drafting. */
  stalled?: boolean;
  onRetry?: () => void;
}) {
  const drafting = isDrafting(draft);
  const failed = draft?.status === "failed";
  if (!version && !drafting && !failed) return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap items-center gap-3">
        {version ? <VersionPill version={version} /> : null}
        {version && canExport && opportunityId ? (
          <EstimateExport opportunityId={opportunityId} />
        ) : null}
        {version && version.uncovered_count > 0 ? (
          <p className="flex items-center gap-1.5 text-label text-foreground">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0 text-gap" />
            {uncoveredLabel(version.uncovered_count)}
          </p>
        ) : null}
        {drafting && stalled ? (
          <p className="text-label text-muted-foreground">{STILL_DRAFTING}</p>
        ) : drafting ? (
          <p className="flex items-center gap-2 text-label" data-status={draft?.status}>
            <span
              aria-hidden="true"
              data-testid="running-dot"
              className="size-1.5 shrink-0 animate-pulse rounded-full bg-agent motion-reduce:animate-none"
            />
            {DRAFTING}
          </p>
        ) : null}
      </div>
      {failed ? (
        <>
          <p className="flex items-center gap-1.5 text-label text-blocker" data-status="failed">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
            {draftFailure(draft.error_code)}
          </p>
          {canStart ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => onRetry?.()}
              className={actionClass}
            >
              {RETRY}
            </button>
          ) : null}
        </>
      ) : null}
      {message ? <span className="text-meta text-destructive">{message}</span> : null}
    </div>
  );
}

function retryMessage(result: StartEstimateDraftResult): string {
  switch (result.kind) {
    case "forbidden":
      return RETRY_NOT_ALLOWED;
    case "not-found":
      return NO_ACCESS_TO_OPPORTUNITY;
    default:
      return RETRY_FAILED;
  }
}

/** What the right pane shows: a line, or the Gap an Assumption was made from. */
type Selection = { kind: "line"; id: string } | { kind: "gap"; assumptionId: string };

/** The Estimate tab's content: the header, the grid and the Assumptions Register below it in
 * the main pane, and the selected line's (or Assumption's Gap's) inspector in the right pane
 * (opened if closed). While a draft or the Assumption proposals are queued or running the
 * Estimate is re-read every 2 s: paused while the tab is hidden, and stopped after 15
 * minutes. A selected line that a new version replaced leaves the pane showing "Nothing
 * selected." Lines of the draft are editable for those who may edit them (Story 8.2), with
 * a note when a re-draft could not carry some edits; Retry only for those who may start a
 * draft, Accept for those who may accept Assumptions. */
export function EstimateSection({
  opportunityId,
  initial,
}: {
  opportunityId: string;
  initial: EstimateView;
}) {
  const announce = useAnnounce();
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [view, setView] = useState<EstimateView>(initial);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  /** The element to focus when the pane closes after a keyboard open. */
  const returnFocusTo = useRef<string | null>(null);
  const [syncedFrom, setSyncedFrom] = useState(initial);
  const [stalled, setStalled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  /** Bumped after every poll, so the next one is scheduled. */
  const [pollTick, setPollTick] = useState(0);
  /** Bumped on every local change (a Retry); a poll that started before one is dropped. */
  const mutation = useRef(0);
  const draftingSince = useRef<number | null>(null);
  const [visible, setVisible] = useState(true);
  const drafting = isDrafting(view.draft);
  const proposing = isProposing(view.version);
  const working = drafting || proposing;
  /** The view as last rendered, for the poll to tell what finished. */
  const viewRef = useRef(view);
  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  // New data from the server (e.g. a navigation refresh) replaces the local copy.
  if (initial !== syncedFrom) {
    setSyncedFrom(initial);
    setView(initial);
    setStalled(false);
  }

  const lines = view.version?.sections.flatMap((section) => section.lines) ?? [];
  const register = view.version
    ? [...view.version.assumptions.conditions, ...view.version.assumptions.contingencies]
    : [];
  const selected =
    selection?.kind === "line" ? (lines.find((line) => line.id === selection.id) ?? null) : null;
  const selectedAssumption =
    selection?.kind === "gap"
      ? (register.find((a) => a.id === selection.assumptionId) ?? null)
      : null;

  // The pane's content unmounts on close: reopening it must not take focus again.
  const [paneWasOpen, setPaneWasOpen] = useState(rightPaneOpen);
  if (paneWasOpen !== rightPaneOpen) {
    setPaneWasOpen(rightPaneOpen);
    if (!rightPaneOpen) setFocusRequest(0);
  }

  // When the pane closes after a keyboard open, focus goes back to the line, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(id)?.focus();
    }
  }, [rightPaneOpen]);

  function open(line: EstimateLine, viaKeyboard: boolean) {
    setSelection({ kind: "line", id: line.id });
    returnFocusTo.current = viaKeyboard ? `[data-line-id="${line.id}"]` : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function openGap(assumption: Assumption, viaKeyboard: boolean) {
    setSelection({ kind: "gap", assumptionId: assumption.id });
    returnFocusTo.current = viaKeyboard
      ? `[data-assumption-id="${assumption.id}"] [data-gap-chip]`
      : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  useEffect(() => {
    const onVisibility = () => setVisible(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    if (!working) {
      draftingSince.current = null;
      return;
    }
    draftingSince.current ??= Date.now();
    if (!visible) return;
    if (Date.now() - draftingSince.current >= DRAFT_POLL_LIMIT_MS) {
      // Past the limit (e.g. hidden through it): say so instead of pulsing forever.
      setStalled(true);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(async () => {
      const startedAt = mutation.current;
      try {
        const result = await loadEstimate(opportunityId);
        if (!cancelled && result.kind === "ok" && mutation.current === startedAt) {
          const before = viewRef.current;
          setView(result.estimate);
          const { draft, version } = result.estimate;
          if (isDrafting(before.draft) && !isDrafting(draft)) {
            announce(
              draft?.status === "failed"
                ? draftFailure(draft.error_code)
                : version
                  ? versionLabel(version)
                  : NOTHING_TO_ESTIMATE,
            );
          } else if (isProposing(before.version) && version && !isProposing(version)) {
            announce(`Assumptions Register: ${registerSummary(version.counts)}`);
          }
        }
      } catch {
        // A failed poll is retried on the next tick.
      }
      if (cancelled) return;
      const since = draftingSince.current;
      if (since !== null && Date.now() - since >= DRAFT_POLL_LIMIT_MS) setStalled(true);
      setPollTick((tick) => tick + 1);
    }, DRAFT_POLL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [working, visible, opportunityId, pollTick, announce]);

  /** Story 8.2: save a line's change with its reason; the grid re-renders from the server's
   * Estimate. */
  async function saveLine(
    line: EstimateLine,
    change: LineChange,
    reason: string,
    rowVersion: number,
  ): Promise<EditOutcome> {
    let result: EstimateLineEditResult;
    try {
      result = await editEstimateLine({
        opportunityId,
        lineId: line.id,
        rowVersion,
        ...(change.effortHours !== undefined ? { effortHours: change.effortHours } : {}),
        ...(change.roleMix !== undefined ? { roleMix: change.roleMix } : {}),
        reason,
      });
    } catch {
      result = { kind: "error" };
    }
    let outcome: EditOutcome;
    switch (result.kind) {
      case "ok":
        mutation.current += 1;
        setView(result.estimate);
        announce(`Saved: ${line.title}`);
        return { ok: true };
      case "stale":
        outcome = { ok: false, message: result.message, reload: true };
        break;
      case "not-draft":
        outcome = { ok: false, message: VERSION_REPLACED, reload: true };
        break;
      case "invalid":
        outcome = { ok: false, message: result.detail };
        break;
      case "forbidden":
        outcome = { ok: false, message: EDIT_NOT_ALLOWED };
        break;
      case "not-found":
        outcome = { ok: false, message: NO_ACCESS_TO_OPPORTUNITY };
        break;
      default:
        outcome = { ok: false, message: EDIT_SAVE_FAILED };
    }
    announce(outcome.message);
    return outcome;
  }

  async function reloadEstimate() {
    try {
      const loaded = await loadEstimate(opportunityId);
      if (loaded.kind === "ok") {
        mutation.current += 1;
        setView(loaded.estimate);
        announce("Reloaded the Estimate");
      }
    } catch {
      // The tab stays as it is.
    }
  }

  async function retry() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: StartEstimateDraftResult;
    try {
      result = await startEstimateDraft(opportunityId);
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      const { draft } = result;
      mutation.current += 1;
      draftingSince.current = null;
      setStalled(false);
      setView((current) => ({ ...current, draft }));
      announce(DRAFTING);
    } else if (result.kind === "conflict") {
      // One is already queued or running: show what is stored now.
      try {
        const loaded = await loadEstimate(opportunityId);
        if (loaded.kind === "ok") {
          mutation.current += 1;
          setView(loaded.estimate);
        }
      } catch {
        // The tab stays as it is.
      }
    } else {
      const sentence = retryMessage(result);
      setMessage(sentence);
      announce(sentence);
    }
  }

  const { version, draft } = view;
  const succeeded = draft?.status === "succeeded";
  return (
    <div className="flex flex-col gap-4">
      <EstimateHeader
        version={version}
        draft={draft}
        canStart={view.can_start_draft}
        opportunityId={opportunityId}
        canExport={view.can_export}
        busy={busy}
        message={message}
        stalled={stalled}
        onRetry={() => void retry()}
      />
      {version ? (
        <>
          {version.uncarried_edit_count > 0 ? (
            <p className="flex items-center gap-1.5 text-label text-foreground" data-uncarried="">
              <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0 text-gap" />
              {uncarriedEditsNote(
                version.uncarried_edit_count,
                version.uncarried_edits_from_version,
              )}
            </p>
          ) : null}
          <EstimateGrid
            version={version}
            selectedId={selected?.id ?? null}
            onOpen={open}
            canEdit={view.can_edit_lines}
            onSave={saveLine}
            onReload={() => void reloadEstimate()}
            opportunityId={opportunityId}
          />
          <AssumptionsRegister
            opportunityId={opportunityId}
            version={version}
            canAccept={view.can_accept_assumptions}
            selectedId={selectedAssumption?.id ?? null}
            onChanged={(estimate) => {
              mutation.current += 1;
              setView(estimate);
            }}
            onOpenGap={openGap}
            canRetry={view.can_start_draft && !drafting}
            retryBusy={busy}
            onRetry={() => void retry()}
          />
        </>
      ) : succeeded ? (
        <p className="text-muted-foreground">{NOTHING_TO_ESTIMATE}</p>
      ) : !drafting && draft?.status !== "failed" ? (
        <p className="text-muted-foreground">{NO_ESTIMATE}</p>
      ) : null}
      {selected ? (
        <RightPaneContent>
          <EstimateInspector key={selected.id} line={selected} focusRequest={focusRequest} />
        </RightPaneContent>
      ) : selectedAssumption ? (
        <RightPaneContent>
          <OriginGapInspector
            key={selectedAssumption.id}
            gap={selectedAssumption.origin}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </div>
  );
}
