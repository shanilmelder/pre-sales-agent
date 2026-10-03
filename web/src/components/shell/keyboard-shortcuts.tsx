"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useSyncExternalStore } from "react";

import { useShell } from "@/components/shell/shell-context";
import { NAV_ITEMS, type Role } from "@/lib/navigation";
import {
  NEW_OPPORTUNITY_HREF,
  SEQUENCE_TIMEOUT_MS,
  SHORTCUTS,
  shortcutsFor,
  type Shortcut,
  type ShortcutId,
} from "@/lib/shortcuts";

/** Input types that don't take typed text: shortcuts still work while they have focus. */
const NON_TEXT_INPUT_TYPES = new Set([
  "radio",
  "checkbox",
  "button",
  "submit",
  "reset",
  "range",
  "color",
  "file",
  "image",
]);

/** True when the event comes from a place where keys type text. */
export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false;
  const input = target.closest("input");
  if (input) return !NON_TEXT_INPUT_TYPES.has(input.type);
  if (target.closest("textarea, select")) return true;
  const editable = target.closest("[contenteditable]");
  return editable !== null && editable.getAttribute("contenteditable") !== "false";
}

function isMac(): boolean {
  return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
}

const subscribeNothing = () => () => {};

/** "⌘" on Apple platforms, "Ctrl" elsewhere (and during server rendering). */
export function useModKeyLabel(): string {
  return useSyncExternalStore(
    subscribeNothing,
    () => (isMac() ? "⌘" : "Ctrl"),
    () => "Ctrl",
  );
}

/** ⌘/Ctrl and Alt as the shortcuts see them. AltGr (reported as Ctrl+Alt on Windows and
 * Linux) only selects a character such as `[` or `]`, so it counts as no modifier. */
function modifiers(event: KeyboardEvent): { mod: boolean; alt: boolean } {
  const altGraph =
    event.getModifierState?.("AltGraph") || (!isMac() && event.ctrlKey && event.altKey);
  if (altGraph) return { mod: false, alt: false };
  return { mod: event.metaKey || event.ctrlKey, alt: event.altKey };
}

function matchesKey(shortcut: Shortcut, event: KeyboardEvent): boolean {
  if (shortcut.match.kind !== "key") return false;
  const { mod, alt } = modifiers(event);
  if (shortcut.match.mod) {
    return (
      mod && !alt && !event.shiftKey && event.key.toLowerCase() === shortcut.match.key
    );
  }
  return !mod && !alt && event.key === shortcut.match.key;
}

/** The key as a `g` sequence compares it: single letters ignore case (Shift, Caps Lock). */
function sequenceKey(key: string): string {
  return /^[a-z]$/i.test(key) ? key.toLowerCase() : key;
}

const SEQUENCES = SHORTCUTS.filter(
  (s): s is Shortcut & { match: { kind: "sequence" } } => s.match.kind === "sequence",
);

/** The shell's global key handler. Matches events against the user's shortcuts (`SHORTCUTS`
 * minus those needing a permission they lack). */
export function KeyboardShortcuts({ roles }: { roles: readonly Role[] }) {
  const router = useRouter();
  const pathname = usePathname();
  const shell = useShell();
  const pending = useRef<{ key: string; at: number } | null>(null);
  const rolesKey = roles.join(",");

  useEffect(() => {
    const shortcuts = shortcutsFor(rolesKey ? (rolesKey.split(",") as Role[]) : []);

    function run(id: ShortcutId) {
      switch (id) {
        case "open-palette":
          if (shell.dialog === "palette") shell.closeDialog();
          else shell.openDialog("palette");
          return;
        case "open-cheat-sheet":
          shell.openDialog("cheat-sheet");
          return;
        case "toggle-right-pane":
          shell.toggleRightPane();
          return;
        case "toggle-sidebar":
          shell.toggleSidebar();
          return;
        case "close-layer":
          shell.closeTopLayer();
          return;
        case "create-opportunity":
          router.push(NEW_OPPORTUNITY_HREF);
          return;
        case "switch-workspace-tab":
          // Handled with the digit in `onKeyDown`.
          return;
        default: {
          const item = NAV_ITEMS.find((nav) => `go-${nav.id}` === id);
          if (item) router.push(item.href);
        }
      }
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.isComposing) return;
      // Held keys don't repeat shortcuts; a held Esc may keep closing layers.
      if (event.repeat && event.key !== "Escape") return;
      const shortcut = shortcuts.find((s) => matchesKey(s, event));
      const editable = isEditableTarget(event.target);
      const inMenu =
        event.target instanceof Element && event.target.closest('[role="menu"]') !== null;

      if (shortcut?.id === "close-layer") {
        pending.current = null;
        if (shell.dialog) {
          // Close the dialog here so the right pane underneath stays open.
          event.preventDefault();
          event.stopPropagation();
          run("close-layer");
          return;
        }
        // A menu or a text field handles its own Esc.
        if (editable || inMenu) return;
        if (shell.layers.length > 0) run("close-layer");
        return;
      }

      // ⌘K/Ctrl+K inside the palette's own search field closes it again.
      if (shortcut?.id === "open-palette" && shell.dialog === "palette") {
        event.preventDefault();
        run("open-palette");
        return;
      }

      if (editable) {
        pending.current = null;
        return;
      }

      if (shortcut && !shortcut.singleKey) {
        event.preventDefault();
        run(shortcut.id);
        return;
      }

      const { mod, alt } = modifiers(event);
      if (mod || alt) {
        pending.current = null;
        return;
      }
      // Single keys: off by preference, inert while a dialog is open, and left to an open
      // menu (which uses letters for typeahead).
      if (!shell.singleKeyShortcuts || shell.dialog || inMenu) {
        pending.current = null;
        return;
      }

      const key = sequenceKey(event.key);
      const first = pending.current;
      pending.current = null;
      if (first && Date.now() - first.at <= SEQUENCE_TIMEOUT_MS) {
        const sequence = SEQUENCES.find(
          (s) => s.match.keys[0] === first.key && s.match.keys[1] === key,
        );
        if (sequence) {
          event.preventDefault();
          run(sequence.id);
        }
        // Any other key cancels the sequence.
        return;
      }

      // `1`–`9`: the workspace tab with that number, while a workspace is open.
      if (/^[1-9]$/.test(event.key)) {
        const href = shell.workspaceTabs?.[Number(event.key) - 1];
        if (href) {
          event.preventDefault();
          // The tab already open: no duplicate history entry.
          if (href !== pathname) router.push(href);
        }
        return;
      }

      if (SEQUENCES.some((s) => s.match.keys[0] === key)) {
        pending.current = { key, at: Date.now() };
        return;
      }

      if (shortcut) {
        event.preventDefault();
        run(shortcut.id);
      }
    }

    // Capture phase: runs before dialogs see the key, so Esc closes only the top layer.
    window.addEventListener("keydown", onKeyDown, true);
    return () => window.removeEventListener("keydown", onKeyDown, true);
  }, [router, pathname, shell, rolesKey]);

  return null;
}
