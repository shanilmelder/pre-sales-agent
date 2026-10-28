// The Auth0 role-to-permission seed from the README ("Auth0 setup"): what a token's
// `permissions` claim (and so `/me`'s `permissions`) holds for each role. Tests only.
import type { Permission, Role } from "@/lib/navigation";

const CHECKLIST_AUTHOR = [
  "knowledge.checklist.create",
  "knowledge.checklist.edit",
  "knowledge.checklist.publish",
  "knowledge.checklist.retire",
] as const;

const SEED: Partial<Record<Role, readonly Permission[]>> = {
  platform_administrator: [
    "identity.user.list",
    "knowledge.catalogue_entry.create",
    "knowledge.catalogue_entry.edit",
    "knowledge.catalogue_entry.reactivate",
    "knowledge.catalogue_entry.retire",
    "knowledge.checklist.create",
    "knowledge.checklist.edit",
    "knowledge.checklist.publish",
    "knowledge.checklist.retire",
    "knowledge.source.add_version",
    "knowledge.source.register",
    "knowledge.source.retag",
    "knowledge.source.retire",
    "knowledge.source.retry_embed",
    "knowledge.source.retry_parse",
    "knowledge.source.review",
    "opportunities.opportunity.read",
    "platform.retention.read",
    "reporting.report.read",
  ],
  presales_engineer: ["identity.user.search", "opportunities.opportunity.create"],
  head_of_delivery: ["opportunities.opportunity.read", "reporting.report.read"],
  engineering_reviewer: CHECKLIST_AUTHOR,
  pm_reviewer: CHECKLIST_AUTHOR,
  security_reviewer: CHECKLIST_AUTHOR,
};

/** The permissions Auth0 issues for these roles, sorted like the API returns them. */
export function permissionsFor(roles: readonly Role[]): Permission[] {
  return [...new Set(roles.flatMap((role) => SEED[role] ?? []))].sort();
}
