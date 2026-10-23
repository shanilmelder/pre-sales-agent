---
title: 'One Opportunities nav item; All / Mine / Due as views on it'
type: 'feature'
created: '2026-10-23'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The sidebar has two entries, "My Opportunities" and "All Opportunities", even though the Opportunities list already has All / Mine / Due in 14 days view tabs at the top. The user wants one nav entry.

**Approach:** Keep a single sidebar item labelled "Opportunities" (`/opportunities`). The Mine view moves onto `/opportunities?view=mine` (same `scope=mine` API call, no filter bar, as today). The page title is "Opportunities" for every view. `/my-opportunities` redirects to `/opportunities?view=mine` so old links keep working, and presales engineers land on `/opportunities?view=mine`.

</frozen-after-approval>

## Implementation Notes

- Decisions (not user-visible beyond the above): nav `g` shortcut becomes `g o` (was `g a` for All; `g m` for My Opportunities is dropped). `NavItem.id` loses `"my-opportunities"`.
- Files: `web/src/lib/navigation.ts`, `web/src/app/opportunities/page.tsx`, `web/src/app/opportunities/list-page.tsx`, `web/src/app/my-opportunities/page.tsx`, `web/src/components/opportunities/opportunity-views.tsx`, plus their tests (`pages.test.tsx`, `page.test.tsx`, `opportunity-views.test.tsx`, `navigation.test.ts`, `app-shell.test.tsx`).
- Stale "All Opportunities" comments in `filters.ts`, `filter-bar.tsx` and `lib/opportunities.ts` were renamed, along with the workspace breadcrumb label.
- Surprise: a first pass ran Prettier without the repo config and rewrapped whole files to 80 columns. The files were restored and only the intended edits were reapplied.

## Review Triage Log

- Screen reader does not announce All↔Mine (announcer only watches pathname): low. All↔Due already behaved this way; the fix needs `useSearchParams` plus Suspense in the shell. Rejected.
- Same document title and caption on every view: low. This is the decided design (one "Opportunities" page). Rejected.
- `/my-opportunities` redirect drops `?page`, and it is a 307: low. Rare legacy bookmark. Rejected.
- No `g`/palette route to Mine: low. One nav item was the explicit intent. Rejected.
- Sidebar goes to All while presales engineers land on Mine: false. This is by design; the views at the top switch.
- Breadcrumb forgets the view: low. It already dropped Due filters before this change. Rejected.
- `view=due` is ignored and Due is inferred from filters: low. Unchanged behaviour. Rejected.
- Mine href built by string concatenation: low. Correct and covered by tests. Rejected.
- Mine empty state says "No Opportunities yet": low. The old My Opportunities page showed the same text. Rejected.
- Stale "All Opportunities" comments: low, trivial. Patched.
- Diff reformatted to 80 columns: high. Patched (reverted and reapplied without the formatter).
- Missing tests for the new routing: medium. Patched in part: added tests for the redirect and the Mine pagination hrefs. g o / g m already covered by the updated g-key tests.
