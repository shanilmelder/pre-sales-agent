"use client";

import { UploadIcon } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

import {
  createEstimateVersion,
  replyToReviewRequest,
  type ReplyResult,
} from "@/app/opportunities/actions";
import { EvidencePicker } from "@/components/opportunities/finding-decisions";
import { ReasonInput } from "@/components/opportunities/reason-input";
import { SourceUpload } from "@/components/opportunities/source-upload";
import { useAnnounce } from "@/components/shell/live-region";
import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Select } from "@/components/ui/select";
import type { EvidenceOption } from "@/lib/findings";
import { codePointLength } from "@/lib/opportunities";
import {
  ADD_SOURCE,
  ALTERNATIVE_DRAFT,
  HIDE_ADD_SOURCE,
  LINK_ALTERNATIVE,
  NEW_VERSION,
  NEW_VERSION_FAILED,
  NEW_VERSION_FORBIDDEN,
  REPLY,
  REPLY_FAILED,
  REPLY_FORBIDDEN,
  REPLY_MAX,
  REPLY_SENT,
  newVersionAnnouncement,
  replyLabel,
  type CreatedVersion,
  type RecordedReply,
  type ReviewPanel,
} from "@/lib/reviews";
import { cn } from "@/lib/utils";

/** The outline buttons of the review block (the mockup's 13px, 7×14 outline style). */
export const outlineButtonClass = "border-border-strong bg-surface";

type Problem = { kind: "stale"; lead: string } | { kind: "message"; text: string };

function problemOf(result: Exclude<ReplyResult, { kind: "ok" }>): Problem {
  switch (result.kind) {
    case "stale":
      return { kind: "stale", lead: result.detail };
    case "invalid":
      return { kind: "message", text: result.detail };
    case "forbidden":
    case "not-found":
      return { kind: "message", text: REPLY_FORBIDDEN };
    default:
      return { kind: "message", text: REPLY_FAILED };
  }
}

/** The author's Reply composer (Story 9.4; built from the review block's parts): the "Reply to
 * {reviewer} (required)" reason box, the Evidence picker with its chips, **Add Source** (the
 * upload area, so a new Source becomes pickable), **Link as alternative** (a toggle, only when
 * `can_link_alternative`, with the draft to offer) and **Reply**. A 412 shows "Changed by {name}
 * since you opened it." with Reload; nothing is sent. */
