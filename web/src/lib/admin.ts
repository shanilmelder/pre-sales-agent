// Users & roles (read-only since Story 1.9): roles are managed in Auth0. Safe on server and
// client.
import type { components } from "@/lib/api/client";

export type AdminUser = components["schemas"]["AdminUser"];

const AUTH0_DASHBOARD = "https://manage.auth0.com/";

/** The Auth0 dashboard's user list for the tenant behind `domain` (e.g.
 * `psa.eu.auth0.com` -> `.../dashboard/eu/psa/users`). A custom or missing domain can't be
 * mapped to a tenant, so it links to the dashboard home. */
export function auth0UsersUrl(domain: string | undefined): string {
  const host = (domain ?? "")
    .trim()
    .replace(/^https?:\/\//, "")
    .replace(/\/.*$/, "")
    .toLowerCase();
  const match = /^([a-z0-9-]+)(?:\.([a-z0-9]+))?\.auth0\.com$/.exec(host);
  if (!match) return AUTH0_DASHBOARD;
  const [, tenant, region = "us"] = match;
  return `${AUTH0_DASHBOARD}dashboard/${region}/${tenant}/users`;
}

export const ROLES_AS_OF_NOTE =
  "Roles are managed in Auth0 and shown as of each person's last sign-in.";
