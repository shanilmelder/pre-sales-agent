"use client";

import { UploadIcon } from "lucide-react";
import { useId, useRef, useState, type DragEvent } from "react";

import { addSource, type AddSourceResult } from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import { NO_ACCESS_TO_OPPORTUNITY } from "@/lib/opportunities";
import { ACCEPTED_FILES, exceedsTransportLimit, TOO_LARGE, type Source } from "@/lib/sources";

type RowState = "uploading" | "added" | "rejected";
type Row = { key: number; name: string; state: RowState; message: string };

export const UPLOADING = "Uploading";
export const ADDED = "Added";
const NOT_A_COLLABORATOR = "Only the owner and collaborators can add Sources.";
const UPLOAD_FAILED = "The upload failed. Try again.";

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary";

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

/** Drop files, or choose them, to add them as Sources. Files go up one at a time; each gets
 * a row that shows Uploading, then Added ("Added as version N" when the bytes match an
 * existing Source) or the API's reason ("Rejected: .exe files aren't
 * allowed"). The API decides what is accepted. */
export function SourceUpload({
  opportunityId,
  onAdded,
}: {
  opportunityId: string;
  onAdded: (source: Source) => void;
}) {
  const announce = useAnnounce();
  const [rows, setRows] = useState<Row[]>([]);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const queue = useRef<Promise<void>>(Promise.resolve());
  const nextKey = useRef(0);
  const hintId = useId();

  function settle(key: number, name: string, state: RowState, message: string) {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, state, message } : row)));
    announce(`${name}: ${message}`);
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
    let result: AddSourceResult;
    try {
      result = await addSource(form);
    } catch {
      result = { kind: "error" };
    }
    if (result.kind === "ok") onAdded(result.source);
    const { state, message } = outcome(result);
    settle(key, file.name, state, message);
  }

  function add(files: readonly File[]) {
    if (files.length === 0) return;
    const added = files.map((file) => ({
      file,
      row: { key: nextKey.current++, name: file.name, state: "uploading" as const, message: UPLOADING },
    }));
    setRows((current) => [...current, ...added.map(({ row }) => row)]);
    for (const { file, row } of added) {
      // A throw (e.g. from onAdded) settles that row as failed so later files still go up.
      queue.current = queue.current
        .then(() => upload(row.key, file))
        .catch(() => settle(row.key, file.name, "rejected", UPLOAD_FAILED));
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    add(Array.from(event.dataTransfer?.files ?? []));
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-dragging={dragging || undefined}
        className="flex max-w-xl flex-col items-center gap-2 rounded-md border border-dashed border-border p-6 text-center data-[dragging]:border-primary data-[dragging]:bg-muted"
      >
        <UploadIcon aria-hidden className="size-4 text-muted-foreground" />
        <p id={hintId} className="text-body">
          Drop emails, notes, transcripts or documents here
        </p>
        <p className="text-meta text-muted-foreground">
          .eml, .msg, .txt, .vtt, .docx or .pdf, up to 50 MB each
        </p>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          aria-describedby={hintId}
          className={buttonClass}
        >
          Choose files
        </button>
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
      {rows.length > 0 ? (
        <ul aria-label="Uploads" className="flex max-w-xl flex-col">
          {rows.map((row) => (
            <li
              key={row.key}
              data-state={row.state}
              className="flex min-h-row items-center justify-between gap-3 border-b border-border"
            >
              <span className="min-w-0 truncate text-body">{row.name}</span>
              <span
                className={
                  row.state === "rejected"
                    ? "shrink-0 text-meta text-destructive"
                    : "shrink-0 text-meta text-muted-foreground"
                }
              >
                {row.message}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
