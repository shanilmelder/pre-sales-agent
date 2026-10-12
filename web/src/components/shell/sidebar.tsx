"use client";

import { cn } from "cn";
import { KeyboardIcon, PanelLeftCloseIcon, PanelLeftOpenIcon, SearchIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AvatarMenu } from "@/components/avatar-menu";
import { useModKeyLabel } from "@/components/shell/keyboard-shortcuts";
import { useShell } from "@/components/shell/shell-context";
import type { Me } from "@/lib/api/server";
import { visibleNav } from "@/lib/navigation";

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="ml-auto rounded-sm border border-border px-1 font-sans text-meta text-muted-foreground">
      {children}
    </kbd>
  );
}

const itemClass =
  "flex h-row w-full items-center gap-2 rounded-sm px-2 text-body text-sidebar-foreground outline-none hover:bg-sidebar-accent focus-visible:ring-2 focus-visible:ring-primary";

/** Primary navigation. Below 1280px, or when collapsed with `[`, only icons show. */
export function Sidebar({ me }: { me: Pick<Me, "name" | "email" | "permissions"> }) {
  const pathname = usePathname();
  const { sidebarCollapsed, toggleSidebar, openDialog } = useShell();
  const modKey = useModKeyLabel();
  // Labels stay in the accessibility tree when only icons show.
  const label = sidebarCollapsed ? "sr-only" : "sr-only min-[1280px]:not-sr-only";
  const hint = sidebarCollapsed ? "hidden" : "hidden min-[1280px]:inline-flex";

  return (
    <nav
      aria-label="Primary"
      data-collapsed={sidebarCollapsed ? "true" : "false"}
      className={cn(
        "flex h-full w-12 shrink-0 flex-col gap-2 border-r border-sidebar-border bg-surface-sidebar p-1.5",
        !sidebarCollapsed && "min-[1280px]:w-sidebar",
      )}
    >
      <button
        type="button"
        title={`Search or run a command (${modKey} K)`}
        className={itemClass}
        onClick={() => openDialog("palette")}
      >
        <SearchIcon className="size-4 shrink-0" aria-hidden="true" />
        <span className={label}>Search or run a command</span>
        <span className={hint} aria-hidden="true">
          <Kbd>{modKey} K</Kbd>
        </span>
      </button>

      <ul className="flex flex-1 flex-col gap-0.5">
        {visibleNav(me.permissions).map((item) => {
          const active = pathname === item.href || pathname.startsWith(item.href + "/");
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                title={item.label}
                className={cn(itemClass, active && "bg-sidebar-accent text-body-strong")}
              >
                <Icon className="size-4 shrink-0" aria-hidden="true" />
                <span className={label}>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="flex flex-col gap-0.5 border-t border-sidebar-border pt-1.5">
        <button
          type="button"
          title="Keyboard shortcuts (?)"
          className={itemClass}
          onClick={() => openDialog("cheat-sheet")}
        >
          <KeyboardIcon className="size-4 shrink-0" aria-hidden="true" />
          <span className={label}>Keyboard shortcuts</span>
          <span className={hint} aria-hidden="true">
            <Kbd>?</Kbd>
          </span>
        </button>
        <button
          type="button"
          title="Collapse sidebar ([)"
          className={itemClass}
          aria-pressed={sidebarCollapsed}
          onClick={toggleSidebar}
        >
          {sidebarCollapsed ? (
            <PanelLeftOpenIcon className="size-4 shrink-0" aria-hidden="true" />
          ) : (
            <PanelLeftCloseIcon className="size-4 shrink-0" aria-hidden="true" />
          )}
          <span className={label}>Collapse sidebar</span>
          <span className={hint} aria-hidden="true">
            <Kbd>[</Kbd>
          </span>
        </button>
        <div className="px-0.5 pt-1">
          <AvatarMenu name={me.name} email={me.email} side="top" align="start" />
        </div>
      </div>
    </nav>
  );
}
