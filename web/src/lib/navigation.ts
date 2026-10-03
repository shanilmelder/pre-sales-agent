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

export type NavItem = {
  id: "inbox" | "my-opportunities" | "opportunities" | "knowledge" | "reports" | "admin";
  label: string;
  href: string;
  icon: LucideIcon;
  /** The second key of the `g` sequence, if the item has one. */
  gKey?: string;
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

export function isAdmin(roles: readonly Role[]): boolean {
  return roles.includes("platform_administrator");
}

/** The nav items this user sees. Display only: each page still gates itself. */
export function visibleNav(roles: readonly Role[]): NavItem[] {
  const admin = isAdmin(roles);
  return NAV_ITEMS.filter((item) => !item.adminOnly || admin);
}

/** Where `/` sends a user: presales engineers to My Opportunities, everyone else to Inbox. */
export function landingFor(roles: readonly Role[]): string {
  return roles.includes("presales_engineer") ? "/my-opportunities" : "/inbox";
}
