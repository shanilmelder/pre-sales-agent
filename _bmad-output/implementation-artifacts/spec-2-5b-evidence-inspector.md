---
title: 'Story 2.5 (Part B): Evidence inspector'
type: 'feature'
created: '2026-10-04'
status: 'done'
baseline_commit: 'acf56505d8ad1221aa93e5127316eaea95c7247b'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-2-5a-extract-requirements.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** After Part A, a Requirement shows which Source it came from, but not what the customer actually said. The presales engineer can't check a Requirement against its evidence without opening the file and searching it. That breaks the "every Requirement is traceable" promise (FR-5, UX-DR7, UX-DR11).

**Approach:** Add a passage API, and turn the Requirements tab into a list plus inspector, following the Users & roles pattern. Selecting a Requirement opens it in the right pane. Clicking one of its Evidence chips shows the cited passage, highlighted, in its surrounding text.

## Boundaries & Constraints

**Always:**
- **Depends on Story 2.5 Part A:** `intake_source_passages`, `intake_requirement_evidence`, the requirements list API and its `evidence` items. The extracted text comes from Story 2.2 Part B.
- **Passage API:** `GET /api/v1/opportunities/{id}/passages/{passage_id}`, open to anyone who can read the Opportunity. It returns `{passage_id, source_id, source_version, filename, label, before, text, after}`.
  - `text` is the cited span exactly, sliced by code points from the stored extracted text.
  - `before` and `after` hold up to 300 code points each. They are cut back to the nearest whitespace so no word is split, with `…` added when the context was truncated.
  - A passage of another Opportunity, or an unknown id, gives the Opportunity's 404. Non-readers also get 404.
- **List and keyboard:** the Requirements list becomes keyboard-navigable like `users-table.tsx`.
  - One tab stop. `j`/`k` (when single-key shortcuts are on) or the arrow keys move between rows.
  - Enter or Space opens the row in the inspector; a click does the same.
  - The selected row is marked `aria-selected`.
