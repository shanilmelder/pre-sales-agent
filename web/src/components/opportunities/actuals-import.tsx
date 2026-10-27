"use client";

import { DownloadIcon, TriangleAlertIcon, UploadIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import {
  applyActualsImport,
  loadActualsImport,
  loadLatestActualsImport,
  retryActualsImport,
  uploadActualsImport,
  type ActualsImportResult,
} from "@/app/opportunities/actions";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { ParseStatusPill } from "@/components/opportunities/sources-list";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  ACTUALS_REASON_MAX,
  BATCH_REASON_LABEL,
  CHECK_AGAIN,
  CHOOSE_FILE,
  CONFIRM_IMPORT,
  DASH,
  DOWNLOAD_TEMPLATE,
  EXCLUDE_INVALID,
  IMPORT_ACCEPT,
  IMPORT_FAILED,
  IMPORT_FORBIDDEN,
  IMPORT_FROM_FILE,
  IMPORT_HINT,
  IMPORT_INTRO,
  IMPORT_STALE,
  IMPORT_TITLE,
  NOT_IMPORTABLE,
  REPEAT_TICK,
  RETRY,
  STILL_READING,
  TEMPLATE_FAILED,
  UPLOAD_FAILED,
  actualsTemplateUrl,
  causeLabel,
  hours,
  importBlocked,
  importPillStatus,
  importSummary,
  isImportPending,
  kindLabel,
  rowProblems,
  type ActualsImportView,
  type ActualsView,
  type ImportRowView,
} from "@/lib/actuals";
import { PARSE_POLL_LIMIT_MS, PARSE_POLL_MS } from "@/lib/sources";

const STATUS_WORDS: Record<ImportRowView["status"], string> = {
  create: "To create",
  correct: "To correct",
  invalid: "Invalid",
  skipped: "Skipped",
};

/** Fetch the template through the web route and hand the file to the browser. */
async function downloadTemplate(opportunityId: string): Promise<string | null> {
  let response: Response;
  try {
    response = await fetch(actualsTemplateUrl(opportunityId), { credentials: "same-origin" });
  } catch {
    return TEMPLATE_FAILED;
  }
  if (!response.ok) {
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) return body.detail;
    } catch {
      // Not problem+json: the general sentence.
    }
    return TEMPLATE_FAILED;
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "actuals-template.xlsx";
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return null;
}

function failureText(result: Exclude<ActualsImportResult, { kind: "ok" }>): string {
  switch (result.kind) {
    case "rejected":
      return result.reason;
    case "conflict":
      return result.detail ?? IMPORT_FAILED;
    case "forbidden":
      return IMPORT_FORBIDDEN;
    default:
      return UPLOAD_FAILED;
  }
}

/** **Import from file** on the Actuals tab (Story 10.2): the header's outline button opens the
 * mockup's dialog with **Download template** (.xlsx, one row per Baseline line) and **Choose
 * file** (.xlsx or .csv). The import row shows the Sources parse pill while the worker reads the
 * file (polled), or a red **Parse failed** with the reason and **Retry**. The preview lists the
 * rows to create, to correct and the invalid ones with their reasons; invalid rows can be
 * excluded, corrections without a reason of their own take one batch reason, and a repeated
 * file needs a tick. **Confirm** applies every row or none (`If-Match` the preview's tab
 * version; a 412 refreshes the preview). Delivery managers only: the tab renders it only for
 * them. While `disabledReason` is set (the table has unsaved edits, which applying would
 * drop) the button is `aria-disabled` with the reason as its tooltip. */
