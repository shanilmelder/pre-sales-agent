"use client";

import { useEffect, useRef, useState } from "react";

import type { AdminUser } from "@/app/admin/users/actions";
import { UserInspector } from "@/components/admin/user-inspector";
import { UsersTable } from "@/components/admin/users-table";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";

/** Users & roles: the list in the main pane and the selected user's inspector in the right
 * pane. Saved changes update the list row in place; new server data replaces the rows. */
export function UsersAdmin({ initialUsers }: { initialUsers: readonly AdminUser[] }) {
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [users, setUsers] = useState<readonly AdminUser[]>(initialUsers);
  const [syncedFrom, setSyncedFrom] = useState(initialUsers);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);

  // A server refresh (e.g. router.refresh or revisiting the page) brings new rows.
  if (initialUsers !== syncedFrom) {
    setSyncedFrom(initialUsers);
    setUsers(initialUsers);
  }

  const selected = users.find((user) => user.id === selectedId) ?? null;

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-user-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function open(user: AdminUser, viaKeyboard: boolean) {
    setSelectedId(user.id);
    returnFocusTo.current = viaKeyboard ? user.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function replace(next: AdminUser) {
    setUsers((current) => current.map((user) => (user.id === next.id ? next : user)));
  }

  return (
    <>
      <UsersTable users={users} selectedId={selectedId} onOpen={open} />
      {selected ? (
        <RightPaneContent>
          <UserInspector
            key={selected.id}
            user={selected}
            onChange={replace}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </>
  );
}
