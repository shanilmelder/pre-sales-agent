// The shell's navigation: one list drives the sidebar, the palette, `g` sequences and the
// landing redirect. Safe to import from server and client code.
import {
  BookOpenIcon,
  BriefcaseBusinessIcon,
  ChartColumnIcon,
  FolderKanbanIcon,
  InboxIcon,
  ShieldCheckIcon,
  type LucideIcon,
} from "lucide-react";

import type { components } from "@/lib/api/client";

export type Role = components["schemas"]["Role"];

/** An Auth0 permission name, equal to an API action (e.g. `identity.user.list`). */
export type Permission = string;

/** The permission that lists users: it opens Admin. */
export const USER_LIST_PERMISSION = "identity.user.list";

export type NavItem = {
  id: "inbox" | "my-opportunities" | "opportunities" | "knowledge" | "reports" | "admin";
  label: string;
  href: string;
  icon: LucideIcon;
  /** The second key of the `g` sequence, if the item has one. */
  gKey?: string;
  /** Shown only to users holding `identity.user.list`. */
  adminOnly?: boolean;
};

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "inbox", label: "Inbox", href: "/inbox", icon: InboxIcon, gKey: "i" },
  {
    id: "my-opportunities",
    label: "My Opportunities",
    href: "/my-opportunities",
    icon: BriefcaseBusinessIcon,
    gKey: "m",
  },
  {
    id: "opportunities",
    label: "All Opportunities",
    href: "/opportunities",
    icon: FolderKanbanIcon,
    gKey: "a",
  },
  { id: "knowledge", label: "Knowledge", href: "/knowledge", icon: BookOpenIcon, gKey: "k" },
  { id: "reports", label: "Reports", href: "/reports", icon: ChartColumnIcon, gKey: "r" },
  { id: "admin", label: "Admin", href: "/admin", icon: ShieldCheckIcon, adminOnly: true },
];

/** Whether the user may open Admin (Users & roles). Display only: the API decides. */
export function isAdmin(permissions: readonly Permission[]): boolean {
  return permissions.includes(USER_LIST_PERMISSION);
}

/** The nav items this user sees. Display only: each page still gates itself. */
export function visibleNav(permissions: readonly Permission[]): NavItem[] {
  const admin = isAdmin(permissions);
  return NAV_ITEMS.filter((item) => !item.adminOnly || admin);
}

/** Where `/` sends a user: presales engineers to My Opportunities, everyone else to Inbox. */
export function landingFor(roles: readonly Role[]): string {
  return roles.includes("presales_engineer") ? "/my-opportunities" : "/inbox";
}
