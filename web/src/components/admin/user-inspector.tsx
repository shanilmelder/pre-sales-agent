"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";

import { changeRole, loadUser, type AdminUser } from "@/app/admin/users/actions";
import { useAnnounce } from "@/components/shell/live-region";
import type { Role } from "@/lib/navigation";
import { ROLES, roleLabel } from "@/lib/roles";

type Notice =
  | { kind: "stale"; changedBy: string | null }
  | { kind: "conflict"; detail: string }
  | { kind: "error"; message: string };

const SAVE_FAILED = "The change could not be saved. Try again.";
const NO_ACCESS = "You don't have access to change roles.";
const GONE = "This user no longer exists.";
const RELOAD_FAILED = "The user could not be reloaded. Try again.";

export function staleMessage(changedBy: string | null): string {
  return `Changed by ${changedBy ?? "another administrator"} since you opened it.`;
}

function RoleSwitch({
  role,
  label,
  checked,
  disabled,
  onChange,
}: {
  role: Role;
  label: string;
  checked: boolean;
  disabled: boolean;
  onChange: (role: Role, assigned: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex h-row items-center justify-between gap-4">
      <label htmlFor={id} className="text-body">
        {label}
      </label>
      {/* The transparent input covers the track, so clicking the track toggles it. */}
      <span className="relative flex">
        <input
          id={id}
          type="checkbox"
          role="switch"
          checked={checked}
          // aria-disabled, not disabled: a disabled control drops keyboard focus to <body>.
          aria-disabled={disabled || undefined}
          onChange={(event) => {
            if (!disabled) onChange(role, event.target.checked);
          }}
          className="peer absolute inset-0 z-10 m-0 cursor-pointer opacity-0 aria-disabled:cursor-not-allowed"
        />
        <span
          aria-hidden="true"
          className="relative h-5 w-9 rounded-full bg-muted-foreground transition-colors peer-checked:bg-primary peer-focus-visible:ring-3 peer-focus-visible:ring-primary peer-aria-disabled:opacity-60 after:absolute after:top-0.5 after:left-0.5 after:size-4 after:rounded-full after:bg-background after:transition-transform peer-checked:after:translate-x-4"
        />
      </span>
    </div>
  );
}

/** The selected user's roles: nine switches that save on change with `If-Match`. A 412
 * shows who changed the user with a Reload button and overwrites nothing; a 409 shows the
 * API's detail. Changes are announced through the shell's live region. */
export function UserInspector({
  user,
  onChange,
  focusRequest = 0,
}: {
  user: AdminUser;
  /** Called with the user as stored after a save or a reload. */
  onChange: (user: AdminUser) => void;
  /** Bump to move keyboard focus to the inspector's heading (0: leave focus alone). */
  focusRequest?: number;
}) {
  const announce = useAnnounce();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pending, startTransition] = useTransition();
  const headingId = useId();
  const stale = notice?.kind === "stale";
  const locked = pending || stale;
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  // On 412 the switches are locked: take focus to the one thing that can be done next.
  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  function fail(next: Notice, spoken: string) {
    setNotice(next);
    announce(spoken);
  }

  function toggle(role: Role, assigned: boolean) {
    if (locked) return;
    setNotice(null);
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof changeRole>>;
      try {
        result = await changeRole({ userId: user.id, role, assigned, rowVersion: user.row_version });
      } catch {
        result = { kind: "error" };
      }
      switch (result.kind) {
        case "ok":
          onChange(result.user);
          announce(`${roleLabel(role)} ${assigned ? "assigned to" : "removed from"} ${result.user.name}`);
          return;
        case "stale": {
          const message = staleMessage(result.changedBy);
          fail({ kind: "stale", changedBy: result.changedBy }, message);
          return;
        }
        case "conflict":
          fail({ kind: "conflict", detail: result.detail }, result.detail);
          return;
        case "forbidden":
          fail({ kind: "error", message: NO_ACCESS }, NO_ACCESS);
          return;
        case "not-found":
          fail({ kind: "error", message: GONE }, GONE);
          return;
        default:
          fail({ kind: "error", message: SAVE_FAILED }, SAVE_FAILED);
      }
    });
  }

  function reload() {
    if (pending) return;
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof loadUser>>;
      try {
        result = await loadUser(user.id);
      } catch {
        result = { kind: "error" };
      }
      // The Reload button goes away unless the reload failed: keep focus in the inspector.
      if (result.kind === "ok" || result.kind === "not-found" || result.kind === "forbidden") {
        headingRef.current?.focus();
      }
      if (result.kind === "ok") {
        setNotice(null);
        onChange(result.user);
        announce(`Reloaded ${result.user.name}`);
      } else if (result.kind === "not-found") {
        fail({ kind: "error", message: GONE }, GONE);
      } else if (result.kind === "forbidden") {
        fail({ kind: "error", message: NO_ACCESS }, NO_ACCESS);
      } else {
        // Keep the stale notice (and its Reload button); nothing was overwritten.
        announce(RELOAD_FAILED);
      }
    });
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-section outline-none">
          {user.name}
        </h3>
        <p className="text-meta text-muted-foreground">{user.email}</p>
      </div>
      <fieldset className="flex flex-col" aria-busy={pending}>
        <legend className="mb-1 text-label text-muted-foreground">Roles</legend>
        {ROLES.map(({ value, label }) => (
          <RoleSwitch
            key={value}
            role={value}
            label={label}
            checked={user.roles.includes(value)}
            disabled={locked}
            onChange={toggle}
          />
        ))}
      </fieldset>
      {/* Screen readers hear these through the shell's single live region. */}
      {notice?.kind === "stale" ? (
        <div className="flex items-center justify-between gap-2 rounded-md border border-border p-2">
          <p className="text-meta">{staleMessage(notice.changedBy)}</p>
          <button
            type="button"
            ref={reloadRef}
            onClick={reload}
            aria-disabled={pending || undefined}
            className="h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
          >
            Reload
          </button>
        </div>
      ) : null}
      {notice?.kind === "conflict" ? <p className="text-meta text-destructive">{notice.detail}</p> : null}
      {notice?.kind === "error" ? <p className="text-meta text-destructive">{notice.message}</p> : null}
    </section>
  );
}
