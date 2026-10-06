"use client";

import { ExternalLinkIcon } from "lucide-react";
import { useEffect, useId, useRef } from "react";

import { ROLES_AS_OF_NOTE, type AdminUser } from "@/lib/admin";
import { roleLabel } from "@/lib/roles";

/** The selected user's roles, read-only: roles are edited in the Auth0 dashboard, which
 * the inspector links to. The roles shown are as of the user's last sign-in. */
export function UserInspector({
  user,
  manageRolesUrl,
  focusRequest = 0,
}: {
  user: AdminUser;
  /** The Auth0 dashboard page where roles are managed. */
  manageRolesUrl: string;
  /** Bump to move keyboard focus to the inspector's heading (0: leave focus alone). */
  focusRequest?: number;
}) {
  const headingId = useId();
  const rolesId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    if (focusRequest > 0) headingRef.current?.focus();
  }, [focusRequest]);

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4 p-gutter">
      <div className="flex flex-col gap-1">
        <h3 id={headingId} ref={headingRef} tabIndex={-1} className="text-section outline-none">
          {user.name}
        </h3>
        <p className="text-meta text-muted-foreground">{user.email}</p>
      </div>
      <div className="flex flex-col gap-1">
        <h4 id={rolesId} className="text-label text-muted-foreground">
          Roles as of last sign-in
        </h4>
        {user.roles.length > 0 ? (
          <ul aria-labelledby={rolesId} className="flex flex-col">
            {user.roles.map((role) => (
              <li key={role} className="flex h-row items-center text-body">
                {roleLabel(role)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-body text-muted-foreground">No roles</p>
        )}
      </div>
      <p className="text-meta text-muted-foreground">{ROLES_AS_OF_NOTE}</p>
      <a
        href={manageRolesUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex h-7 w-fit items-center gap-1.5 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
      >
        Manage roles in Auth0
        <ExternalLinkIcon className="size-3.5" aria-hidden="true" />
        <span className="sr-only">(opens in a new tab)</span>
      </a>
    </section>
  );
}
