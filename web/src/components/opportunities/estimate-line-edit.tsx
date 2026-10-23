"use client";

import { CircleAlertIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { InlineAlert } from "@/components/ui/inline-alert";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { codePointLength } from "@/lib/opportunities";
import {
  EDIT_SAVE_FAILED,
  EFFORT_RULE,
  hours,
  keepReason,
  mixSum,
  parseEffort,
  readKeptReason,
  REASON_LABEL,
  REASON_MAX,
  ROLES,
  roundHours,
  type EstimateLine,
  type RoleMix,
} from "@/lib/estimates";
import { cn } from "@/lib/utils";

/** A change to a line, before its reason is given. */
export type LineChange = { effortHours?: number; roleMix?: RoleMix };

/** What saving a change came to: on failure, the sentence to show, and whether a Reload is
 * offered (stale or replaced version). */
export type EditOutcome = { ok: true } | { ok: false; message: string; reload?: boolean };

export type SaveLine = (
  line: EstimateLine,
  change: LineChange,
  reason: string,
  rowVersion: number,
) => Promise<EditOutcome>;

/** The note beside Save. */
export const EDIT_TRACED = "Each edit needs a reason and is traced.";

/** The line as it was when editing started: its `row_version` goes in `If-Match`, so a
 * colleague's save in between is a 412, never silently overwritten. */
type Base = { rowVersion: number; effort: number; mix: RoleMix };

function baseOf(line: EstimateLine): Base {
  return { rowVersion: line.row_version, effort: line.effort_hours, mix: line.role_mix };
}

function mixTexts(mix: RoleMix): Record<string, string> {
  return Object.fromEntries(ROLES.map((role) => [role.value, String(mix[role.value])]));
}

/** The inspector's "Edit line" form (Story 8.2, moved out of the grid): Effort (h), one
 * whole-number share per role (adding up to 100), and a required reason prefilled with the
 * user's last reason in this version. Save sends only the changed fields with the
 * `row_version` seen when editing started, and stays disabled until something changed and a
 * reason is given. A failure shows as an inline alert here (Reload for a stale line or a
 * replaced version); a success leaves the form on the saved values. */
export function EditLineForm({
  line,
  versionId,
  reasonKey,
  onSave,
  onReload,
  onDirtyChange,
  focusRequest = 0,
}: {
  line: EstimateLine;
  /** The version the line belongs to: the kept reason is per version. */
  versionId: string;
  /** Where the last reason is kept in the browser (one key per Opportunity). */
  reasonKey: string;
  onSave: SaveLine;
  onReload?: () => void;
  /** Told whether the form holds unsaved changes. */
  onDirtyChange?: (dirty: boolean) => void;
  /** Bumped to move focus to the Effort field. */
  focusRequest?: number;
}) {
  const formId = useId();
  const effortId = useId();
  const effortRuleId = useId();
  const sumId = useId();
  const ruleId = useId();
  const reasonId = useId();
  const countId = useId();
  const noteId = useId();
  const effortRef = useRef<HTMLInputElement>(null);

  const [base, setBase] = useState<Base>(() => baseOf(line));
  const [effortText, setEffortText] = useState(() => hours(line.effort_hours));
  const [mixValues, setMixValues] = useState(() => mixTexts(line.role_mix));
  const [reason, setReason] = useState(() => readKeptReason(reasonKey, versionId));
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ message: string; reload: boolean } | null>(null);
  /** Bumped when a save settles: focus goes back to Effort (Save was disabled meanwhile). */
  const [refocus, setRefocus] = useState(0);
  /** Take the line's stored values again on the next render (after a save or a Reload). */
  const [resync, setResync] = useState(false);

  const effort = parseEffort(effortText);
  const effortChanged = effort !== null && roundHours(effort) !== roundHours(base.effort);
  const parsedMix = ROLES.map((role) => {
    const text = mixValues[role.value].trim();
    return /^\d{1,3}$/.test(text) ? Number(text) : null;
  });
  const fieldValid = parsedMix.map((v) => v !== null && v <= 100);
  const whole = fieldValid.every(Boolean);
  const mix = whole
    ? (Object.fromEntries(ROLES.map((role, i) => [role.value, parsedMix[i]])) as RoleMix)
    : null;
  const sum = parsedMix.reduce<number>((total, v) => total + (v ?? 0), 0);
  const mixValid = mix !== null && mixSum(mix) === 100;
  const mixChanged =
    mix !== null && ROLES.some((role) => mix[role.value] !== base.mix[role.value]);
  const dirty = effortChanged || mixChanged || effort === null || !whole;

  // A save or a refresh brought new stored values: show them unless the user is mid-edit.
  if (resync || (!dirty && !saving && line.row_version !== base.rowVersion)) {
    setResync(false);
    setBase(baseOf(line));
    setEffortText(hours(line.effort_hours));
    setMixValues(mixTexts(line.role_mix));
  }

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);

  // Unmounted (another line or a Gap opened): no unsaved change is left open.
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  useEffect(() => {
    if (focusRequest > 0) effortRef.current?.focus();
  }, [focusRequest]);

  useEffect(() => {
    if (refocus > 0 && !saving) effortRef.current?.focus();
  }, [refocus, saving]);

  const length = codePointLength(reason.trim());
  const reasonValid = length > 0 && length <= REASON_MAX;
  const canSave =
    !saving &&
    (effortChanged || mixChanged) &&
    effort !== null &&
    mixValid &&
    reasonValid;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSave) return;
    const change: LineChange = {
      ...(effortChanged && effort !== null ? { effortHours: effort } : {}),
      ...(mixChanged && mix ? { roleMix: mix } : {}),
    };
    const given = reason.trim();
    setSaving(true);
    setNotice(null);
    let outcome: EditOutcome;
    try {
      outcome = await onSave(line, change, given, base.rowVersion);
    } catch {
      outcome = { ok: false, message: EDIT_SAVE_FAILED };
    }
    setSaving(false);
    setRefocus((n) => n + 1);
    if (outcome.ok) {
      keepReason(reasonKey, versionId, given);
      setReason(given);
      setResync(true);
    } else {
      setNotice({ message: outcome.message, reload: outcome.reload ?? false });
    }
  }

  return (
    <section
      aria-labelledby={formId}
      data-edit-line=""
      className="flex flex-col gap-3 border-t border-border pt-4"
    >
      <h4 id={formId} className="text-eyebrow text-muted-foreground uppercase">
        Edit line
      </h4>
      {notice ? (
        notice.reload && onReload ? (
          <InlineAlert
            lead={notice.message}
            onReload={() => {
              setNotice(null);
              setResync(true);
              onReload();
            }}
          />
        ) : (
          <div
            role="alert"
            data-slot="inline-alert"
            className="flex max-w-md items-start gap-2 rounded-lg border border-blocker bg-blocker-tint p-3"
          >
            <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-3 shrink-0 text-blocker" />
            <p className="text-meta text-foreground">{notice.message}</p>
          </div>
        )
      ) : null}
      <form
        aria-busy={saving || undefined}
        onSubmit={(event) => void submit(event)}
        className="flex flex-col gap-3"
      >
        <div className="flex flex-col gap-1">
          <label htmlFor={effortId} className="text-label">
            Effort (h)
          </label>
          <Input
            id={effortId}
            ref={effortRef}
            type="text"
            inputMode="decimal"
            value={effortText}
            disabled={saving}
            aria-invalid={effort === null ? true : undefined}
            aria-describedby={effort === null ? effortRuleId : undefined}
            onChange={(event) => setEffortText(event.target.value)}
            className="h-8 w-28 text-right"
          />
          {effort === null ? (
            <p id={effortRuleId} className="text-meta text-destructive">
              {EFFORT_RULE}
            </p>
          ) : null}
        </div>
        <fieldset className="flex flex-col gap-1">
          <legend className="text-label">Role mix</legend>
          <div className="flex flex-wrap items-end gap-2">
            {ROLES.map((role, i) => (
              <label key={role.value} className="flex flex-col gap-1 text-meta">
                <span>{`${role.label} (%)`}</span>
                <Input
                  type="text"
                  inputMode="numeric"
                  value={mixValues[role.value]}
                  disabled={saving}
                  aria-invalid={fieldValid[i] ? undefined : true}
                  aria-describedby={fieldValid[i] ? sumId : `${sumId} ${ruleId}`}
                  onChange={(event) =>
                    setMixValues((current) => ({ ...current, [role.value]: event.target.value }))
                  }
                  className="h-8 w-16 text-right"
                />
              </label>
            ))}
            <span
              id={sumId}
              aria-live="polite"
              data-valid={mixValid}
              className={cn(
                "pb-2 [font-variant-numeric:tabular-nums]",
                mixValid ? "text-muted-foreground" : "text-destructive",
              )}
            >
              <span className="text-label">{`= ${sum}%`}</span>
            </span>
          </div>
          {whole ? null : (
            <p id={ruleId} className="text-meta text-destructive">
              Whole numbers 0–100
            </p>
          )}
        </fieldset>
        <div className="flex flex-col gap-1">
          <label htmlFor={reasonId} className="text-label">
            {REASON_LABEL}
          </label>
          <Textarea
            id={reasonId}
            value={reason}
            required
            rows={2}
            maxLength={REASON_MAX * 2}
            disabled={saving}
            aria-describedby={countId}
            onChange={(event) => setReason(event.target.value)}
          />
          <span
            id={countId}
            data-over={length > REASON_MAX || undefined}
            className={cn(
              "[font-variant-numeric:tabular-nums]",
              length > REASON_MAX ? "text-destructive" : "text-muted-foreground",
            )}
          >
            <span className="text-meta">
              {length > REASON_MAX
                ? `${length}/${REASON_MAX}: shorten the reason to save`
                : `${length}/${REASON_MAX}`}
            </span>
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!canSave} aria-describedby={noteId}>
            Save
          </Button>
          <p id={noteId} className="text-meta text-muted-foreground">
            {EDIT_TRACED}
          </p>
        </div>
      </form>
    </section>
  );
}
