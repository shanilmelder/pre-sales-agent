// The nine platform roles in display order, with their labels. Safe on server and client.
import type { Role } from "@/lib/navigation";

export const ROLES: readonly { value: Role; label: string }[] = [
  { value: "presales_engineer", label: "Presales engineer" },
  { value: "sales_representative", label: "Sales representative" },
  { value: "engineering_reviewer", label: "Engineering reviewer" },
  { value: "pm_reviewer", label: "PM reviewer" },
  { value: "security_reviewer", label: "Security reviewer" },
  { value: "commercial", label: "Commercial" },
  { value: "delivery_manager", label: "Delivery manager" },
  { value: "head_of_delivery", label: "Head of Delivery" },
  { value: "platform_administrator", label: "Platform administrator" },
];

const LABELS = new Map(ROLES.map((role) => [role.value, role.label]));

export function roleLabel(role: Role): string {
  return LABELS.get(role) ?? role;
}

export function isRole(value: unknown): value is Role {
  return typeof value === "string" && LABELS.has(value as Role);
}
