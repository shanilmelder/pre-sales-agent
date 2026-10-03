"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

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
  /** Where `1`–`9` go, in key order, while an Opportunity workspace is mounted (else null).
   * Set through `useWorkspaceTabKeys`; the global key handler applies the single-key rules. */
  workspaceTabs: readonly string[] | null;
  setWorkspaceTabs: (hrefs: readonly string[] | null) => void;
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
  const [workspaceTabs, setWorkspaceTabs] = useState<readonly string[] | null>(null);

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
      workspaceTabs,
      setWorkspaceTabs,
    };
  }, [
    sidebarCollapsed,
    rightPaneOpen,
    setRightPaneOpen,
    dialog,
    singleKeyShortcuts,
    workspaceTabs,
  ]);

  return (
    <ShellContext.Provider value={value}>
      <RightPaneSlotProvider>{children}</RightPaneSlotProvider>
    </ShellContext.Provider>
  );
}

/** Registers the workspace's tab hrefs (index 0 is key `1`) with the global key handler
 * while the calling component is mounted. */
export function useWorkspaceTabKeys(hrefs: readonly string[]) {
  const { setWorkspaceTabs } = useShell();
  // A string dependency: a new array with the same hrefs doesn't re-register.
  const key = hrefs.join("\n");
  useEffect(() => {
    setWorkspaceTabs(key ? key.split("\n") : []);
    return () => setWorkspaceTabs(null);
  }, [key, setWorkspaceTabs]);
}

// --- right-pane content slot ----------------------------------------------------------------

type RightPaneSlot = {
  /** The element the right pane renders page content into (null while it is closed). */
  target: HTMLElement | null;
  setTarget: (element: HTMLElement | null) => void;
  /** How many `RightPaneContent`s are mounted; the pane shows "Nothing selected." at 0. */
  contentCount: number;
  register: () => () => void;
};

const RightPaneSlotContext = createContext<RightPaneSlot | null>(null);

function RightPaneSlotProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<HTMLElement | null>(null);
  const [contentCount, setContentCount] = useState(0);
  const register = useCallback(() => {
    setContentCount((count) => count + 1);
    return () => setContentCount((count) => count - 1);
  }, []);
  const value = useMemo(
    () => ({ target, setTarget, contentCount, register }),
    [target, contentCount, register],
  );
  return <RightPaneSlotContext.Provider value={value}>{children}</RightPaneSlotContext.Provider>;
}

export function useRightPaneSlot(): RightPaneSlot {
  const slot = useContext(RightPaneSlotContext);
  if (!slot) throw new Error("useRightPaneSlot must be used inside <ShellProvider>");
  return slot;
}

/** Renders `children` inside the right pane (e.g. a list's inspector) while the pane is
 * open. The content stays part of the page's React tree, so its state lives with the page;
 * while it is mounted the pane no longer says "Nothing selected." */
export function RightPaneContent({ children }: { children: ReactNode }) {
  const { target, register } = useRightPaneSlot();
  useEffect(() => register(), [register]);
  return target ? createPortal(children, target) : null;
}
