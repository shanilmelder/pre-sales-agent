"use client";

import { CircleAlertIcon, CircleCheckIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import {
  FormNotice,
  formFieldClass,
  OriginCard,
  PaneLabel,
  ReasonField,
  reasonValid,
} from "@/components/opportunities/estimate-item-parts";
import { AssumptionLineageSection } from "@/components/opportunities/lineage-section";
import type { EditOutcome } from "@/components/opportunities/estimate-line-edit";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { codePointLength } from "@/lib/opportunities";
import {
  acceptedLabel,
  ASSUMPTION_EDIT_HINT,
  assumptionId,
  assumptionKindLabel,
  CONTINGENCY_HOURS_RULE,
  EDIT_SAVE_FAILED,
  hours,
  NOT_ACCEPTED_YET,
  parseContingencyHours,
  roundHours,
  WORDING_MAX,
  WORDING_RULE,
  type Assumption,
  type AssumptionKind,
} from "@/lib/estimates";
import { cn } from "@/lib/utils";

export const ACCEPT = "Accept";
export const SAVE_CHANGE = "Save change";
export const NO_LINE = "No line";

/** The fields an Assumption edit sends (all of them, as the form holds them). */
export type AssumptionFields = {
  kind: AssumptionKind;
  wording: string;
  amountHours: number | null;
  lineId: string | null;
};

export type SaveAssumption = (
  assumption: Assumption,
  fields: AssumptionFields,
  reason: string,
  rowVersion: number,
) => Promise<EditOutcome>;

/** What the inspector needs to offer **Accept**; left out, there is none. */
export type AssumptionAccepting = { busy: boolean; onAccept: () => void; message?: string | null };

/** What the inspector needs to offer the "Edit Assumption" form; left out, there is none. */
export type AssumptionEditing = {
  /** The version's lines a Contingency may be linked to. */
  lines: readonly { id: string; title: string }[];
  onSave: SaveAssumption;
  onReload?: () => void;
};

const KINDS: readonly { value: AssumptionKind; label: string }[] = [
  { value: "condition", label: "Condition" },
  { value: "contingency", label: "Contingency" },
];

type Base = {
  rowVersion: number;
  kind: AssumptionKind;
  wording: string;
  hours: number | null;
  lineId: string | null;
};

function baseOf(a: Assumption): Base {
  return {
    rowVersion: a.row_version,
    kind: a.kind,
    wording: a.wording,
    hours: a.amount_hours,
    lineId: a.line?.id ?? null,
  };
}

/** The "Edit Assumption" form (Story 8.5): a Condition/Contingency segmented control (a small
 * radio group), the wording, the hours and the line (Contingency only; "No line" is
 * Unallocated) and a required reason. **Save change** stays disabled until something changed,
 * the values are valid and a reason is typed; saving clears the acceptance. A stale save (412)
 * shows the inline alert with Reload. */
export function EditAssumptionForm({
  assumption,
  editing,
}: {
  assumption: Assumption;
  editing: AssumptionEditing;
}) {
  const formId = useId();
  const kindName = useId();
  const wordingId = useId();
  const wordingRuleId = useId();
  const hoursId = useId();
  const hoursRuleId = useId();
  const lineId = useId();
  const hintId = useId();
  const [base, setBase] = useState<Base>(() => baseOf(assumption));
  const [kind, setKind] = useState<AssumptionKind>(assumption.kind);
  const [wording, setWording] = useState(assumption.wording);
  const [hoursText, setHoursText] = useState(
    assumption.amount_hours === null ? "" : hours(assumption.amount_hours),
  );
  const [line, setLine] = useState<string>(assumption.line?.id ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ message: string; reload: boolean } | null>(null);
  const [resync, setResync] = useState(false);
  /** After a Reload: the row version the form was on; its values are taken again once the
   * reloaded item (a newer row version) arrives, even with a reason typed. */
  const [reloadFrom, setReloadFrom] = useState<number | null>(null);

  const contingency = kind === "contingency";
  const trimmed = wording.trim();
  const wordingLength = codePointLength(trimmed);
  const wordingOk = wordingLength > 0 && wordingLength <= WORDING_MAX;
  const parsedHours = contingency ? parseContingencyHours(hoursText) : null;
  const hoursOk = !contingency || parsedHours !== null;
  // The rule shows once something is typed; empty hours only keep Save disabled.
  const showHoursRule = !hoursOk && hoursText.trim() !== "";
  const after: AssumptionFields = {
    kind,
    wording: trimmed,
    amountHours: contingency && parsedHours !== null ? roundHours(parsedHours) : null,
    lineId: contingency && line !== "" ? line : null,
  };
  const changed =
    after.kind !== base.kind ||
    after.wording !== base.wording ||
    (contingency && hoursOk && after.amountHours !== base.hours) ||
    (!contingency && base.hours !== null) ||
    after.lineId !== base.lineId;
  const dirty = changed || reason.trim() !== "" || !hoursOk || !wordingOk;
  const canSave = !saving && changed && wordingOk && hoursOk && reasonValid(reason);

  // A save or a refresh brought new stored values: show them unless the user is mid-edit.
  const reloaded = reloadFrom !== null && assumption.row_version !== reloadFrom;
  if (resync || reloaded || (!dirty && !saving && assumption.row_version !== base.rowVersion)) {
    const next = baseOf(assumption);
    setResync(false);
    setReloadFrom(null);
    setBase(next);
    setKind(next.kind);
    setWording(next.wording);
    setHoursText(next.hours === null ? "" : hours(next.hours));
    setLine(next.lineId ?? "");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setNotice(null);
    let outcome: EditOutcome;
    try {
      outcome = await editing.onSave(assumption, after, reason.trim(), base.rowVersion);
    } catch {
      outcome = { ok: false, message: EDIT_SAVE_FAILED };
    }
    setSaving(false);
    if (outcome.ok) {
      setReason("");
      setResync(true);
    } else {
      setNotice({ message: outcome.message, reload: outcome.reload ?? false });
    }
  }

  return (
    <section
      aria-labelledby={formId}
      data-edit-assumption=""
      className="flex flex-col gap-3 border-t border-border pt-4"
    >
      <h4 id={formId} className="text-eyebrow text-muted-foreground uppercase">
        Edit Assumption
      </h4>
      {notice ? (
        <FormNotice
          notice={notice}
          onReload={
            editing.onReload
              ? () => {
                  setNotice(null);
                  setReloadFrom(base.rowVersion);
                  editing.onReload?.();
                }
              : undefined
          }
        />
      ) : null}
      <form
        aria-label="Edit Assumption"
        aria-busy={saving || undefined}
        onSubmit={(event) => void submit(event)}
        className="flex flex-col gap-3"
      >
        <fieldset className="flex flex-col gap-1">
          <legend className="mb-1 text-label">Kind</legend>
          <div
            data-kind-control=""
            className="inline-flex w-fit rounded-md border border-border-strong bg-surface-alt p-0.5"
          >
            {KINDS.map((option) => (
              <label
                key={option.value}
                className={cn(
                  "cursor-pointer rounded-[5px] px-3 py-1 text-label has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary",
                  kind === option.value
                    ? "bg-surface text-foreground shadow-sm"
                    : "text-muted-foreground",
                )}
              >
                <input
                  type="radio"
                  name={kindName}
                  value={option.value}
                  checked={kind === option.value}
                  disabled={saving}
                  onChange={() => setKind(option.value)}
                  className="sr-only"
                />
                {option.label}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex flex-col gap-1">
          <label htmlFor={wordingId} className="text-label">
            Wording
          </label>
          <Textarea
            id={wordingId}
            value={wording}
            rows={3}
            maxLength={WORDING_MAX * 2}
            disabled={saving}
            aria-invalid={wordingOk ? undefined : true}
            aria-describedby={wordingOk ? undefined : wordingRuleId}
            onChange={(event) => setWording(event.target.value)}
          />
          {wordingOk ? null : (
            <p id={wordingRuleId} className="text-meta text-destructive">
              {WORDING_RULE}
            </p>
          )}
        </div>
        {contingency ? (
          <div className="flex flex-wrap gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor={hoursId} className="text-label">
                Hours
              </label>
              <input
                id={hoursId}
                type="text"
                inputMode="decimal"
                value={hoursText}
                disabled={saving}
                aria-invalid={showHoursRule ? true : undefined}
                aria-describedby={showHoursRule ? hoursRuleId : undefined}
                onChange={(event) => setHoursText(event.target.value)}
                className={cn(formFieldClass, "w-28 text-right")}
              />
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
              <label htmlFor={lineId} className="text-label">
                Line
              </label>
              <select
                id={lineId}
                value={line}
                disabled={saving}
                onChange={(event) => setLine(event.target.value)}
                className={cn(formFieldClass, "w-full min-w-0")}
              >
                <option value="">{NO_LINE}</option>
                {editing.lines.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.title}
                  </option>
                ))}
              </select>
            </div>
            {showHoursRule ? (
              <p id={hoursRuleId} className="w-full text-meta text-destructive">
                {CONTINGENCY_HOURS_RULE}
              </p>
            ) : null}
          </div>
        ) : null}
        <ReasonField value={reason} onChange={setReason} disabled={saving} />
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!canSave} aria-describedby={hintId}>
            {SAVE_CHANGE}
          </Button>
          <p id={hintId} className="text-meta text-muted-foreground">
            {ASSUMPTION_EDIT_HINT}
          </p>
        </div>
      </form>
    </section>
  );
}

