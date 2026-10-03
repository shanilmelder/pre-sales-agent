"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState, useTransition } from "react";

import {
  changeCollaborator,
  loadOpportunity,
  searchUsers,
} from "@/app/opportunities/actions";
import { useAnnounce } from "@/components/shell/live-region";
import {
  codePointLength,
  NO_ACCESS_TO_OPPORTUNITY,
  staleMessage,
  type Opportunity,
  type UserSummary,
} from "@/lib/opportunities";

type Notice =
  | { kind: "stale"; changedBy: string | null }
  | { kind: "message"; text: string };

/** How long typing must pause before the people search runs. */
export const SEARCH_DEBOUNCE_MS = 250;
/** The API's shortest query. */
const SEARCH_MIN = 2;

/** A search answer and the (trimmed) query it belongs to. */
type Found = { q: string; users: UserSummary[]; error: boolean };

const SAVE_FAILED = "The change could not be saved. Try again.";
const NOT_OWNER = "Only the owner can change collaborators.";
const RELOAD_FAILED = "The Opportunity could not be reloaded. Try again.";
const SEARCH_FAILED = "People search is not available right now.";

const buttonClass =
  "h-7 shrink-0 rounded-md border border-border px-2 text-label outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary aria-disabled:opacity-60";

/** The Opportunity's owner and collaborators. The owner also gets a people search to add
 * collaborators and a Remove button per collaborator; each change saves with `If-Match`.
 * A 412 shows who changed the Opportunity with a Reload button and overwrites nothing.
 *
 * When the server data refreshes with a newer `row_version` (e.g. after a header edit), the
 * panel follows it, so its next change sends the current version instead of a stale one. */
