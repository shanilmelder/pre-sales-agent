// The one definition of the shell's keyboard shortcuts. The key handler matches events
// against it and the cheat sheet lists it, so the two cannot drift apart.
import { NAV_ITEMS, type NavItem } from "@/lib/navigation";

export type ShortcutId =
  | "open-palette"
  | "open-cheat-sheet"
  | "toggle-right-pane"
  | "toggle-sidebar"
  | "close-layer"
  | `go-${NavItem["id"]}`;

export type Shortcut = {
  id: ShortcutId;
  description: string;
  /** Keys as shown in the cheat sheet. `Mod` renders as ⌘ or Ctrl. */
  keys: readonly string[];
  /** What the handler matches: one key (with ⌘/Ctrl when `mod`), or a `g` sequence. */
  match:
    | { kind: "key"; key: string; mod?: boolean }
    | { kind: "sequence"; keys: readonly [string, string] };
  /** Single-key shortcuts are switched off by the preference. */
  singleKey: boolean;
};

/** How long the second key of a `g` sequence may take. */
export const SEQUENCE_TIMEOUT_MS = 1000;

const goShortcuts: Shortcut[] = NAV_ITEMS.flatMap((item) =>
  item.gKey
    ? [
        {
          id: `go-${item.id}` as const,
          description: `Go to ${item.label}`,
          keys: ["G", item.gKey.toUpperCase()],
          match: { kind: "sequence", keys: ["g", item.gKey] } as const,
          singleKey: true,
        },
      ]
    : [],
);

export const SHORTCUTS: readonly Shortcut[] = [
  {
    id: "open-palette",
    description: "Open the command palette",
    keys: ["Mod", "K"],
    match: { kind: "key", key: "k", mod: true },
    singleKey: false,
  },
  ...goShortcuts,
  {
    id: "toggle-right-pane",
    description: "Show or hide the right pane",
    keys: ["]"],
    match: { kind: "key", key: "]" },
    singleKey: true,
  },
  {
    id: "toggle-sidebar",
    description: "Collapse or expand the sidebar",
    keys: ["["],
    match: { kind: "key", key: "[" },
    singleKey: true,
  },
  {
    id: "open-cheat-sheet",
    description: "Show keyboard shortcuts",
    keys: ["?"],
    match: { kind: "key", key: "?" },
    singleKey: true,
  },
  {
    id: "close-layer",
    description: "Close the palette, cheat sheet or right pane",
    keys: ["Esc"],
    match: { kind: "key", key: "Escape" },
    singleKey: false,
  },
];
