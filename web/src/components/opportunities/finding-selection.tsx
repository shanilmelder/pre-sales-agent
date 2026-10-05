"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

type Selection = { key: string | null; setKey: (key: string | null) => void };

const FindingSelectionContext = createContext<Selection | null>(null);

/** One selected Finding across every section inside it (the Assessments tab's Specialist
 * Assessments and Red Team), since they share the one right-pane slot: selecting a Finding
 * in one section clears the selection in the others. */
export function FindingSelectionProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [key, setKey] = useState<string | null>(null);
  const value = useMemo(() => ({ key, setKey }), [key]);
  return (
    <FindingSelectionContext.Provider value={value}>
      {children}
    </FindingSelectionContext.Provider>
  );
}

/** The section's selected Finding id and its setter. Inside a `FindingSelectionProvider` the
 * selection is shared (keyed by `scope`), so only one section has a Finding selected at a
 * time; outside one it is the section's own state. */
export function useFindingSelection(
  scope: string,
): [string | null, (id: string | null) => void] {
  const shared = useContext(FindingSelectionContext);
  const [local, setLocal] = useState<string | null>(null);
  const prefix = `${scope}:`;
  const setShared = shared?.setKey;
  const setSelected = useCallback(
    (id: string | null) => {
      if (setShared) setShared(id === null ? null : `${prefix}${id}`);
      else setLocal(id);
    },
    [setShared, prefix],
  );
  if (!shared) return [local, setSelected];
  const id = shared.key?.startsWith(prefix)
    ? shared.key.slice(prefix.length)
    : null;
  return [id, setSelected];
}
