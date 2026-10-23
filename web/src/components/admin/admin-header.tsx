import { ExternalLinkIcon } from "lucide-react";

import { PAGE_SUBTITLES, PageHeader } from "@/components/shell/page-header";
import { buttonVariants } from "@/components/ui/button";
import { auth0UsersUrl } from "@/lib/admin";

/** The header band of every Admin section: "Admin", its subtitle and "Invite user", which
 * opens the Auth0 user list in a new tab (users are invited there, not here). */
export function AdminHeader() {
  return (
    <PageHeader
      title="Admin"
      subtitle={PAGE_SUBTITLES.admin}
      action={
        <a
          href={auth0UsersUrl(process.env.AUTH0_DOMAIN)}
          target="_blank"
          rel="noreferrer"
          className={`${buttonVariants({ variant: "default" })} text-body-strong`}
        >
          Invite user
          <span className="sr-only">, opens Auth0 in a new tab</span>
          <ExternalLinkIcon data-icon="inline-end" aria-hidden="true" />
        </a>
      }
    />
  );
}
