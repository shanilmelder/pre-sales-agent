"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { LiveRegionProvider, useAnnounce } from "@/components/shell/live-region";

/** DOM ids shared by the right pane and its toggle (for focus return on close). */
export const RIGHT_PANE_ID = "right-pane";
export const RIGHT_PANE_TOGGLE_ID = "right-pane-toggle";

export type ShellDialog = "palette" | "cheat-sheet";
export type ShellLayer = ShellDialog | "right-pane";

type ShellState = {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  rightPaneOpen: boolean;
  setRightPaneOpen: (open: boolean) => void;
  toggleRightPane: () => void;
  /** The open dialog, if any. Only one is open at a time. */
  dialog: ShellDialog | null;
  openDialog: (dialog: ShellDialog) => void;
  closeDialog: () => void;
  /** Open layers, bottom to top. `Esc` closes the last one. */
  layers: ShellLayer[];
  closeTopLayer: () => void;
  singleKeyShortcuts: boolean;
};

const ShellContext = createContext<ShellState | null>(null);

export function useShell(): ShellState {
  const state = useContext(ShellContext);
  if (!state) throw new Error("useShell must be used inside <ShellProvider>");
  return state;
}

/** Shell state and the live region. Mounted once in the root layout so they survive
 * navigation; holds no page content, so it doesn't bypass any page's access gate. */
export function ShellProviders({
  singleKeyShortcuts,
  children,
}: {
  singleKeyShortcuts: boolean;
  children: ReactNode;
}) {
  return (
    <LiveRegionProvider>
      <ShellProvider singleKeyShortcuts={singleKeyShortcuts}>{children}</ShellProvider>
    </LiveRegionProvider>
  );
}

export function ShellProvider({
  singleKeyShortcuts,
  children,
}: {
  singleKeyShortcuts: boolean;
  children: ReactNode;
}) {
  const announce = useAnnounce();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [rightPaneOpen, setRightPaneOpenState] = useState(false);
  const [dialog, setDialog] = useState<ShellDialog | null>(null);

  const setRightPaneOpen = useCallback(
    (open: boolean) => {
      if (!open) {
        // Closing with focus inside the pane would drop focus to <body>: hand it to the
        // toggle first.
        const pane = document.getElementById(RIGHT_PANE_ID);
        if (pane?.contains(document.activeElement)) {
          document.getElementById(RIGHT_PANE_TOGGLE_ID)?.focus();
        }
      }
      setRightPaneOpenState(open);
      announce(open ? "Right pane opened" : "Right pane closed");
    },
    [announce],
  );

  const value = useMemo<ShellState>(() => {
    const layers: ShellLayer[] = [];
    if (rightPaneOpen) layers.push("right-pane");
    if (dialog) layers.push(dialog);
    return {
      sidebarCollapsed,
      toggleSidebar: () => setSidebarCollapsed((collapsed) => !collapsed),
      rightPaneOpen,
      setRightPaneOpen,
      toggleRightPane: () => setRightPaneOpen(!rightPaneOpen),
      dialog,
      openDialog: setDialog,
      closeDialog: () => setDialog(null),
      layers,
      closeTopLayer: () => {
        const top = layers.at(-1);
        if (top === "right-pane") setRightPaneOpen(false);
        else if (top) setDialog(null);
      },
      singleKeyShortcuts,
    };
  }, [sidebarCollapsed, rightPaneOpen, setRightPaneOpen, dialog, singleKeyShortcuts]);

  return <ShellContext.Provider value={value}>{children}</ShellContext.Provider>;
}
