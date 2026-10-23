---
title: 'Story 17.2c: Offline strip, read-only below 1024px, shell axe'
type: 'feature'
created: '2026-10-22'
status: 'done'
baseline_commit: '993930991f7c4e655b0b5eb1cb92892d4a86b762'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-17-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-2b-shell-chrome.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After 60 s without the event stream the workspace only shows "Offline — edits disabled" in a small bottom bar, with no way to retry. Below 1024px the read-only notice shows but nothing disables editing. Axe is not run on the shell in the offline and narrow states (Story 17.2, UX-DR20, UX-DR26, NFR-7, NFR-8).

**Approach:** Add a shell-level Offline strip with **Retry**, fed by the workspace's stream status. Disable editing below 1024px the way offline already does. Cover both states with axe.

## Boundaries & Constraints

**Always:** The strip appears at the top of the main pane only when the stream status is `offline` (down 60 s, `OFFLINE_AFTER_MS`); it says "Offline — edits disabled", has a **Retry** button, and is a polite live region that stays mounted. **Retry** reopens the Opportunity's event stream at once (reset the backoff, keep `lastEventId`) and the strip goes when the stream opens. The workspace bottom bar keeps only "Reconnecting…"; the Offline text moves to the strip. Editing stays disabled while offline through the existing `<fieldset disabled>`. Below 1024px the same fieldset is disabled (viewport read through `matchMedia`, server render treats it as wide) so inputs and buttons in the workspace do not work; the notice stays. Tiers ≥1440, 1280–1439, 1024–1279 are unchanged. Type classes outside `cn()`; reuse `ui/button`.

**Never:** Add a stream outside the Opportunity workspace, change `OFFLINE_AFTER_MS` or reconnect delays, touch Settings, preferences or 17.2b chrome, disable editing on Knowledge or Admin pages, or add toasts.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Stream drops | Down under 60 s | Bottom bar "Reconnecting…"; no strip; editing enabled | N/A |
| Offline | Down 60 s | Strip with Retry; editing disabled; announced politely | N/A |
| Retry | Click Retry while offline | Stream reopens at once; strip goes on open; focus returns to main | Still down: strip stays |
| Leave workspace | Navigate to another page while offline | Strip goes (no stream) | N/A |
| Narrow | Viewport <1024px | Notice shows; workspace fieldset disabled | N/A |
| Wide again | Resize to ≥1024px | Fieldset enabled (unless offline) | N/A |

</frozen-after-approval>

## Code Map

- `web/src/lib/opportunity-events.ts` -- `subscribe`/`open`/`markDown`, `sharedConnections`, `useEventStreamStatus`; add exported `retryEventStream(opportunityId)` that closes a down source, clears the reopen timer, resets `attempt`, and calls `open`.
- `web/src/components/opportunities/workspace-tabs.tsx` -- `offline` flag and `<fieldset disabled>` at lines ~83 and ~176; publish stream status to the shell, add the narrow-viewport condition to `disabled`.
- `web/src/components/opportunities/connection-status.tsx` -- `connectionMessage`; drop the offline branch (strip owns it).
- `web/src/components/shell/shell-context.tsx` -- add `streamStatus`, `setStreamStatus`, and a retry callback registration (cleared on workspace unmount).
- `web/src/components/shell/read-only-notice.tsx`, `app-shell.tsx` -- strip renders beside the notice; add a `useNarrowViewport` hook (new, `useSyncExternalStore` over `matchMedia("(max-width: 1023.98px)")`).
- New: `components/shell/offline-strip.tsx` (+ test). Tests: `workspace-tabs.test.tsx`, `connection-status` test, `opportunity-events.test.tsx`, `app-shell.test.tsx`.

## Tasks & Acceptance

**Execution:**
- [ ] `lib/opportunity-events.ts` + test -- `retryEventStream`
- [ ] `shell-context.tsx`, `workspace-tabs.tsx`, `connection-status.tsx` + tests -- publish status, narrow disable, drop Offline text from the bar
- [ ] `offline-strip.tsx`, `app-shell.tsx` + test -- strip with Retry and live region
- [ ] `use-narrow-viewport` hook + test -- matchMedia subscribe, SSR false
- [ ] Tests -- matrix rows; axe on the shell with the strip and the notice, light and dark

**Acceptance Criteria:**
- Given an Opportunity workspace whose stream has been down 60 s, when it renders, then the strip shows Retry, editing is disabled and axe is clean in light and dark.
- Given a viewport below 1024px, when the workspace renders, then its controls are disabled and the notice shows.
- Given lint, typecheck, build and tests, when run, then all pass.

## Implementation Notes

- The strip is a `div` with `aria-live="polite"` (no `role="status"`, so existing `getByRole("status")` tests stay unambiguous); the shell now has two polite regions.
- Retry moves focus to `<main>` at once; the strip goes when the stream opens.
- `usePublishStreamState` publishes the status and retry while a workspace is mounted and resets on unmount.
- Axe in jsdom does not compute the design tokens, so dark mode toggles only the `dark` class and is not a real contrast check.

## Spec Change Log

## Review Triage Log

| # | Source | Finding | Verdict | Evidence | Route |
|---|--------|---------|---------|----------|-------|
| 1 | Gap | Fieldset labels (narrow, offline) not asserted | medium | Verified: no test read either `aria-label`. Added group-name assertions in both tests. | patch |
| 2 | Edge, Blind | `retryEventStream` reopens a healthy stream (comment says "down") | low | Race only (stream opens between render and click), but the guard is one line. Added `status === "open"` guard and a test. | patch |
| 3 | Edge | No axe on AppShell with strip and notice, light and dark | medium | Verified: axe ran only on the strip alone. Added an AppShell test in both themes. | patch |
| 4 | Edge | Strip not topmost (first-run hint above it) | low | The hint shows only on first run; strip placement is now asserted inside AppShell. | rejected |
| 5 | Blind, Edge | Stale unmount wipes a new workspace's published state | false | React runs a replaced component's cleanup before the new one's effects in the same commit; the id change keeps one instance. | rejected |
| 6 | Blind, Edge | Retry gives no feedback and moves focus off the button | low | Focus to main and "strip stays if still down" are the spec's matrix rows. | rejected |
| 7 | Blind | Button inside the live region is announced with the text | low | Harmless; message is first. | rejected |
| 8 | Blind, Edge | Read-only covers only the workspace fieldset (right pane, ARIA widgets, other pages) | maybe-false | Spec Never limits it to the workspace; whether pane inspectors have editable inputs reachable while narrow or offline is unchecked. Would be medium. | defer |
| 9 | Edge, Blind | Hydration flash: narrow client renders enabled before the snapshot flips | low | Spec says the server treats the viewport as wide; the window is one commit. | rejected |
| 10 | Edge | `addListener` fallback for old browsers | false | `addEventListener` on MediaQueryList is supported by every browser the app targets. | rejected |
| 11 | Blind, Edge | Extra re-renders from the publish effect | low | One state update per status change. | rejected |
| 12 | Blind | Live-region count asserted as 2 in three tests; narrow boundary test; narrow plus offline label | low | Style and coverage nits. | rejected |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.
