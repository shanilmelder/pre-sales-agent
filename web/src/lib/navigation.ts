// The shell's navigation: one list drives the sidebar, the palette, `g` sequences and the
// landing redirect. Safe to import from server and client code.
import {
  BookOpenIcon,
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

/** Story 10.3: the permission that opens Reports (Head of Delivery, platform administrators). */
export const REPORTS_PERMISSION = "reporting.report.read";

export type NavItem = {
  id: "inbox" | "opportunities" | "knowledge" | "reports" | "admin";
  label: string;
  href: string;
  icon: LucideIcon;
  /** The second key of the `g` sequence, if the item has one. */
  gKey?: string;
  /** Shown only to users holding `identity.user.list`. */
  adminOnly?: boolean;
  /** Shown (in the sidebar, the palette and as a `g` shortcut) only to holders of this
   * permission. */
  requires?: Permission;
  /** Story 9.2: the item shows the Inbox unread count. */
  badge?: "inbox-unread";
};

export const NAV_ITEMS: readonly NavItem[] = [
  {
    id: "inbox",
    label: "Inbox",
    href: "/inbox",
    icon: InboxIcon,
    gKey: "i",
    badge: "inbox-unread",
  },
  {
    id: "opportunities",
    label: "Opportunities",
    href: "/opportunities",
    icon: FolderKanbanIcon,
    gKey: "o",
  },
  { id: "knowledge", label: "Knowledge", href: "/knowledge", icon: BookOpenIcon, gKey: "k" },
  {
    id: "reports",
    label: "Reports",
    href: "/reports",
    icon: ChartColumnIcon,
    gKey: "r",
    requires: REPORTS_PERMISSION,
  },
  { id: "admin", label: "Admin", href: "/admin", icon: ShieldCheckIcon, adminOnly: true },
];

/** Whether the user may open Admin (Users & roles). Display only: the API decides. */
export function isAdmin(permissions: readonly Permission[]): boolean {
  return permissions.includes(USER_LIST_PERMISSION);
}

/** Whether the user may open Reports. Display only: the API decides. */
export function canReadReports(permissions: readonly Permission[]): boolean {
  return permissions.includes(REPORTS_PERMISSION);
}

/** Whether the user may see this nav item (its `adminOnly` and `requires`). */
export function canSeeNavItem(item: NavItem, permissions: readonly Permission[]): boolean {
  if (item.adminOnly && !isAdmin(permissions)) return false;
  return !item.requires || permissions.includes(item.requires);
}

/** The nav items this user sees. Display only: each page still gates itself. */
export function visibleNav(permissions: readonly Permission[]): NavItem[] {
  return NAV_ITEMS.filter((item) => canSeeNavItem(item, permissions));
}

/** The Opportunities list on its Mine view. */
export const MY_OPPORTUNITIES_HREF = "/opportunities?view=mine";

/** Where `/` sends a user: presales engineers to their Opportunities, everyone else to Inbox. */
export function landingFor(roles: readonly Role[]): string {
  return roles.includes("presales_engineer") ? MY_OPPORTUNITIES_HREF : "/inbox";
}
