"use client";

import { cn } from "cn";
import {
  ChevronsUpDownIcon,
  KeyboardIcon,
  PanelLeftCloseIcon,
  PanelLeftOpenIcon,
  SearchIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { BrandMark } from "@/components/shell/brand-mark";
import { useModKeyLabel } from "@/components/shell/keyboard-shortcuts";
import { useShell } from "@/components/shell/shell-context";
import { UserCard } from "@/components/shell/user-card";
import type { Me } from "@/lib/api/server";
import { badgeText, inboxLinkName, opportunityIdOf } from "@/lib/inbox";
import { visibleNav } from "@/lib/navigation";
import { useInboxUnread } from "@/lib/use-inbox-count";

/** A shortcut hint at the end of a row: plain 12px text, as in the mockup. */
function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="ml-auto font-sans text-meta text-text-secondary">{children}</kbd>;
}

const focusRing = "outline-none focus-visible:ring-2 focus-visible:ring-primary";
// Nav links: 18px icons, 10px gap, 7px 8px padding, radius 8, 14px text.
const navClass = `flex w-full items-center gap-2.5 rounded-md px-2 py-[7px] ${focusRing}`;
// Footer buttons (Keyboard shortcuts, Collapse sidebar): 13px secondary text.
const footerClass = `flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-text-secondary hover:bg-surface-alt hover:text-foreground ${focusRing}`;

/** The Inbox unread count on its nav item (Story 9.2): hidden at 0, capped at "99+". Over
 * the icon when only icons show. The link's accessible name carries the count. */
function UnreadBadge({ count, collapsed }: { count: number; collapsed: boolean }) {
  return (
    <span
      aria-hidden="true"
      data-testid="inbox-badge"
      className={cn(
        "absolute top-0.5 right-0.5 min-w-[18px] rounded-full bg-primary px-1 text-center text-[11px] leading-[18px] font-semibold text-primary-foreground text-numeric",
        !collapsed && "min-[1280px]:static min-[1280px]:ml-auto",
      )}
    >
      {badgeText(count)}
    </span>
  );
}

/** Primary navigation. Below 1280px, or when collapsed with `[`, only icons show. */
export function Sidebar({ me }: { me: Pick<Me, "name" | "email" | "roles" | "permissions"> }) {
  const pathname = usePathname();
  const { sidebarCollapsed, toggleSidebar, openDialog } = useShell();
  const modKey = useModKeyLabel();
  const unread = useInboxUnread(opportunityIdOf(pathname));
  // Labels stay in the accessibility tree when only icons show.
  const label = sidebarCollapsed ? "sr-only" : "sr-only min-[1280px]:not-sr-only";
  const hint = sidebarCollapsed ? "hidden" : "hidden min-[1280px]:inline-flex";

  return (
    <nav
      aria-label="Primary"
      data-collapsed={sidebarCollapsed ? "true" : "false"}
      className={cn(
        "flex h-full w-sidebar-collapsed shrink-0 flex-col gap-1 overflow-hidden border-r border-border bg-surface px-2.5 py-3 transition-[width] duration-[160ms] motion-reduce:transition-none",
        !sidebarCollapsed && "min-[1280px]:w-sidebar",
      )}
    >
      {/* One organisation, so a static label rather than a switcher. */}
      <div
        data-testid="org-switcher"
        className="flex w-full items-center gap-2 rounded-md p-1.5 text-foreground"
      >
        <BrandMark className="size-[26px]" />
        <span className={`${cn(label, "min-w-0 flex-1 truncate")} text-[14px] leading-5 font-semibold`}>
          Pre Sales Agent Framework
        </span>
        <span className={hint} aria-hidden="true">
          <ChevronsUpDownIcon className="size-3.5 text-text-secondary" />
        </span>
      </div>
      <button
        type="button"
        title={`Search or run a command (${modKey} K)`}
        className={`my-1.5 flex w-full items-center gap-2 rounded-md border border-border bg-surface-alt px-2 py-1.5 text-left text-text-secondary hover:text-foreground ${focusRing}`}
        onClick={() => openDialog("palette")}
      >
        <SearchIcon className="size-4 shrink-0" aria-hidden="true" />
        <span className={`${cn(label, "flex-1")} text-[13px] leading-5`}>Search or run a command</span>
        <span className={hint} aria-hidden="true">
          <Kbd>{modKey} K</Kbd>
        </span>
      </button>

      <ul className="flex flex-1 flex-col gap-1">
        {visibleNav(me.permissions).map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;
          const count = item.badge === "inbox-unread" ? (unread ?? 0) : 0;
          return (
            <li key={item.id}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                aria-label={count > 0 ? inboxLinkName(count) : undefined}
                title={count > 0 ? inboxLinkName(count) : item.label}
                className={cn(
                  navClass,
                  "relative",
                  active
                    ? "bg-primary-tint text-primary-text"
                    : "text-text-secondary hover:bg-surface-alt hover:text-foreground",
                )}
              >
                <Icon className="size-[18px] shrink-0" aria-hidden="true" />
                <span
                  className={`${cn(label, "truncate")} text-[14px] leading-5 ${active ? "font-semibold" : "font-medium"}`}
                >
                  {item.label}
                </span>
                {count > 0 ? <UnreadBadge count={count} collapsed={sidebarCollapsed} /> : null}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-col gap-0.5">
        <button
          type="button"
          title="Keyboard shortcuts (?)"
          className={footerClass}
          onClick={() => openDialog("cheat-sheet")}
        >
          <KeyboardIcon className="size-4 shrink-0" aria-hidden="true" />
          <span className={`${cn(label, "flex-1")} text-[13px] leading-5`}>Keyboard shortcuts</span>
          <span className={hint} aria-hidden="true">
            <Kbd>?</Kbd>
          </span>
        </button>
        <button
          type="button"
          title="Collapse sidebar ([)"
          className={footerClass}
          aria-pressed={sidebarCollapsed}
          onClick={toggleSidebar}
        >
          {sidebarCollapsed ? (
            <PanelLeftOpenIcon className="size-4 shrink-0" aria-hidden="true" />
          ) : (
            <PanelLeftCloseIcon className="size-4 shrink-0" aria-hidden="true" />
          )}
          <span className={`${cn(label, "flex-1")} text-[13px] leading-5`}>Collapse sidebar</span>
          <span className={hint} aria-hidden="true">
            <Kbd>[</Kbd>
          </span>
        </button>
        <UserCard me={me} collapsed={sidebarCollapsed} />
      </div>
    </nav>
  );
}
