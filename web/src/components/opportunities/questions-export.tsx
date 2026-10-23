"use client";

import { ChevronDownIcon, CircleAlertIcon, DownloadIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { copyClarificationQuestions } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { EXPORTING, exportFailure, exportFileName } from "@/lib/estimates";
import {
  copiedCount,
  QUESTION_EXPORT_FORMATS,
  questionsExportFailureReason,
  questionsExportUrl,
  type QuestionExportFormat,
} from "@/lib/gaps";

/** The trigger's label. */
export const EXPORT_QUESTIONS = "Export questions";
const optionClass =
  "w-full rounded-sm px-2 py-1 text-left text-label outline-none hover:bg-muted focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

const FILE_TYPES: Record<"docx" | "eml", string> = {
  docx: "application/vnd.openxmlformats-officedocument.",
  eml: "message/rfc822",
};

class ExportError extends Error {
  constructor(readonly reason: string) {
    super(reason);
  }
}

/** Fetch a `.docx` or `.eml` export and hand the file to the browser. Throws `ExportError`
 * with the reason. */
async function download(opportunityId: string, format: "docx" | "eml"): Promise<string> {
  let response: Response;
  try {
    response = await fetch(questionsExportUrl(opportunityId, format), {
      method: "POST",
      credentials: "same-origin",
    });
  } catch {
    throw new ExportError(questionsExportFailureReason(null));
  }
  if (!response.ok) {
    let code: string | null = null;
    try {
      const body = (await response.json()) as { code?: unknown };
      code = typeof body.code === "string" ? body.code : null;
    } catch {
      // Not problem+json: the status says enough.
    }
    throw new ExportError(questionsExportFailureReason(response.status, code));
  }
  if (!(response.headers.get("Content-Type") ?? "").startsWith(FILE_TYPES[format])) {
    // A redirect to sign-in lands here as an HTML page.
    throw new ExportError(questionsExportFailureReason(401));
  }
  const blob = await response.blob();
  const name =
    exportFileName(response.headers.get("Content-Disposition")) ??
    `clarification-questions.${format}`;
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

/** Copy the approved questions to the clipboard; how many. Throws `ExportError`. */
async function copy(opportunityId: string): Promise<number> {
  let result;
  try {
    result = await copyClarificationQuestions(opportunityId);
  } catch {
    result = { kind: "error" as const };
  }
  switch (result.kind) {
    case "ok":
      break;
    case "nothing-approved":
      throw new ExportError(questionsExportFailureReason(409));
    case "forbidden":
      throw new ExportError(questionsExportFailureReason(403));
    case "not-found":
      throw new ExportError(questionsExportFailureReason(404));
    default:
      throw new ExportError(questionsExportFailureReason(-1));
  }
  try {
    await navigator.clipboard.writeText(result.text);
  } catch {
    throw new ExportError("the clipboard couldn't be written; allow clipboard access and retry");
  }
  return result.count;
}

/** The **Export questions** menu in the Gaps tab header (Story 4.6): "Copy", "Word (.docx)" and "Email
 * draft (.eml)" of the approved questions of open Gaps, grouped by topic, in customer wording
 * only. Copy puts the text on the clipboard and announces "N questions copied"; the files
 * download through a web route. Keyboard as the Estimate's Export: Enter/Space opens it, the
 * arrow keys move, Escape closes it and returns focus. On failure: "Export failed: <reason>"
 * with **Retry**. */
export function QuestionsExport({ opportunityId }: { opportunityId: string }) {
  const announce = useAnnounce();
  const listId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [last, setLast] = useState<QuestionExportFormat | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLDivElement>(null);
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [open]);

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

  async function run(format: QuestionExportFormat) {
    if (busy) return;
    setOpen(false);
    setLast(format);
    setFailure(null);
    setBusy(true);
    try {
      if (format === "copy") {
        announce(copiedCount(await copy(opportunityId)));
      } else {
        announce(`Exported ${await download(opportunityId, format)}`);
      }
    } catch (error) {
      const sentence = exportFailure(
        error instanceof ExportError ? error.reason : questionsExportFailureReason(-1),
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
      const next = at === -1 ? (step === 1 ? 0 : options.length - 1) : at + step;
      options[(next + options.length) % options.length]?.focus();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  }

  return (
    <div ref={root} className="relative flex flex-wrap items-center gap-2" data-questions-export="">
      <Button
        ref={trigger}
        type="button"
        variant="outline"
        size="sm"
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
      >
        <DownloadIcon aria-hidden="true" />
        {busy ? EXPORTING : EXPORT_QUESTIONS}
        <ChevronDownIcon aria-hidden="true" />
      </Button>
      {open ? (
        <div
          ref={list}
          id={listId}
          role="group"
          aria-label="Export questions as"
          onKeyDown={onListKey}
          className="absolute top-7 right-0 z-20 flex min-w-40 flex-col gap-0.5 rounded-md border border-border bg-popover p-1 shadow-md"
        >
          {QUESTION_EXPORT_FORMATS.map((f) => (
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
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              aria-label="Retry export"
              onClick={() => void run(last)}
            >
              Retry
            </Button>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
