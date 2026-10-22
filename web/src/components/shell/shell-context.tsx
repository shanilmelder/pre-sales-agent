"use client";

import {
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { LiveRegionProvider, useAnnounce } from "@/components/shell/live-region";
// Types only: the preferences module imports next/headers.
import type { Density, Theme } from "@/lib/preferences";

/** DOM ids shared by the right pane and its toggle (for focus return on close). */
export const RIGHT_PANE_ID = "right-pane";
export const RIGHT_PANE_TOGGLE_ID = "right-pane-toggle";

export type RightPaneTab = "inspector" | "activity";

export type ShellDialog = "palette" | "cheat-sheet";
export type ShellLayer = ShellDialog | "right-pane";

type ShellState = {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  rightPaneOpen: boolean;
  setRightPaneOpen: (open: boolean) => void;
  toggleRightPane: () => void;
  /** The active right-pane tab. Opening the pane, or selecting a row, shows Inspector. */
  rightPaneTab: RightPaneTab;
  setRightPaneTab: (tab: RightPaneTab) => void;
  /** The open dialog, if any. Only one is open at a time. */
  dialog: ShellDialog | null;
  openDialog: (dialog: ShellDialog) => void;
  closeDialog: () => void;
  /** Open layers, bottom to top. `Esc` closes the last one. */
  layers: ShellLayer[];
  closeTopLayer: () => void;
  singleKeyShortcuts: boolean;
  /** The stored theme and density, for the user card's theme toggle. */
  theme: Theme;
  density: Density;
  /** No preferences cookie yet: the shell shows the shortcut hint until it is answered. */
  firstRun: boolean;
  dismissFirstRun: () => void;
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
  firstRun = false,
  theme = "system",
  density = "comfortable",
  children,
}: {
  singleKeyShortcuts: boolean;
  firstRun?: boolean;
  theme?: Theme;
  density?: Density;
  children: ReactNode;
}) {
  return (
    <LiveRegionProvider>
      <ShellProvider
        singleKeyShortcuts={singleKeyShortcuts}
        firstRun={firstRun}
        theme={theme}
        density={density}
      >
        {children}
      </ShellProvider>
    </LiveRegionProvider>
  );
}

export function ShellProvider({
  singleKeyShortcuts,
  firstRun = false,
  theme = "system",
  density = "comfortable",
  children,
}: {
  singleKeyShortcuts: boolean;
  firstRun?: boolean;
  theme?: Theme;
  density?: Density;
  children: ReactNode;
}) {
  const announce = useAnnounce();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [rightPaneOpen, setRightPaneOpenState] = useState(false);
  const [rightPaneTab, setRightPaneTab] = useState<RightPaneTab>("inspector");
  const [dialog, setDialog] = useState<ShellDialog | null>(null);
  const [workspaceTabs, setWorkspaceTabs] = useState<readonly string[] | null>(null);
  const [firstRunAnswered, setFirstRunAnswered] = useState(false);
  const dismissFirstRun = useCallback(() => setFirstRunAnswered(true), []);

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
      if (open) setRightPaneTab("inspector");
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
      rightPaneTab,
      setRightPaneTab,
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
      theme,
      density,
      firstRun: firstRun && !firstRunAnswered,
      dismissFirstRun,
      workspaceTabs,
      setWorkspaceTabs,
    };
  }, [
    sidebarCollapsed,
    rightPaneOpen,
    setRightPaneOpen,
    rightPaneTab,
    dialog,
    singleKeyShortcuts,
    theme,
    density,
    firstRun,
    firstRunAnswered,
    dismissFirstRun,
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
  /** How many `RightPaneContent`s are mounted; the Inspector shows its empty text at 0. */
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
 * while it is mounted the pane no longer shows its empty text. */
export function RightPaneContent({ children }: { children: ReactNode }) {
  const { setRightPaneTab } = useShell();
  const { target, register } = useRightPaneSlot();
  useEffect(() => register(), [register]);
  // Selecting a row mounts the content, or swaps its keyed child: show Inspector then,
  // even if Activity was the active tab.
  const childKey = isValidElement(children) ? children.key : null;
  useEffect(() => setRightPaneTab("inspector"), [childKey, setRightPaneTab]);
  return target ? createPortal(children, target) : null;
}
