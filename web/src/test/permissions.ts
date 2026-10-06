// The Auth0 role-to-permission seed from the README ("Auth0 setup"): what a token's
// `permissions` claim (and so `/me`'s `permissions`) holds for each role. Tests only.
import type { Permission, Role } from "@/lib/navigation";

const SEED: Partial<Record<Role, readonly Permission[]>> = {
  platform_administrator: ["identity.user.list", "opportunities.opportunity.read"],
  presales_engineer: ["identity.user.search", "opportunities.opportunity.create"],
  head_of_delivery: ["opportunities.opportunity.read"],
};

/** The permissions Auth0 issues for these roles, sorted like the API returns them. */
export function permissionsFor(roles: readonly Role[]): Permission[] {
  return [...new Set(roles.flatMap((role) => SEED[role] ?? []))].sort();
}