/** The selected Assumption in the right pane (Story 8.5): "{kind} · A{n}" over its wording,
 * its hours and line, its origin card (the Gap opens with its own inspector), "Accepted by
 * {name} · {date}" or "Not accepted" with **Accept**, and the "Edit Assumption" form. Without
 * `accepting` and `editing` (a version that isn't the draft, or a sales representative) it is
 * read-only. Story 9.9: with `opportunityId`, it ends with the **Lineage** chain. */
export function AssumptionInspector({
  assumption,
  opportunityId,
  focusRequest = 0,
  accepting,
  editing,
  onOpenGap,
}: {
  assumption: Assumption;
  /** For the lineage; without it the section is left out. */
  opportunityId?: string;
  focusRequest?: number;
  accepting?: AssumptionAccepting;
  editing?: AssumptionEditing;
  onOpenGap?: () => void;
}) {
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const accepted = assumption.accepted_at !== null;

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section
      aria-labelledby={headingId}
      data-assumption-inspector=""
      className="flex flex-col gap-5 p-gutter"
    >
      <div className="flex flex-col gap-1">
        <p className="text-meta text-muted-foreground">
          {`${assumptionKindLabel(assumption.kind)} · ${assumptionId(assumption)}`}
        </p>
        <h3
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-section break-words outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          {assumption.wording}
        </h3>
      </div>

      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 text-body">
        <dt className="text-muted-foreground">Hours</dt>
        <dd className="text-numeric">
          {assumption.amount_hours === null ? "–" : `${hours(assumption.amount_hours)} h`}
        </dd>
        <dt className="text-muted-foreground">Line</dt>
        <dd className="truncate">
          {assumption.line
            ? assumption.line.title
            : assumption.kind === "contingency"
              ? "Unallocated"
              : "–"}
        </dd>
      </dl>

      <div className="flex flex-col gap-1.5">
        <PaneLabel>Origin</PaneLabel>
        <OriginCard item={assumption} onOpenGap={onOpenGap} />
      </div>

      <div className="flex flex-col gap-2">
        <PaneLabel>Acceptance</PaneLabel>
        {accepted ? (
          <p className="flex items-center gap-1 text-resolved">
            <CircleCheckIcon aria-hidden="true" className="size-3.5 shrink-0" />
            <span className="text-label">{acceptedLabel(assumption)}</span>
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <p className="flex items-center gap-1 text-blocker">
              <CircleAlertIcon aria-hidden="true" className="size-3.5 shrink-0" />
              <span className="text-label">{NOT_ACCEPTED_YET}</span>
            </p>
            {accepting ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={accepting.busy}
                onClick={accepting.onAccept}
              >
                {ACCEPT}
              </Button>
            ) : null}
          </div>
        )}
        {accepting?.message ? (
          <p className="text-meta text-destructive">{accepting.message}</p>
        ) : null}
      </div>

      {editing ? (
        <EditAssumptionForm
          key={assumption.id}
          assumption={assumption}
          editing={editing}
        />
      ) : null}

      {opportunityId ? (
        <AssumptionLineageSection opportunityId={opportunityId} assumptionId={assumption.id} />
      ) : null}
    </section>
  );
}