- **Inspector** (in the right pane via `RightPaneContent`, opening the pane if it's closed):
  - Shows the Requirement text, its classification label, origin `Extracted`, and its Evidence chips in citation order.
  - The first chip's passage is shown by default.
  - Selecting a chip shows that passage: the filename and `v{n}` above it, then `before`, the span in a `<mark>` with the evidence token colour, then `after`, in body text with whitespace and line breaks preserved.
  - Chips are buttons with `aria-pressed` for the one shown.
- **Chips in the list:** clicking a chip in a list row opens that Requirement with that chip's passage shown.
- **Loading and errors:** "Loading passage…" while the request is in flight. "The passage couldn't be loaded." with **Retry** on failure. A 404 says "This passage is no longer available."
- **Focus:** opening with the keyboard moves focus into the inspector's first chip. Closing the pane returns focus to the row, the same as `users-admin.tsx`.
- **Polling:** when Part A's poll replaces the list and the selected Requirement is gone (superseded by a re-run), the inspector closes its content and shows "Nothing selected."
- **Privacy:** the passage endpoint logs ids only.

**Never:** No editing from the inspector (that's Story 2.6). No source viewer showing the whole file, and no download (Story 2.3). No new right-pane mechanics: reuse the shell's container. No caching layer beyond React state.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Passage | Passage at offsets [120, 160) in a 1,000-character text | `text` = exactly that span; `before` ≤ 300, `after` ≤ 300, cut at whitespace, with `…` | N/A |
| Edges | Passage at offset 0, or ending at the last character | Empty `before` or `after`, with no `…` | N/A |
| Non-BMP | Emoji before the span | Code-point slicing; `text` matches the quote | N/A |
| Other Opp | A passage id from another Opportunity | 404 | N/A |
| Non-reader | A user who can't read the Opportunity | 404 | N/A |
| Open row | Enter on a focused row | Pane opens; inspector shows the Requirement and the first passage highlighted; focus on the first chip | N/A |
| Switch chip | Click the second chip | Second passage shown; `aria-pressed` moves | N/A |
| List chip | Click a chip inside a row | That Requirement opens with that passage | N/A |
| Fail | Passage request fails | Error line plus Retry; Retry refetches | N/A |
| Superseded | Poll removes the selected Requirement | Inspector shows "Nothing selected." | N/A |
| Close | Esc or Close after a keyboard open | Focus returns to the row | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/intake/` -- add `application/passages.py` (query: read access through `opportunities.readable_resource`, load the passage row plus the extracted text through Story 2.2 Part B's `extracted_text`, slice by code points, trim the context), the pure `domain` helper `context_window(text, start, end, width=300)`, the route in `api/` next to the requirements routes, and a repository read.
- `web/src/components/admin/users-admin.tsx` and `users-table.tsx` -- the reference pattern for the list plus inspector: `RightPaneContent`, `useShell`, focus return, `j`/`k`/arrows, the tab stop.
- `web/src/components/shell/{right-pane.tsx,shell-context.tsx}` -- reuse as they are.
- `web/src/app/opportunities/[id]/requirements.tsx` and the Part A components -- add selection state, the inspector component, and an `getPassage` server action (or data function) following `actions.ts`.
- `web/src/app/globals.css` (or the token file) -- use the existing evidence or semantic token for `<mark>`. Don't add a new colour if one exists.
- Tests -- domain tests for `context_window` (edges, whitespace cut, non-BMP), an API test against Postgres (span, 404 cases), and web component tests with axe (open, chips, errors, superseded, focus return).

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/intake/**` -- `context_window`, the passage query and the route
- [x] `backend/tests/test_intake_passages.py` plus domain tests -- the matrix's API rows
- [x] `web/src/lib/api/schema.d.ts` (from local uvicorn), the passage action, the Requirements list keyboard support, `requirement-inspector.tsx` and tests -- the matrix's UI rows, axe

**Acceptance Criteria:**
- Given the demo Opportunity with extracted Requirements, when the presales engineer presses Enter on a Requirement and clicks each of its chips, then each passage shows the highlighted quote in context, and that quote supports the Requirement.
- Given CI, when it runs, then the backend and web checks pass.

## Implementation Notes

- **Context width includes the ellipsis.** `context_window` keeps each side at most 300 code points *with* the `…`, so a cut side holds at most 299 characters of text. A side that reaches the start or end of the text is returned whole, with no `…`. Only the outer, cut edge is trimmed; whitespace next to the span is kept. If the whole window is one word longer than the window, that side is just `…`.
- **Unreadable text gives 404.** A passage whose extracted text is missing from the store, or shorter than its offsets, gets the Opportunity's 404 (the UI shows "This passage is no longer available."). This is logged with ids only.
- **`aria-selected` needs a role that allows it.** Each classification group is a one-column `role="grid"`. Its rows are `role="row"` with `aria-selected`, and each row has one `gridcell` holding the row button and the chips. A `<button>` or `<li>` can't carry `aria-selected` and pass axe. There is still one Tab stop for the whole list: list chips are `tabIndex=-1`, and keyboard users reach chips through the inspector.
- **Highlight token.** DESIGN.md has no evidence-highlight colour (the UX review rubric flagged this gap). `--evidence-highlight` / `bg-evidence-highlight` is an alias of the existing `--diff-tint` in light and dark, so no new colour was added. `<mark>` also gets a primary underline so it stays visible on the inspector surface.
- **Focus on a keyboard open** goes to the chip being shown. That is the first chip for a row open, or the chip that was activated for a chip open.

## Spec Change Log

## Review Triage Log

| # | Finding (layer) | Verdict | Evidence | Route |
|---|---|---|---|---|
| 1 | Bad stored span (`start>=end`, `start<0`) → 500 (blind) | false | `intake_source_passages` has `CHECK start >= 0 AND "end" > start`; only `end > len(text)` can occur and it is guarded | reject |
| 2 | `context_window` drops the whitespace next to the span when the window is one long word (blind, edge ×3) | low | `"x"*500+" SPAN "` gives `before == "…"`, contradicting the docstring; test locks it in. Direct one-expression fix | patch |
| 3 | No hard-cut fallback for text without whitespace (CJK, URLs) (blind) | low | Real but needs 299 code points with no whitespace; demo data is English. Fix adds a branch | reject |
| 4 | Missing S-number becomes `S0` (blind) | false | `source_numbers` covers every Source of the Opportunity and Sources are never removed; the join guarantees membership | reject |
| 5 | No caching of passages / full text re-read per click (blind) | low | Real cost but the intent excludes caching beyond React state; transcripts are small | reject |
| 6 | Unreadable-text 404 path untested (blind, verification-gap) | medium | Gap pre-verified: no test reaches the `text is None` / `end > len` branch | patch |
| 7 | `passage_unreadable` log doesn't separate causes or carry source ids (blind) | low | Cosmetic for operators; not everyday | reject |
| 8 | Several `role="grid"` and chips not keyboard-reachable in the list (blind, edge) | low | Chips are reachable in the inspector, which is the spec's path; reworking the grid model is not a direct fix | reject |
| 9 | `originLabel` non-exhaustive (blind) | low | Enum is two values; would only matter if it grows | reject |
| 10 | Evidence highlight shares the pressed-chip tint; redundant dark alias (blind) | low | Cosmetic; intentional reuse noted in Implementation Notes | reject |
| 11 | Superseded selection not cleared; close then focuses body (blind) | low | Real but needs a re-run while the pane is open, then a keyboard close; rare | reject |
| 12 | Error uses `role="status"`, loading inside `aria-busy` (blind) | low | Polite announcement still reaches AT; not a defect users meet | reject |
| 13 | `extracted_text` OSError/bad UTF-8 → 500 (edge) | low | Pre-existing in `texts.py` (Story 2.2 Part B), not caused here | reject |
| 14 | Reopening the pane replays `focusRequest` and steals focus (edge) | low | The pane unmounts the portal target on close, so the inspector remounts with `focusRequest > 0` and focuses a chip. One-line reset | patch |
| 15 | Row stays `aria-selected` with the pane closed (edge) | false | Same behaviour as the reference `users-admin.tsx` the spec says to follow | reject |
| 16 | Arrow key with no row buttons blocks scroll (edge) | false | The list only renders with items; every focusable target is inside a row | reject |
| 17 | AT click with `detail 0` treated as keyboard (edge) | false | Moving focus into the pane is the desired outcome for AT activation | reject |
| 18 | Passage from an older Source version untested (verification-gap) | medium | Gap pre-verified: every test uses one version | patch |
| 19 | `S<n>` label only tested with one Source (verification-gap) | medium | Gap pre-verified | patch |
| 20 | j/k with single-key shortcuts off untested (verification-gap) | medium | Gap pre-verified; siblings test the off case | patch |
| 21 | Out-of-order passage replies untested (verification-gap) | medium | Gap pre-verified | patch |
| 22 | Poll test has little timeout headroom (verification-gap other) | low | Seen flaking during verification; trivial `timeout` bump | patch |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
