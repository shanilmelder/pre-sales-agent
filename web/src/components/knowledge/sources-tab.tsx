"use client";

import { useEffect, useRef, useState } from "react";

import { loadSources } from "@/app/knowledge/actions";
import { SourceInspector } from "@/components/knowledge/source-inspector";
import {
  SourceRegisterForm,
  type IntegrationTypeOption,
} from "@/components/knowledge/source-register-form";
import { SourcesTable } from "@/components/knowledge/sources-table";
import { isEditableTarget } from "@/components/shell/keyboard-shortcuts";
import {
  RIGHT_PANE_TOGGLE_ID,
  RightPaneContent,
  useShell,
} from "@/components/shell/shell-context";
import type { Role } from "@/lib/navigation";
import {
  applyFilters,
  canRegister,
  hasFilters,
  isParsePending,
  mergeSources,
  NO_FILTERS,
  ownersOf,
  PARSE_POLL_LIMIT_MS,
  PARSE_POLL_MS,
  productsOf,
  upsert,
  type Filters,
  type KnowledgeSource,
} from "@/lib/knowledge-sources";

const selectClass =
  "h-7 rounded-md border border-input bg-background px-1.5 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary";

/** Knowledge → Sources: the list in the main pane (filters by product, Integration Type,
 * owner and stale; status updates by polling while a parse is pending); the selected
 * Source's inspector, or the register form (`c`), in the right pane. */
