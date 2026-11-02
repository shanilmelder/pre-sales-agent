"use client";

import { ArchiveIcon, CircleAlertIcon, CircleCheckIcon, Clock3Icon } from "lucide-react";
import { useEffect, useRef, useState, useTransition } from "react";

import {
  retestProfile,
  retireProfile,
  type ProfileResult,
} from "@/app/admin/model-profiles/actions";
import { BODY_ROW, CardTable } from "@/components/admin/card-table";
import { useAnnounce } from "@/components/shell/live-region";
import { Pill } from "@/components/ui/pill";
import {
  canRetest,
  canRetire,
  NO_PROFILES,
  OFF_HOST_NOTE,
  samplingLabel,
  stateLabel,
  stateTone,
  testResult,
  type ModelProfile,
  type ProfileState,
} from "@/lib/model-profiles";

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";
const GRID = "grid-cols-[minmax(0,1.2fr)_minmax(0,1.2fr)_140px_minmax(0,1fr)_170px]";
const COLUMNS = ["Profile", "Model", "State", "Test result", "Actions"] as const;
const ICONS: Record<ProfileState, typeof ArchiveIcon> = {
  untested: Clock3Icon,
  verified: CircleCheckIcon,
  failed: CircleAlertIcon,
  retired: ArchiveIcon,
};

/** The profile's state: always an icon and a label, never colour alone. */
export function ProfileStatePill({ profile }: { profile: ModelProfile }) {
  const Icon = ICONS[profile.state];
  return (
    <Pill
      data-profile-state={profile.state}
      tone={stateTone(profile.state)}
      icon={<Icon />}
      className="w-fit shrink-0"
    >
      {stateLabel(profile.state)}
    </Pill>
  );
}

function failureMessage(result: Exclude<ProfileResult, { kind: "ok" }>): string {
  switch (result.kind) {
    case "conflict":
    case "invalid":
      return result.detail;
    case "forbidden":
      return "You don't have access to change model profiles.";
    case "not-found":
      return "This profile no longer exists. Reload the page.";
    default:
      return "That didn't work. Try again.";
  }
}

function ProfileRow({
  profile,
  pollStopped,
  onChange,
}: {
  profile: ModelProfile;
  pollStopped: boolean;
  onChange: (profile: ModelProfile) => void;
}) {
  const announce = useAnnounce();
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const result = testResult(profile);
  const rowRef = useRef<HTMLDivElement>(null);
  const retireRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const wasConfirming = useRef(false);

  // Retire and Confirm swap places, so focus follows; a retired row has neither.
  useEffect(() => {
    if (confirming) confirmRef.current?.focus();
    else if (wasConfirming.current) (retireRef.current ?? rowRef.current)?.focus();
    wasConfirming.current = confirming;
  }, [confirming]);

  function run(action: () => Promise<ProfileResult>, done: string) {
    if (pending) return;
    setMessage(null);
    startTransition(async () => {
      let outcome: ProfileResult;
      try {
        outcome = await action();
      } catch {
        outcome = { kind: "error" };
      }
      setConfirming(false);
      if (outcome.kind === "ok") {
        onChange(outcome.profile);
        if (!confirming) rowRef.current?.focus(); // "Test again" just went away
        announce(done);
        return;
      }
      const text = failureMessage(outcome);
      setMessage(text);
      announce(text);
    });
  }

  return (
    <div
      ref={rowRef}
      role="row"
      tabIndex={-1}
      data-profile-id={profile.id}
      className={`${BODY_ROW} ${GRID} py-2.5 outline-none focus-visible:ring-2 focus-visible:ring-primary`}
    >
      <div role="cell" className="min-w-0">
        <p className="truncate font-mono text-body">{profile.name}</p>
        <p className="text-meta text-text-secondary">{OFF_HOST_NOTE}</p>
      </div>
      <div role="cell" className="min-w-0">
        <p className="truncate font-mono text-body">{profile.model}</p>
        <p className="text-meta text-text-secondary">
          {profile.provider} · {profile.num_ctx.toLocaleString("en-GB")} context ·{" "}
          {samplingLabel(profile)}
        </p>
      </div>
      <div role="cell">
        <ProfileStatePill profile={profile} />
      </div>
      <div role="cell" className="min-w-0 text-meta text-text-secondary">
        {result ?? "No result yet"}
      </div>
      <div role="cell" className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap gap-1">
          {canRetest(profile, pollStopped) ? (
            <button
              type="button"
              aria-disabled={pending || undefined}
              aria-label={`Test ${profile.name} again`}
              onClick={() =>
                run(() => retestProfile(profile.id), `${profile.name} queued for testing`)
              }
              className={buttonClass}
            >
              Test again
            </button>
          ) : null}
          {canRetire(profile) && !confirming ? (
            <button
              ref={retireRef}
              type="button"
              aria-label={`Retire ${profile.name}`}
              onClick={() => setConfirming(true)}
              className={buttonClass}
            >
              Retire
            </button>
          ) : null}
          {confirming ? (
            <>
              <button
                ref={confirmRef}
                type="button"
                aria-disabled={pending || undefined}
                aria-label={`Confirm retiring ${profile.name}`}
                onClick={() => run(() => retireProfile(profile.id), `${profile.name} retired`)}
                className={buttonClass}
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className={buttonClass}
              >
                Keep
              </button>
            </>
          ) : null}
        </div>
        {message ? <p className="text-meta text-destructive">{message}</p> : null}
      </div>
    </div>
  );
}

/** Every chat profile, newest first: name, model, state and latest test result. Every row
 * says the profile sends prompt text off the host. */
export function ModelProfileTable({
  profiles,
  pollStopped,
  onChange,
}: {
  profiles: readonly ModelProfile[];
  pollStopped: boolean;
  onChange: (profile: ModelProfile) => void;
}) {
  if (profiles.length === 0) {
    return <p className="border-t border-border px-5 py-4 text-text-secondary">{NO_PROFILES}</p>;
  }
  return (
    <CardTable label="Chat model profiles" grid={GRID} columns={COLUMNS}>
      {profiles.map((profile) => (
        <ProfileRow
          key={profile.id}
          profile={profile}
          pollStopped={pollStopped}
          onChange={onChange}
        />
      ))}
    </CardTable>
  );
}
