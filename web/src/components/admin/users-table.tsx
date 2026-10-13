"use client";

import { useRef, useState, type KeyboardEvent } from "react";

import { useShell } from "@/components/shell/shell-context";
import type { AdminUser } from "@/lib/admin";
import { roleLabel } from "@/lib/roles";

/** Users with their roles as of their last sign-in, one page at a time. Each row's name is a button. The list is one
 * Tab stop (roving tabindex: the last focused, else the selected, else the first row);
 * j/k (or the arrow keys) move between rows and Enter opens the row's inspector. */
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
  const body = useRef<HTMLTableSectionElement>(null);
  const [focusedId, setFocusedId] = useState<string | null>(null);
  const tabStopId =
    [focusedId, selectedId].find((id) => id !== null && users.some((u) => u.id === id)) ??
    users[0]?.id;

  if (users.length === 0) {
    return <p className="p-gutter text-muted-foreground">No users yet.</p>;
  }

  function onKeyDown(event: KeyboardEvent<HTMLTableSectionElement>) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const down = event.key === "ArrowDown" || (singleKeyShortcuts && event.key === "j");
    const up = event.key === "ArrowUp" || (singleKeyShortcuts && event.key === "k");
    if (!down && !up) return;
    const buttons = Array.from(
      body.current?.querySelectorAll<HTMLButtonElement>("button[data-user-row]") ?? [],
    );
    const index = buttons.findIndex((button) => button === document.activeElement);
    const next = index === -1 ? 0 : Math.min(buttons.length - 1, Math.max(0, index + (down ? 1 : -1)));
    event.preventDefault();
    buttons[next]?.focus();
  }

  return (
    <table className="w-full table-fixed border-collapse text-left">
      <caption className="sr-only">Users and their roles</caption>
      <thead className="text-label text-muted-foreground">
        <tr className="h-row border-b border-border">
          <th scope="col" className="w-1/4 px-gutter font-medium">
            Name
          </th>
          <th scope="col" className="w-1/4 px-2 font-medium">
            Email
          </th>
          <th scope="col" className="px-2 font-medium">
            Roles
          </th>
        </tr>
      </thead>
      <tbody ref={body} onKeyDown={onKeyDown}>
        {users.map((user) => {
          const selected = user.id === selectedId;
          return (
            <tr
              key={user.id}
              className={`h-row border-b border-border ${selected ? "bg-muted" : "hover:bg-muted/60"}`}
            >
              <td className="truncate px-gutter">
                <button
                  type="button"
                  data-user-row=""
                  data-user-id={user.id}
                  tabIndex={user.id === tabStopId ? 0 : -1}
                  aria-current={selected ? "true" : undefined}
                  onFocus={() => setFocusedId(user.id)}
                  // A keyboard-activated click has no pointer clicks (detail 0).
                  onClick={(event) => onOpen(user, event.detail === 0)}
                  className="w-full truncate rounded-sm text-left text-body-strong outline-none focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {user.name}
                </button>
              </td>
              <td className="truncate px-2 text-muted-foreground">{user.email}</td>
              <td className="truncate px-2">
                {user.roles.length > 0 ? (
                  user.roles.map(roleLabel).join(", ")
                ) : (
                  <span className="text-muted-foreground">No roles</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