export function ActualsImport({
  opportunityId,
  causes,
  onApplied,
  disabledReason = null,
}: {
  opportunityId: string;
  causes: ActualsView["causes"];
  onApplied: (view: ActualsView) => void;
  disabledReason?: string | null;
}) {
  const announce = useAnnounce();
  const ids = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<ActualsImportView | null>(null);
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [reason, setReason] = useState("");
  const [repeatTicked, setRepeatTicked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [serverErrors, setServerErrors] = useState<string[]>([]);
  const pollStarted = useRef<number>(0);
  /** The poll window passed or a poll failed: the dialog offers Check again. */
  const [pollStopped, setPollStopped] = useState(false);

  function startPolling() {
    pollStarted.current = Date.now();
    setPollStopped(false);
  }

  const show = useCallback((next: ActualsImportView | null) => {
    setCurrent(next);
    setServerErrors([]);
  }, []);

  function reset() {
    setExcluded(new Set());
    setReason("");
    setRepeatTicked(false);
    setMessage(null);
    setStale(false);
    setServerErrors([]);
  }

  async function changeOpen(next: boolean) {
    setOpen(next);
    if (!next) return;
    reset();
    show(null);
    const loaded = await loadLatestActualsImport(opportunityId);
    if (loaded.kind === "ok" && loaded.latest && loaded.latest.status !== "applied") {
      startPolling();
      show(loaded.latest);
    }
  }

  // Poll while the worker reads the file.
  const pending = isImportPending(current);
  const currentId = current?.id ?? null;
  useEffect(() => {
    if (!open || !pending || pollStopped || currentId === null) return;
    const timer = setTimeout(async () => {
      if (Date.now() - pollStarted.current > PARSE_POLL_LIMIT_MS) {
        setPollStopped(true);
        return;
      }
      const loaded = await loadActualsImport(opportunityId, currentId);
      if (loaded.kind === "ok") show(loaded.imported);
      else setPollStopped(true);
    }, PARSE_POLL_MS);
    return () => clearTimeout(timer);
  }, [open, pending, pollStopped, currentId, current, opportunityId, show]);

  async function onCheckAgain() {
    if (!current || busy) return;
    setBusy(true);
    try {
      const loaded = await loadActualsImport(opportunityId, current.id);
      if (loaded.kind === "ok") {
        startPolling();
        show(loaded.imported);
      }
    } finally {
      setBusy(false);
    }
  }

  async function onTemplate() {
    if (busy) return;
    setBusy(true);
    try {
      const failed = await downloadTemplate(opportunityId);
      setMessage(failed);
      if (!failed) announce("Template downloaded");
    } finally {
      setBusy(false);
    }
  }

  async function onFile(file: File | undefined) {
    if (!file || busy) return;
    setBusy(true);
    reset();
    try {
      const form = new FormData();
      form.append("opportunityId", opportunityId);
      form.append("file", file, file.name);
      const result = await uploadActualsImport(form);
      if (result.kind === "ok") {
        startPolling();
        show(result.imported);
        announce(`${file.name} uploaded. Reading the file.`);
      } else {
        setMessage(failureText(result));
      }
    } finally {
      setBusy(false);
    }
  }

  async function onRetry() {
    if (!current || busy) return;
    setBusy(true);
    try {
      const result = await retryActualsImport(opportunityId, current.id);
      if (result.kind === "ok") {
        startPolling();
        show(result.imported);
        setMessage(null);
      } else {
        setMessage(failureText(result));
      }
    } finally {
      setBusy(false);
    }
  }

  async function refresh() {
    if (!current) return;
    const loaded = await loadActualsImport(opportunityId, current.id);
    if (loaded.kind === "ok") show(loaded.imported);
  }

  const blocked = current
    ? importBlocked(current, excluded, reason, repeatTicked)
    : "Choose a file first.";

  async function onConfirm() {
    if (!current || busy || blocked !== null) return;
    setBusy(true);
    setMessage(null);
    setStale(false);
    try {
      const result = await applyActualsImport({
        opportunityId,
        importId: current.id,
        rowVersion: current.row_version,
        excludedRows: [...excluded],
        reason: reason.trim() ? reason : undefined,
        confirmRepeat: repeatTicked,
      });
      switch (result.kind) {
        case "ok": {
          const applied = result.applied.imported.applied;
          onApplied(result.applied.actuals);
          setOpen(false);
          announce(
            `Actuals imported: ${applied?.created ?? 0} created, ${applied?.corrected ?? 0} corrected`,
          );
          return;
        }
        case "invalid":
          setServerErrors(result.errors.map((e) => e.message));
          return;
        case "stale":
          setStale(true);
          await refresh();
          return;
        case "repeated":
          setMessage(result.detail ?? IMPORT_FAILED);
          await refresh();
          return;
        case "conflict":
          setMessage(result.detail ?? IMPORT_FAILED);
          return;
        case "forbidden":
          setMessage(IMPORT_FORBIDDEN);
          return;
        default:
          setMessage(IMPORT_FAILED);
      }
    } finally {
      setBusy(false);
    }
  }

  function toggle(row: number, include: boolean) {
    setExcluded((was) => {
      const next = new Set(was);
      if (include) next.delete(row);
      else next.add(row);
      return next;
    });
  }

  // Parsed, but delivery closed or the Baseline went since: nothing can be imported now.
  const unimportable = current?.status === "parsed" && current.estimate_version === null;
  const rows = current?.status === "parsed" ? current.rows.filter((r) => r.status !== "skipped") : [];
  const invalidRows = rows.filter((r) => r.problems.length > 0 && !excluded.has(r.row));
  const needsBatchReason = rows.some(
    (r) => r.status === "correct" && r.reason_missing && !excluded.has(r.row),
  );

  return (
    <Dialog open={open} onOpenChange={(next) => void changeOpen(next)}>
      {disabledReason ? (
        <Tooltip>
          <TooltipTrigger
            render={<Button type="button" variant="outline" className="text-control" aria-disabled="true" />}
          >
            {IMPORT_FROM_FILE}
            <span className="sr-only">{`. ${disabledReason}`}</span>
          </TooltipTrigger>
          <TooltipContent>{disabledReason}</TooltipContent>
        </Tooltip>
      ) : (
        <Button
          type="button"
          variant="outline"
          className="text-control"
          onClick={() => void changeOpen(true)}
        >
          {IMPORT_FROM_FILE}
        </Button>
      )}
      <DialogContent
        showCloseButton={false}
        className="max-h-[85vh] w-[720px]! max-w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-[720px]"
      >
        <DialogHeader>
          <DialogTitle className="text-[20px] leading-7 font-semibold">{IMPORT_TITLE}</DialogTitle>
          <DialogDescription className="text-meta text-text-secondary">
            {IMPORT_INTRO}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" onClick={() => void onTemplate()} aria-disabled={busy || undefined}>
            <DownloadIcon aria-hidden="true" />
            {DOWNLOAD_TEMPLATE}
          </Button>
          <Button
            type="button"
            onClick={() => inputRef.current?.click()}
            aria-disabled={busy || undefined}
            aria-describedby={`${ids}-hint`}
          >
            <UploadIcon aria-hidden="true" />
            {CHOOSE_FILE}
          </Button>
          <span id={`${ids}-hint`} className="text-meta text-text-secondary">
            {IMPORT_HINT}
          </span>
          <input
            ref={inputRef}
            type="file"
            accept={IMPORT_ACCEPT}
            hidden
            tabIndex={-1}
            data-testid="actuals-file-input"
            onChange={(event) => {
              void onFile(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </div>

        {current ? (
          <div
            data-import-row=""
            className="flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg border border-border bg-surface px-3 py-2"
          >
            <span className="min-w-0 flex-1 text-body-strong [overflow-wrap:anywhere]">
              {current.filename}
            </span>
            <ParseStatusPill parse={{ status: importPillStatus(current.status), error_code: null }} />
            {current.status === "failed" ? (
              <>
                <span className="basis-full text-meta text-blocker">
                  {current.error_message ?? IMPORT_FAILED}
                </span>
                <span className="flex basis-full flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="xs"
                    disabled={busy}
                    onClick={() => void onRetry()}
                    aria-label={`${RETRY}: ${current.filename}`}
                  >
                    {RETRY}
                  </Button>
                  <span className="text-meta text-text-secondary">
                    You can still enter Actuals by line.
                  </span>
                </span>
              </>
            ) : pending && pollStopped ? (
              <span className="flex basis-full flex-wrap items-center gap-2" data-still-reading="">
                <span className="text-meta text-text-secondary">{STILL_READING}</span>
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  disabled={busy}
                  onClick={() => void onCheckAgain()}
                >
                  {CHECK_AGAIN}
                </Button>
              </span>
            ) : null}
          </div>
        ) : null}

        {stale ? <InlineAlert lead={IMPORT_STALE} onReload={() => void refresh()} /> : null}
        {message ? (
          <p role="alert" className="text-meta text-destructive">
            {message}
          </p>
        ) : null}

        {unimportable ? (
          <p id={`${ids}-unimportable`} className="text-meta text-text-secondary">
            {NOT_IMPORTABLE}
          </p>
        ) : null}

        {current?.status === "parsed" && !unimportable ? (
          <section aria-labelledby={`${ids}-preview`} className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <h3 id={`${ids}-preview`} className="flex-1 text-section">
                Preview
              </h3>
              <p className="text-meta tabular-nums" data-import-summary="">
                {importSummary(current.rows, excluded, reason)}
              </p>
              {invalidRows.length > 0 ? (
                <Button
                  type="button"
                  variant="outline"
                  size="xs"
                  onClick={() =>
                    setExcluded((was) => new Set([...was, ...invalidRows.map((r) => r.row)]))
                  }
                >
                  {EXCLUDE_INVALID}
                </Button>
              ) : null}
            </div>

            {current.repeat_message ? (
              <div className="flex flex-col gap-2 rounded-[10px] bg-gap-tint px-3.5 py-2.5 text-control text-gap">
                <p className="flex items-start gap-2.5">
                  <TriangleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  {current.repeat_message}
                </p>
                <label className="flex items-center gap-2 text-foreground">
                  <input
                    type="checkbox"
                    checked={repeatTicked}
                    onChange={(event) => setRepeatTicked(event.target.checked)}
                  />
                  {REPEAT_TICK}
                </label>
              </div>
            ) : null}

            {rows.length === 0 ? (
              <p className="text-meta text-text-secondary">
                Every row is blank: fill in Actual h for the lines to import.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-[12px] border border-border">
                <table className="w-full min-w-[640px] text-left text-[13px]">
                  <caption className="sr-only">Rows of the file</caption>
                  <thead className="bg-surface-alt text-[12px] font-medium text-text-secondary">
                    <tr>
                      <th scope="col" className="px-3 py-2">
                        Import
                      </th>
                      <th scope="col" className="px-3 py-2">
                        Row
                      </th>
                      <th scope="col" className="px-3 py-2">
                        Line
                      </th>
                      <th scope="col" className="px-3 py-2 text-right">
                        Actual h
                      </th>
                      <th scope="col" className="px-3 py-2">
                        Cause
                      </th>
                      <th scope="col" className="px-3 py-2">
                        Status
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => {
                      const left = excluded.has(row.row);
                      const problems = rowProblems(row, reason);
                      const invalid = problems.length > 0;
                      return (
                        <tr
                          key={row.row}
                          data-row={row.row}
                          className={`border-t border-border align-top ${left ? "text-text-secondary" : ""}`}
                        >
                          <td className="px-3 py-2">
                            <input
                              type="checkbox"
                              aria-label={`Import row ${row.row}`}
                              checked={!left}
                              onChange={(event) => toggle(row.row, event.target.checked)}
                            />
                          </td>
                          <td className="px-3 py-2 tabular-nums">{row.row}</td>
                          <td className="px-3 py-2">
                            {row.line_label ? `${row.line_label} ${row.line_title ?? ""}` : DASH}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {row.effort_hours === null ? DASH : hours(row.effort_hours)}
                            {row.kind === "milestone" ? (
                              <span className="block text-meta text-text-secondary">
                                {kindLabel(row.kind)}
                              </span>
                            ) : null}
                          </td>
                          <td className="px-3 py-2">{causeLabel(row.variance_cause, causes)}</td>
                          <td className="px-3 py-2">
                            {left ? (
                              "Excluded"
                            ) : invalid ? (
                              <>
                                <span className="font-medium text-blocker">Invalid</span>
                                {problems.map((p) => (
                                  <span key={p} className="block text-meta text-blocker">
                                    {p}
                                  </span>
                                ))}
                              </>
                            ) : (
                              STATUS_WORDS[row.status]
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {needsBatchReason ? (
              <div className="max-w-md">
                <ReasonInput
                  label={BATCH_REASON_LABEL}
                  value={reason}
                  onChange={setReason}
                  error={null}
                  disabled={busy}
                  max={ACTUALS_REASON_MAX}
                />
              </div>
            ) : null}

            {serverErrors.length > 0 ? (
              <ul role="alert" className="flex flex-col gap-0.5 text-meta text-destructive">
                {serverErrors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}

        <DialogFooter>
          {blocked && current?.status === "parsed" && !unimportable ? (
            <span id={`${ids}-blocked`} className="mr-auto self-center text-meta text-text-secondary">
              {blocked}
            </span>
          ) : null}
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button
            type="button"
            aria-disabled={blocked !== null || busy || undefined}
            aria-describedby={
              unimportable
                ? `${ids}-unimportable`
                : blocked && current?.status === "parsed"
                  ? `${ids}-blocked`
                  : undefined
            }
            onClick={() => void onConfirm()}
          >
            {CONFIRM_IMPORT}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
