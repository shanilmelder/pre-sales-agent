"use client";

import { CircleAlertIcon, UploadIcon, XIcon } from "lucide-react";
import {
  useEffect,
  useId,
  useImperativeHandle,
  useRef,
  useState,
  type DragEvent,
  type KeyboardEvent,
  type Ref,
} from "react";

import { addSource, addTextSource, type AddSourceResult } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import {
  ACCEPTED_FILES,
  CHOOSE_FILES,
  DROP_HINT,
  DROP_TITLE,
  exceedsTransportLimit,
  TOO_LARGE,
  type Source,
} from "@/lib/sources";

type RowState = "uploading" | "added" | "rejected";
type Row = { key: number; name: string; state: RowState; message: string };

export const UPLOADING = "Uploading";
export const ADDED = "Added";
/** The row name (and the API's version filename) of pasted text. */
export const PASTED_TEXT = "Pasted text";
const NOT_A_COLLABORATOR = "Only the owner and collaborators can add Sources.";
const UPLOAD_FAILED = "The upload failed. Try again.";
export const UPLOAD_REJECTED = "Upload rejected";
export const DISMISS = "Dismiss";

function outcome(result: AddSourceResult): { state: RowState; message: string } {
  switch (result.kind) {
    case "ok":
      // Same bytes as an existing Source: say it became that Source's next version.
      return {
        state: "added",
        message: result.source.version > 1 ? `Added as version ${result.source.version}` : ADDED,
      };
    case "rejected":
      return { state: "rejected", message: result.reason };
    case "forbidden":
      return { state: "rejected", message: NOT_A_COLLABORATOR };
    case "not-found":
      return { state: "rejected", message: NO_ACCESS_TO_OPPORTUNITY };
    default:
      return { state: "rejected", message: UPLOAD_FAILED };
  }
}

/** What the Sources list can ask of the upload area. */
export type SourceUploadHandle = {
  /** Opens the paste area (if closed) and focuses its text box ("Paste text instead"). */
  openPaste: () => void;
  /** Opens the file chooser (the empty Sources card's "Choose files"). */
  openChooser: () => void;
};

/** Drop files, choose them, or paste text to add them as Sources. Files and pastes go up one
 * at a time, in order; each gets a row under the drop zone that shows Uploading, then Added
 * ("Added as version N" when the bytes match an existing Source). A rejected one becomes a
 * dismissible alert above the drop zone, newest first, with the API's reason ("Rejected:
 * .exe files aren't allowed"). The API decides what is accepted. */
