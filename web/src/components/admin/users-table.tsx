"use client";

import { useRef, useState, type KeyboardEvent } from "react";

import { BODY_ROW, CardTable } from "@/components/admin/card-table";
import { useShell } from "@/components/shell/shell-context";
import { Card } from "@/components/ui/card";
import { Chip } from "@/components/ui/chip";
import { NO_ROLES_YET, type AdminUser } from "@/lib/admin";
import { actorInitials } from "@/lib/overview";
import { roleLabel } from "@/lib/roles";

const GRID = "grid-cols-[minmax(0,1fr)_190px]";

/** Users with their roles as of their last sign-in, one page at a time, as a card table.
 * Each row's name is a button whose hit area covers the row. The list is one Tab stop
 * (roving tabindex: the last focused, else the selected, else the first row); j/k (or the
 * arrow keys) move between rows and Enter opens the row's inspector. */
export function UsersTable({
  users,
  selectedId,
  onOpen,
}: {
  users: readonly AdminUser[];
  selectedId: string | null;
  /** `viaKeyboard` is true when the row was opened with Enter or Space, not a pointer. */
  onOpen: (user: AdminUser, viaKeyboard: boolean) => void;
}) {
  const { singleKeyShortcuts } = useShell();
  const root = useRef<HTMLDivElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && users.some((u) => u.id === id)) ??
    users[0]?.id;

  if (users.length === 0) {
    return (
      <Card className="overflow-hidden px-5 py-4">
        <p className="text-text-secondary">No users yet.</p>
      </Card>
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      root.current?.querySelectorAll<HTMLButtonElement>("button[data-user-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === document.activeElement);
    const next = index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <Card ref={root} onKeyDown={onKeyDown} className="overflow-hidden">
      <CardTable label="Users and their roles" grid={GRID} columns={["User", "Role"]}>
        {users.map((user) => {
          const selected = user.id === selectedId;
          return (
            <div
              key={user.id}
              role="row"
              className={`relative py-[18px] ${BODY_ROW} ${GRID} ${
                selected ? "bg-primary-tint" : "hover:bg-muted/60"
              }`}
            >
              <div role="rowheader" className="flex min-w-0 items-center gap-3">
                <span
                  aria-hidden="true"
                  className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary-tint text-label text-primary-text"
                >
                  {actorInitials(user.name)}
                </span>
                <div className="min-w-0">
                  <button
                    type="button"
                    data-user-row=""
                    data-user-id={user.id}
                    tabIndex={user.id === tabStopId ? 0 : -1}
                    aria-current={selected ? "true" : undefined}
                    onFocus={() => setFocusedId(user.id)}
                    // A keyboard-activated click has no pointer clicks (detail 0).
                    onClick={(event) => onOpen(user, event.detail === 0)}
                    className="block max-w-full truncate text-left text-body-strong outline-none after:absolute after:inset-0 after:content-[''] focus-visible:after:ring-2 focus-visible:after:ring-primary focus-visible:after:ring-inset"
                  >
                    {user.name}
                  </button>
                  <p className="truncate text-meta text-text-secondary">{user.email}</p>
                </div>
              </div>
              <div role="cell" className="flex min-w-0 flex-wrap items-center gap-1.5">
                {user.roles.length > 0 ? (
                  user.roles.map((role) => (
                    <Chip key={role} className="text-foreground">
                      {roleLabel(role)}
                    </Chip>
                  ))
                ) : (
                  <span className="text-meta text-text-secondary">{NO_ROLES_YET}</span>
                )}
              </div>
            </div>
          );
        })}
      </CardTable>
    </Card>
  );
}
