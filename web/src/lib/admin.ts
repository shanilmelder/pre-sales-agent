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

export const ROLES_SHOWN_NOTE = "Roles are shown as of each person's last sign-in.";

export const NO_ROLES_YET = "No roles yet";

export const USERS_FOOTNOTE =
  "First sign-in creates a user with no roles. Roles are managed in Auth0, and Opportunity access is set on each Opportunity.";

// --- Agents (read-only registry) ---------------------------------------------------------------

export type RegistryAgent = components["schemas"]["RegistryAgent"];
export type AgentStatus = components["schemas"]["AgentStatus"];

export const NO_AGENTS = "No agents registered yet.";

export const AGENTS_FOOTNOTE =
  "No agent can send customer communication or approve. Disabled agents receive no tasks.";

const AGENT_STATUS_LABELS: Record<AgentStatus, string> = {
  active: "Enabled",
  disabled: "Disabled",
  eval_only: "Eval only",
};

export function agentStatusLabel(status: AgentStatus): string {
  return AGENT_STATUS_LABELS[status];
}

/** The Agent's tool permissions as one line, "None" when it has none. */
export function toolPermissionsLabel(permissions: readonly string[]): string {
  return permissions.length > 0 ? permissions.join(", ") : "None";
}
