"use client";

import { useEffect, useRef, useState } from "react";

import { UserInspector } from "@/components/admin/user-inspector";
import { UsersTable } from "@/components/admin/users-table";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import type { AdminUser } from "@/lib/admin";

/** Users & roles (read-only): the list in the main pane and the selected user's roles in
 * the right pane. */
export function UsersAdmin({
  initialUsers,
  manageRolesUrl,
}: {
  initialUsers: readonly AdminUser[];
  /** The Auth0 dashboard page where roles are managed. */
  manageRolesUrl: string;
}) {
  const { rightPaneOpen, setRightPaneOpen } = useShell();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);

  const selected = initialUsers.find((user) => user.id === selectedId) ?? null;

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

  return (
    <>
      <UsersTable users={initialUsers} selectedId={selectedId} onOpen={open} />
      {selected ? (
        <RightPaneContent>
          <UserInspector
            key={selected.id}
            user={selected}
            manageRolesUrl={manageRolesUrl}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </>
  );
}