export function SourcesTab({
  initialSources,
  integrationTypes,
  me,
}: {
  initialSources: readonly KnowledgeSource[];
  /** The active Integration Types, for tagging. */
  integrationTypes: readonly IntegrationTypeOption[];
  me: { id: string; roles: readonly Role[] };
}) {
  const { rightPaneOpen, setRightPaneOpen, singleKeyShortcuts, dialog } = useShell();
  const [sources, setSources] = useState<readonly KnowledgeSource[]>(initialSources);
  const [syncedFrom, setSyncedFrom] = useState(initialSources);
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [focusRequest, setFocusRequest] = useState(0);
  const returnFocusTo = useRef<string | null>(null);
  const local = useRef<Map<string, KnowledgeSource>>(new Map());
  const mayRegister = canRegister(me.roles);
  const isAdmin = me.roles.includes("platform_administrator");

  // A server refresh (e.g. router.refresh or revisiting the page) brings new rows.
  if (initialSources !== syncedFrom) {
    setSyncedFrom(initialSources);
    setSources(initialSources);
  }

  const selected = sources.find((s) => s.id === selectedId) ?? null;
  const visible = applyFilters(sources, filters);
  const pending = sources.some(isParsePending);

  // While a parse is pending the list is re-read every couple of seconds, for a bounded time.
  useEffect(() => {
    if (!pending) return;
    const startedAt = Date.now();
    const timer = setInterval(() => {
      if (Date.now() - startedAt > PARSE_POLL_LIMIT_MS) {
        clearInterval(timer);
        return;
      }
      loadSources()
        .then((result) => {
          if (result.kind === "ok") {
            // Keep what this page changed since the read began (a newer row version).
            setSources(mergeSources(result.sources, [...local.current.values()]));
          }
        })
        .catch(() => {});
    }, PARSE_POLL_MS);
    return () => clearInterval(timer);
  }, [pending]);

  // When the pane closes after a keyboard open, focus goes back to the row, not the toggle.
  useEffect(() => {
    if (rightPaneOpen) return;
    const id = returnFocusTo.current;
    returnFocusTo.current = null;
    const active = document.activeElement;
    if (id && (active === document.body || active?.id === RIGHT_PANE_TOGGLE_ID)) {
      document.querySelector<HTMLElement>(`[data-source-id="${id}"]`)?.focus();
    }
  }, [rightPaneOpen]);

  function startCreate() {
    if (!mayRegister) return;
    setCreating(true);
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  // `c` opens the register form. The shell leaves it to this page (it would otherwise start
  // an Opportunity), so only the keys the shell ignores reach here.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "c" || event.isComposing || event.repeat) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (!singleKeyShortcuts || dialog || isEditableTarget(event.target)) return;
      if (event.target instanceof Element && event.target.closest('[role="menu"]')) return;
      if (!mayRegister) return;
      event.preventDefault();
      startCreate();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // `startCreate` only reads `rightPaneOpen`, `mayRegister` and the setters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [singleKeyShortcuts, dialog, rightPaneOpen, mayRegister]);

  function open(source: KnowledgeSource, viaKeyboard: boolean) {
    setCreating(false);
    setSelectedId(source.id);
    returnFocusTo.current = viaKeyboard ? source.id : null;
    setFocusRequest((n) => (viaKeyboard ? n + 1 : 0));
    if (!rightPaneOpen) setRightPaneOpen(true);
  }

  function replace(next: KnowledgeSource) {
    local.current.set(next.id, next);
    setSources((current) => upsert(current, next));
  }

  function registered(source: KnowledgeSource) {
    replace(source);
    setCreating(false);
    setSelectedId(source.id);
    returnFocusTo.current = source.id;
    setFocusRequest((n) => n + 1);
  }

  function cancelCreate(viaKey: boolean) {
    setCreating(false);
    if (viaKey) {
      const row =
        document.querySelector<HTMLElement>(`[data-source-id="${selectedId}"]`) ??
        document.querySelector<HTMLElement>("[data-source-row]");
      row?.focus();
    }
  }

  const products = productsOf(sources);
  const owners = ownersOf(sources);

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 px-gutter pb-2">
        <label className="flex items-center gap-1 text-label text-muted-foreground">
          Product
          <select
            value={filters.product}
            onChange={(event) => setFilters({ ...filters, product: event.target.value })}
            className={selectClass}
          >
            <option value="">All</option>
            {products.map((product) => (
              <option key={product} value={product}>
                {product}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-label text-muted-foreground">
          Integration Type
          <select
            value={filters.integrationTypeId}
            onChange={(event) => setFilters({ ...filters, integrationTypeId: event.target.value })}
            className={selectClass}
          >
            <option value="">All</option>
            {integrationTypes.map((type) => (
              <option key={type.id} value={type.id}>
                {type.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-label text-muted-foreground">
          Owner
          <select
            value={filters.ownerId}
            onChange={(event) => setFilters({ ...filters, ownerId: event.target.value })}
            className={selectClass}
          >
            <option value="">All</option>
            {owners.map((owner) => (
              <option key={owner.id} value={owner.id}>
                {owner.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1 text-label text-muted-foreground">
          <input
            type="checkbox"
            checked={filters.staleOnly}
            onChange={(event) => setFilters({ ...filters, staleOnly: event.target.checked })}
          />
          Stale only
        </label>
        {hasFilters(filters) ? (
          <button
            type="button"
            onClick={() => setFilters(NO_FILTERS)}
            className="h-7 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
          >
            Clear filters
          </button>
        ) : null}
        {mayRegister ? (
          <button
            type="button"
            onClick={startCreate}
            aria-keyshortcuts="c"
            className="ml-auto h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
          >
            Register Source
          </button>
        ) : null}
      </div>
      <SourcesTable
        sources={visible}
        total={sources.length}
        selectedId={selectedId}
        onOpen={open}
      />
      {creating ? (
        <RightPaneContent>
          <SourceRegisterForm
            integrationTypes={integrationTypes}
            isAdmin={isAdmin}
            onRegistered={registered}
            onCancel={cancelCreate}
          />
        </RightPaneContent>
      ) : selected ? (
        <RightPaneContent>
          <SourceInspector
            key={selected.id}
            source={selected}
            me={me}
            integrationTypes={integrationTypes}
            onChange={replace}
            focusRequest={focusRequest}
          />
        </RightPaneContent>
      ) : null}
    </>
  );
}
