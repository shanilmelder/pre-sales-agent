"use client";

import { ChevronDownIcon, CircleAlertIcon, DownloadIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { useAnnounce } from "@/components/shell/live-region";
import {
  EXPORT,
  EXPORT_FORMATS,
  EXPORTING,
  exportFailure,
  exportFailureReason,
  exportFileName,
  exportUrl,
  type ExportFormat,
} from "@/lib/estimates";

const buttonClass =
  "inline-flex h-6 shrink-0 items-center gap-1 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:cursor-default disabled:opacity-60 disabled:hover:bg-transparent";
const optionClass =
  "w-full rounded-sm px-2 py-1 text-left text-label outline-none hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

const FILE_TYPES = "application/vnd.openxmlformats-officedocument.";

class ExportError extends Error {
  constructor(readonly reason: string) {
    super(reason);
  }
}

/** Fetch the export and hand the file to the browser. Throws `ExportError` with the reason. */
async function download(opportunityId: string, format: ExportFormat): Promise<string> {
  let response: Response;
  try {
    response = await fetch(exportUrl(opportunityId, format), { credentials: "same-origin" });
  } catch {
    throw new ExportError(exportFailureReason(null));
  }
  const type = response.headers.get("Content-Type") ?? "";
  if (!response.ok) {
    let code: string | null = null;
    try {
      const body = (await response.json()) as { code?: unknown };
      code = typeof body.code === "string" ? body.code : null;
    } catch {
      // Not problem+json: the status says enough.
    }
    throw new ExportError(exportFailureReason(response.status, code));
  }
  if (!type.startsWith(FILE_TYPES)) {
    // A redirect to sign-in lands here as an HTML page.
    throw new ExportError(exportFailureReason(401));
  }
  const blob = await response.blob();
  const name =
    exportFileName(response.headers.get("Content-Disposition")) ?? `estimate.${format}`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
  return name;
}

/** The **Export** control in the Estimate header: a button that opens a short list of formats
 * ("Excel (.xlsx)", "Word (.docx)"); choosing one downloads the current draft version.
 * Keyboard: Enter/Space opens it, the arrow keys move between formats, Escape closes it and
 * returns focus to **Export**. On failure: "Export failed: <reason>" with **Retry**. */
export function EstimateExport({ opportunityId }: { opportunityId: string }) {
  const announce = useAnnounce();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [last, setLast] = useState<ExportFormat | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [open]);

  // Back to **Export** once it is enabled again (focus can't land on a disabled button).
  useEffect(() => {
    if (busy || !restoreFocus.current) return;
    restoreFocus.current = false;
    trigger.current?.focus();
  }, [busy]);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    return () => document.removeEventListener("pointerdown", onPointer);
  }, [open]);

  async function run(format: ExportFormat) {
    if (busy) return;
    setOpen(false);
    setLast(format);
    setFailure(null);
    setBusy(true);
    try {
      const name = await download(opportunityId, format);
      announce(`Exported ${name}`);
    } catch (error) {
      const sentence = exportFailure(
        error instanceof ExportError ? error.reason : exportFailureReason(-1),
      );
      setFailure(sentence);
      announce(sentence);
    } finally {
      setBusy(false);
      restoreFocus.current = true;
    }
  }

  function onListKey(event: KeyboardEvent<HTMLDivElement>) {
    const options = [...(list.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
    const at = options.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      trigger.current?.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      // From no option, ArrowDown goes to the first and ArrowUp to the last.
      const next = at === -1 ? (step === 1 ? 0 : options.length - 1) : at + step;
      options[(next + options.length) % options.length]?.focus();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div ref={root} className="relative flex flex-wrap items-center gap-2" data-export="">
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        disabled={busy}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" && !open) {
            event.preventDefault();
            setOpen(true);
          }
        }}
        className={buttonClass}
      >
        <DownloadIcon aria-hidden="true" className="size-3" />
        {busy ? EXPORTING : EXPORT}
        <ChevronDownIcon aria-hidden="true" className="size-3" />
      </button>
      {open ? (
        <div
          ref={list}
          id={listId}
          role="group"
          aria-label="Export format"
          onKeyDown={onListKey}
          className="absolute top-7 left-0 z-20 flex min-w-36 flex-col gap-0.5 rounded-md border border-border bg-popover p-1 shadow-md"
        >
          {EXPORT_FORMATS.map((f) => (
            <button
              key={f.value}
              type="button"
              data-format={f.value}
              onClick={() => void run(f.value)}
              className={optionClass}
            >
              {f.label}
            </button>
          ))}
        </div>
      ) : null}
      {failure ? (
        <>
          <p className="flex items-center gap-1.5 text-label text-blocker" data-export-failed="">
            <CircleAlertIcon aria-hidden="true" className="size-3 shrink-0" />
            {failure}
          </p>
          {last ? (
            <button
              type="button"
              disabled={busy}
              aria-label="Retry export"
              onClick={() => void run(last)}
              className={buttonClass}
            >
              Retry
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