export function ReplyComposer({
  opportunityId,
  panel,
  onReplied,
  onReload,
  beside,
}: {
  opportunityId: string;
  panel: ReviewPanel;
  onReplied: (recorded: RecordedReply) => void;
  onReload: () => Promise<void> | void;
  /** Shown next to **Reply** (e.g. **New version** after a request for an alternative). */
  beside?: ReactNode;
}) {
  const announce = useAnnounce();
  const selectId = useId();
  const [message, setMessage] = useState("");
  const [chosen, setChosen] = useState<EvidenceOption[]>([]);
  const [uploading, setUploading] = useState(false);
  const [pickerKey, setPickerKey] = useState(0);
  const [linking, setLinking] = useState(false);
  const [alternative, setAlternative] = useState(panel.alternative_draft?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [reloading, setReloading] = useState(false);
  const length = codePointLength(message.trim());
  const linkable = panel.can_link_alternative && panel.alternative_draft !== null;
  // The draft may appear after mount (a reload): fall back to it.
  const chosenAlternative = alternative || panel.alternative_draft?.id || "";
  const ready =
    length >= 1 && length <= REPLY_MAX && (!linking || !linkable || chosenAlternative !== "");

  async function send() {
    if (!ready || busy) return;
    setBusy(true);
    setProblem(null);
    let result: ReplyResult;
    try {
      result = await replyToReviewRequest({
        opportunityId,
        requestId: panel.request.id,
        rowVersion: panel.request.row_version,
        message,
        evidence: chosen.map(({ kind, id, version }) => ({ kind, id, version })),
        ...(linking && linkable && chosenAlternative
          ? { alternativeVersionId: chosenAlternative }
          : {}),
      });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      setMessage("");
      setChosen([]);
      setLinking(false);
      setUploading(false);
      announce(REPLY_SENT);
      onReplied(result.value);
      return;
    }
    const next = problemOf(result);
    setProblem(next);
    announce(next.kind === "stale" ? next.lead : next.text);
  }

  async function reload() {
    setReloading(true);
    try {
      await onReload();
      setProblem(null);
    } finally {
      setReloading(false);
    }
  }

  return (
    <div
      role="group"
      aria-label={REPLY}
      className="flex flex-col gap-3 border-t border-border pt-4"
      data-reply-composer=""
    >
      <ReasonInput
        label={replyLabel(panel.request.reviewer.name)}
        value={message}
        onChange={setMessage}
        error={null}
        disabled={busy}
        max={REPLY_MAX}
      />
      <EvidencePicker
        // A remount reads the options again, so a Source added below becomes pickable.
        key={pickerKey}
        opportunityId={opportunityId}
        chosen={chosen}
        onChange={setChosen}
        error={null}
        disabled={busy}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          className={outlineButtonClass}
          aria-expanded={uploading}
          disabled={busy}
          onClick={() => setUploading((open) => !open)}
        >
          <UploadIcon aria-hidden="true" />
          {uploading ? HIDE_ADD_SOURCE : ADD_SOURCE}
        </Button>
        {linkable ? (
          <Button
            type="button"
            variant="outline"
            className={outlineButtonClass}
            aria-pressed={linking}
            disabled={busy}
            onClick={() => setLinking((on) => !on)}
          >
            {LINK_ALTERNATIVE}
          </Button>
        ) : null}
      </div>
      {uploading ? (
        <SourceUpload opportunityId={opportunityId} onAdded={() => setPickerKey((k) => k + 1)} />
      ) : null}
      {linking && linkable && panel.alternative_draft ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={selectId} className="text-meta text-muted-foreground">
            {ALTERNATIVE_DRAFT}
          </label>
          <Select
            id={selectId}
            value={chosenAlternative}
            disabled={busy}
            onChange={(event) => setAlternative(event.target.value)}
          >
            <option value={panel.alternative_draft.id}>
              {`Draft v${panel.alternative_draft.version}`}
            </option>
          </Select>
        </div>
      ) : null}
      {problem?.kind === "stale" ? (
        <InlineAlert lead={problem.lead} onReload={() => void reload()} reloading={reloading} />
      ) : problem ? (
        <p
          role="alert"
          className="rounded-md border border-blocker/30 bg-blocker-tint px-3 py-2 text-meta text-blocker"
        >
          {problem.text}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          disabled={!ready || busy}
          className={cn(busy && "cursor-progress")}
          onClick={() => void send()}
        >
          {REPLY}
        </Button>
        {beside}
      </div>
    </div>
  );
}

/** **New version** (Story 9.4): starts a new draft from the rejected or approved version
 * `versionId`, with its lines, Assumptions and Risks. Shown only when the API's
 * `can_create_version` is set; a failure shows the API's sentence next to it. */
export function NewVersionButton({
  opportunityId,
  versionId,
  onCreated,
  describedBy,
}: {
  opportunityId: string;
  versionId: string;
  onCreated: (created: CreatedVersion) => void;
  /** The id of the text the button is about (the reviewer's reason). */
  describedBy?: string;
}) {
  const announce = useAnnounce();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function create() {
    if (busy) return;
    setBusy(true);
    setMessage(null);
    let result: Awaited<ReturnType<typeof createEstimateVersion>>;
    try {
      result = await createEstimateVersion({ opportunityId, versionId });
    } catch {
      result = { kind: "error" };
    }
    setBusy(false);
    if (result.kind === "ok") {
      announce(newVersionAnnouncement(result.value.version));
      onCreated(result.value);
      return;
    }
    const text =
      result.kind === "invalid"
        ? result.detail
        : result.kind === "forbidden" || result.kind === "not-found"
          ? NEW_VERSION_FORBIDDEN
          : NEW_VERSION_FAILED;
    setMessage(text);
    announce(text);
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-new-version="">
      <Button
        type="button"
        variant="outline"
        className={outlineButtonClass}
        aria-describedby={describedBy}
        disabled={busy}
        onClick={() => void create()}
      >
        {NEW_VERSION}
      </Button>
      {message ? (
        <span role="alert" className="text-meta text-blocker">
          {message}
        </span>
      ) : null}
    </span>
  );
}