export function SourceUpload({
  opportunityId,
  onAdded,
  ref,
}: {
  opportunityId: string;
  onAdded: (source: Source) => void;
  ref?: Ref<SourceUploadHandle>;
}) {
  const announce = useAnnounce();
  const [rows, setRows] = useState<Row[]>([]);
  const [dragging, setDragging] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [pasteBusy, setPasteBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const chooseButtonRef = useRef<HTMLButtonElement>(null);
  const pasteButtonRef = useRef<HTMLButtonElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pasteAreaRef = useRef<HTMLDivElement>(null);
  const refocusPasteButton = useRef(false);
  /** Bumped whenever the paste area closes, so a late success can't close a reopened one. */
  const pasteSession = useRef(0);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const nextKey = useRef(0);
  const hintId = useId();
  const textareaId = useId();
  const pasteHintId = useId();
  const pasteAreaId = useId();

  useImperativeHandle(
    ref,
    () => ({
      openChooser() {
        inputRef.current?.click();
      },
      openPaste() {
        // Opening focuses the text box (the effect below); an open one is focused here.
        if (pasting) textareaRef.current?.focus();
        else setPasting(true);
      },
    }),
    [pasting],
  );

  useEffect(() => {
    if (pasting) {
      textareaRef.current?.focus();
    } else if (refocusPasteButton.current) {
      refocusPasteButton.current = false;
      pasteButtonRef.current?.focus();
    }
  }, [pasting]);

  function settle(key: number, name: string, state: RowState, message: string) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, state, message } : row)));
    // A rejection's alert (role="alert") announces itself.
    if (state !== "rejected") announce(`${name}: ${message}`);
  }

  /** Runs `call`, adds the Source on success and settles the row. */
  async function send(
    key: number,
    name: string,
    call: () => Promise<AddSourceResult>,
  ): Promise<AddSourceResult> {
    let result: AddSourceResult;
    try {
      result = await call();
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") onAdded(result.source);
    const { state, message } = outcome(result);
    settle(key, name, state, message);
    return result;
  }

  async function upload(key: number, file: File) {
    if (exceedsTransportLimit(file.size)) {
      // Past what the web server can carry; the API would reject it with this sentence.
      settle(key, file.name, "rejected", TOO_LARGE);
      return;
    }
    const form = new FormData();
    form.append("opportunityId", opportunityId);
    form.append("file", file);
    await send(key, file.name, () => addSource(form));
  }

  function newRow(name: string): Row {
    return { key: nextKey.current++, name, state: "uploading", message: UPLOADING };
  }

  function add(files: readonly File[]) {
    if (files.length === 0) return;
    const added = files.map((file) => ({ file, row: newRow(file.name) }));
    setRows((current) => [...current, ...added.map(({ row }) => row)]);
    for (const { file, row } of added) {
      // A throw (e.g. from onAdded) settles that row as failed so later files still go up.
      queue.current = queue.current
        .then(() => upload(row.key, file))
        .catch(() => settle(row.key, file.name, "rejected", UPLOAD_FAILED));
    }
  }

  function closePaste(returnFocus: boolean) {
    pasteSession.current++;
    refocusPasteButton.current = returnFocus;
    setPasting(false);
    setPasteText("");
  }

  function submitPaste() {
    if (pasteBusy || pasteText.trim() === "") return;
    const text = pasteText;
    const session = pasteSession.current;
    const row = newRow(PASTED_TEXT);
    setRows((current) => [...current, row]);
    setPasteBusy(true);
    queue.current = queue.current
      .then(async () => {
        const result = await send(row.key, PASTED_TEXT, () => addTextSource(opportunityId, text));
        // Added: the area closes and clears. Rejected: it keeps the text to fix and retry.
        if (result.kind === "ok" && session === pasteSession.current) {
          closePaste(pasteAreaRef.current?.contains(document.activeElement) === true);
        }
      })
      .catch(() => settle(row.key, PASTED_TEXT, "rejected", UPLOAD_FAILED))
      .finally(() => setPasteBusy(false));
  }

  function onPasteKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // Keys that confirm or cancel an IME composition belong to the IME.
    if (event.nativeEvent.isComposing) return;
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      submitPaste();
    } else if (event.key === "Escape") {
      // Esc closes this area only, not a shell layer underneath.
      event.preventDefault();
      event.stopPropagation();
      // While a paste is pending the area stays as it is until the API answers.
      if (!pasteBusy) closePaste(true);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    add(Array.from(event.dataTransfer?.files ?? []));
  }

  /** Removes a rejection alert; focus, if it was on its Dismiss, goes to Choose files. */
  function dismiss(key: number, hadFocus: boolean) {
    setRows((current) => current.filter((row) => row.key !== key));
    if (hadFocus) chooseButtonRef.current?.focus();
  }

  const canSubmitPaste = !pasteBusy && pasteText.trim() !== "";
  const rejected = rows.filter((row) => row.state === "rejected").reverse();
  const progress = rows.filter((row) => row.state !== "rejected");

  return (
    <div className="flex flex-col gap-3">
      {rejected.map((row) => (
        <div
          key={row.key}
          role="alert"
          data-state="rejected"
          className="flex items-start gap-3 rounded-lg bg-blocker-tint px-4 py-3 text-blocker"
        >
          <CircleAlertIcon aria-hidden className="mt-0.5 size-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-body-strong [overflow-wrap:anywhere]">
              {UPLOAD_REJECTED}: {row.name}
            </p>
            <p className="text-body text-foreground">{row.message}</p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label={`${DISMISS}: ${row.name}`}
            className="text-blocker hover:bg-transparent hover:text-blocker"
            onClick={(event) => dismiss(row.key, event.currentTarget === document.activeElement)}
          >
            <XIcon aria-hidden className="size-4" />
          </Button>
        </div>
      ))}
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="source-drop-zone"
        data-dragging={dragging || undefined}
        className="flex flex-col items-start gap-4 rounded-xl border-2 border-dashed border-border-strong bg-surface p-8 data-[dragging]:border-primary data-[dragging]:bg-muted md:flex-row md:items-center md:gap-6"
      >
        <span className="flex size-12 shrink-0 items-center justify-center rounded-xl bg-primary-tint text-primary-text">
          <UploadIcon aria-hidden className="size-[22px]" />
        </span>
        <div className="min-w-0 flex-1">
          <p id={hintId} className="text-section">
            {DROP_TITLE}
          </p>
          <p className="mt-0.5 text-body text-text-secondary">{DROP_HINT}</p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            ref={chooseButtonRef}
            type="button"
            onClick={() => inputRef.current?.click()}
            aria-describedby={hintId}
          >
            {CHOOSE_FILES}
          </Button>
          <Button
            ref={pasteButtonRef}
            type="button"
            variant="outline"
            className="h-[38px] px-4"
            aria-expanded={pasting}
            aria-controls={pasteAreaId}
            onClick={() => (pasting ? textareaRef.current?.focus() : setPasting(true))}
          >
            Paste text
          </Button>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPTED_FILES}
          hidden
          tabIndex={-1}
          data-testid="source-file-input"
          onChange={(event) => {
            add(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
      </div>
      {pasting ? (
        <div ref={pasteAreaRef} id={pasteAreaId} className="flex max-w-xl flex-col gap-1">
          <label htmlFor={textareaId} className="text-label">
            Text to add
          </label>
          <textarea
            ref={textareaRef}
            id={textareaId}
            rows={8}
            value={pasteText}
            onChange={(event) => setPasteText(event.target.value)}
            onKeyDown={onPasteKeyDown}
            readOnly={pasteBusy}
            aria-describedby={pasteHintId}
            className="w-full rounded-md border border-input bg-transparent px-2 py-1 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
          />
          <p id={pasteHintId} className="text-meta text-muted-foreground">
            A call note, chat or email body, up to 1,000,000 characters, added as a Note.
            Ctrl+Enter or ⌘+Enter adds it, Esc cancels.
          </p>
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!canSubmitPaste}
              onClick={submitPaste}
            >
              Add
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={pasteBusy}
              onClick={() => closePaste(true)}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
      {progress.length > 0 ? (
        <ul aria-label="Uploads" className="flex flex-col">
          {progress.map((row) => (
            <li
              key={row.key}
              data-state={row.state}
              className="flex min-h-row items-center justify-between gap-3 border-b border-border"
            >
              <span className="min-w-0 truncate text-body">{row.name}</span>
              <span className="shrink-0 text-meta text-muted-foreground">{row.message}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