export function Collaborators({ initial }: { initial: Opportunity }) {
  const announce = useAnnounce();
  const router = useRouter();
  const [opportunity, setOpportunity] = useState(initial);
  const [seen, setSeen] = useState(initial);
  if (seen !== initial) {
    // Adjusting state while rendering (React's pattern for following a prop).
    setSeen(initial);
    if (initial.row_version > opportunity.row_version) setOpportunity(initial);
  }
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pending, startTransition] = useTransition();
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<Found | null>(null);
  const searchId = useId();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reloadRef = useRef<HTMLButtonElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const stale = notice?.kind === "stale";
  const locked = pending || stale;
  const canManage = opportunity.can_manage_collaborators;

  // On 412 every change is locked: take focus to the one thing that can be done next.
  useEffect(() => {
    if (stale) reloadRef.current?.focus();
  }, [stale]);

  useEffect(() => {
    const q = query.trim();
    if (!canManage || codePointLength(q) < SEARCH_MIN) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      let result: Awaited<ReturnType<typeof searchUsers>>;
      try {
        result = await searchUsers(q);
      } catch {
        result = { kind: "error" };
      }
      if (cancelled) return;
      setFound({ q, users: result.kind === "ok" ? result.users : [], error: result.kind !== "ok" });
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query, canManage]);

  const memberIds = new Set([opportunity.owner.id, ...opportunity.collaborators.map((c) => c.id)]);
  // Only the answer for the current query counts: while a new query waits for its search,
  // the previous query's people (or error) are neither shown nor addable.
  const current = found !== null && found.q === query.trim() ? found : null;
  const searchError = current?.error ?? false;
  const candidates = current ? current.users.filter((user) => !memberIds.has(user.id)) : [];

  function fail(next: Notice, spoken: string) {
    setNotice(next);
    announce(spoken);
  }

  function change(userId: string, name: string, add: boolean) {
    if (locked) return;
    setNotice(null);
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof changeCollaborator>>;
      try {
        result = await changeCollaborator({
          opportunityId: opportunity.id,
          userId,
          add,
          rowVersion: opportunity.row_version,
        });
      } catch {
        result = { kind: "error" };
      }
      switch (result.kind) {
        case "ok":
          setOpportunity(result.opportunity);
          // The workspace header (in the persistent layout) lists collaborators too.
          router.refresh();
          announce(`${name} ${add ? "added as a collaborator" : "removed as a collaborator"}`);
          if (add) {
            setQuery("");
            setFound(null);
            searchRef.current?.focus();
          } else {
            headingRef.current?.focus();
          }
          return;
        case "stale":
          fail(
            { kind: "stale", changedBy: result.changedBy },
            staleMessage(result.changedBy),
          );
          return;
        case "invalid":
          fail({ kind: "message", text: result.detail }, result.detail);
          return;
        case "forbidden":
          fail({ kind: "message", text: NOT_OWNER }, NOT_OWNER);
          return;
        case "not-found":
          fail({ kind: "message", text: NO_ACCESS_TO_OPPORTUNITY }, NO_ACCESS_TO_OPPORTUNITY);
          return;
        default:
          fail({ kind: "message", text: SAVE_FAILED }, SAVE_FAILED);
      }
    });
  }

  function reload() {
    if (pending) return;
    startTransition(async () => {
      let result: Awaited<ReturnType<typeof loadOpportunity>>;
      try {
        result = await loadOpportunity(opportunity.id);
      } catch {
        result = { kind: "error" };
      }
      if (result.kind === "ok") {
        setNotice(null);
        setOpportunity(result.opportunity);
        headingRef.current?.focus();
        announce("Reloaded the Opportunity");
      } else if (result.kind === "not-found") {
        headingRef.current?.focus();
        fail({ kind: "message", text: NO_ACCESS_TO_OPPORTUNITY }, NO_ACCESS_TO_OPPORTUNITY);
      } else {
        // Keep the stale notice (and its Reload button); nothing was overwritten.
        announce(RELOAD_FAILED);
      }
    });
  }

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3" aria-busy={pending}>
      <h2 id={headingId} ref={headingRef} tabIndex={-1} className="text-section outline-none">
        People
      </h2>
      <ul className="flex flex-col">
        <li className="flex h-row items-center gap-2">
          <span className="text-body-strong">{opportunity.owner.name}</span>
          <span className="text-meta text-muted-foreground">Owner</span>
        </li>
        {opportunity.collaborators.map((collaborator) => (
          <li key={collaborator.id} className="flex h-row items-center justify-between gap-2">
            <span>
              <span className="text-body">{collaborator.name}</span>{" "}
              <span className="text-meta text-muted-foreground">Collaborator</span>
            </span>
            {canManage ? (
              <button
                type="button"
                aria-label={`Remove ${collaborator.name}`}
                aria-disabled={locked || undefined}
                onClick={() => change(collaborator.id, collaborator.name, false)}
                className={buttonClass}
              >
                Remove
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {opportunity.collaborators.length === 0 ? (
        <p className="text-meta text-muted-foreground">No collaborators yet.</p>
      ) : null}

      {canManage ? (
        <div className="flex flex-col gap-1">
          <label htmlFor={searchId} className="text-label">
            Add collaborator
          </label>
          <input
            id={searchId}
            ref={searchRef}
            type="search"
            value={query}
            autoComplete="off"
            placeholder="Search by name or email"
            aria-describedby={`${searchId}-status`}
            onChange={(event) => setQuery(event.target.value)}
            className="h-8 w-full max-w-sm rounded-md border border-input bg-transparent px-2 text-body outline-none focus-visible:ring-2 focus-visible:ring-primary"
          />
          <p id={`${searchId}-status`} className="text-meta text-muted-foreground">
            {searchError
              ? SEARCH_FAILED
              : current && candidates.length === 0
                ? "No matching people."
                : "People need a role to be added."}
          </p>
          {candidates.length > 0 ? (
            <ul aria-label="Matching people" className="flex max-w-sm flex-col">
              {candidates.map((user) => (
                <li key={user.id} className="flex h-row items-center justify-between gap-2">
                  <span className="min-w-0 truncate">
                    <span className="text-body">{user.name}</span>{" "}
                    <span className="text-meta text-muted-foreground">{user.email}</span>
                  </span>
                  <button
                    type="button"
                    aria-label={`Add ${user.name}`}
                    aria-disabled={locked || undefined}
                    onClick={() => change(user.id, user.name, true)}
                    className={buttonClass}
                  >
                    Add
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {/* Screen readers hear these through the shell's single live region. */}
      {notice?.kind === "stale" ? (
        <div className="flex max-w-sm items-center justify-between gap-2 rounded-md border border-border p-2">
          <p className="text-meta">{staleMessage(notice.changedBy)}</p>
          <button
            type="button"
            ref={reloadRef}
            onClick={reload}
            aria-disabled={pending || undefined}
            className={buttonClass}
          >
            Reload
          </button>
        </div>
      ) : null}
      {notice?.kind === "message" ? (
        <p className="text-meta text-destructive">{notice.text}</p>
      ) : null}
    </section>
  );
}
