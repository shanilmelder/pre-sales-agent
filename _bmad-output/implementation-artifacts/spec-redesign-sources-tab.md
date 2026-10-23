---
title: 'Redesign the Sources tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: 'c4cd95f8c65501fae00258a982ab48108f0b0193'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-17-3a-sources-requirements-gaps-refit.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Sources tab does not match the new mockup (`_bmad-output/planning-artifacts/ux-designs/ux-pre-sales-agent-2026-10-01/new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Sources). It has a narrow, centred drop zone with small outline buttons, an upload log underneath, and a dense six-column table with headers.

**Approach:** Rebuild the tab to the mockup's structure: dismissible rejection alerts, a full-width drop zone card, and one "Sources" card with three-column rows and no column headers. Restyle the right-pane inspector to match. Use only data the API returns today. Upload, paste, retry, polling, SSE, selection and the inspector keep their behaviour.

## Boundaries & Constraints

**Always:**
- **Rejection alert:** when an upload or paste is rejected, a red-tint `role="alert"` banner appears above the drop zone. It has an alert icon, a bold "Upload rejected: {name}", the API's reason below it in body text, and an X button labelled "Dismiss". There is one banner per rejected item, newest first. Uploading and Added rows stay as a quiet list under the drop zone, so the user still sees progress.
- **Drop zone:** full width, dashed `border-2` border, `rounded-xl`, card surface, padding 32, laid out as a row (stacked below `md`). On the left, a 48px indigo icon tile with an upload icon. Then the title "Drop emails, transcripts or documents here" (section type) and the subtitle ".eml, .msg, .txt, .docx, .pdf, .vtt or text, up to 50 MB each. Sources are stored unchanged and versioned." On the right, **Choose files** (primary) and **Paste text** (outline), using `ui/button`. Drag-over keeps a primary border and muted fill. The paste area opens below the drop zone, unchanged in behaviour.
- **Sources card** (`Card`): a header with `h2` "Sources" and a muted count, and on the right a summary such as "4 parsed · 1 parsing · 1 failed". Queued counts as its own term, and terms with a zero count are left out. Each row is a grid `minmax(0,1fr) 200px 120px` with a top border and no column headers, collapsing to one column below `md`.
  - **Column 1:** a 36px muted tile with the kind icon (transcript uses a mic icon). Next to it, the file name as the row's open button (medium weight, wraps anywhere), and a meta line "{Kind} · v{n} of {count} · {size}".
  - **Column 2:** `ParseStatusPill`. A parsing row adds a 6px indeterminate indigo bar (the Assessments sweep, still under reduced motion) and the caption "Extracting text". A failed row adds the reason, **Retry** (as today, hidden for `not_supported`) and **Paste text instead**, both small outline buttons and only for `canAdd`.
  - **Column 3:** the uploader's name, with the date and time below it in meta type.
  - A selected row gets a primary-tint background. The whole row is clickable through the open button's stretched hit area, which keeps one Tab stop per row.
- **Inspector:** the name in section type, the pill, and a key–value grid with a fixed 90px label column (Kind, Version, Size, Added by, Added). **Download original** is an outline button with an icon. "Extracted text" is an uppercase meta label, and the text sits in a bordered box on the page background.
- The empty state keeps `EmptyTabCard` and its copy. Existing tokens and `ui/*` primitives only. Light and dark themes both work.

**Never:** Show data the API lacks: a parse percentage, passage highlights, "cited by" Requirements, or a tab count. Do not add the Reconnecting banner. Do not change API calls, SSE, polling, the upload queue or retry logic. Do not touch other tabs, the shell, tokens or `ui/*`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mixed list | 4 parsed, 1 parsing, 1 failed | Header "Sources 6", "4 parsed · 1 parsing · 1 failed"; the parsing row shows the bar and "Extracting text" | N/A |
| Rejected upload | API rejects `x.mp4` | Alert "Upload rejected: x.mp4" with the reason; Dismiss removes it | N/A |
| Failed parse, viewer | `canAdd` false | Reason only, no buttons | N/A |
| Not supported | `error_code` `not_supported` | Paste text instead only | N/A |
| Empty, viewer | No Sources, `canAdd` false | No drop zone; empty card with no button | N/A |
| New version | Same bytes added again | Meta line reads "v2 of 2"; the upload row says "Added as version 2" | N/A |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/sources-list.tsx` -- `SourcesList` (table, ~124-265) becomes the header card plus grid rows. `KIND_ICONS` changes transcript to `MicIcon`. `ParseStatusPill` stays as is (the inspector reuses it). `SourcesSection` keeps all state; only its layout wrapper changes.
- `components/opportunities/source-upload.tsx` -- restyle the drop zone and its buttons to `ui/button`. Rows in the `rejected` state render as dismissible alerts above the zone; other rows render below it. Keep `SourceUploadHandle`, the queue, paste keys and focus return.
- `components/opportunities/source-inspector.tsx` -- restyle only.
- `lib/sources.ts` -- add `sourceMeta(source)` (uses `formatSize` from `lib/knowledge-sources.ts`) and `parseSummary(sources)`. The drop-zone hint copy lives here or in the upload component.
- Reuse the sweep from `specialist-assessments.tsx:551` (`animate-in … slide-in-from-left-full repeat-infinite motion-reduce:animate-none`).
- Tests: `sources-list.test.tsx`, `source-upload.test.tsx`, `source-inspector.test.tsx`, `app/opportunities/pages.test.tsx`. Update selectors that relied on table headers or cells.

## Tasks & Acceptance

**Execution:**
- [x] `lib/sources.ts` + test -- `sourceMeta`, `parseSummary`
- [x] `source-upload.tsx` + tests -- drop zone card, rejection alerts with Dismiss, progress rows
- [x] `sources-list.tsx` + tests -- header card, grid rows, parsing bar, failed actions, selection
- [x] `source-inspector.tsx` + tests -- restyle
- [x] Matrix tests -- each row above

**Acceptance Criteria:**
- Given an Opportunity with Sources, when the tab renders at 1440px, then it shows the drop zone and Sources card in the mockup's order and styling, in light and dark.
- Given a row, when it is clicked anywhere or its name is activated with Enter, then the inspector opens as today and keyboard focus returns to the row when the pane closes.
- Given lint, typecheck, tests and build, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Two level-2 "Sources" headings in the tab panel (blind, verification, edge) | low | patch | `sources.tsx:20` sr-only `h2` plus the card's `h2`; `pages.test.tsx` asserts both. |
| Rejection announced twice: `announce()` plus `role="alert"` (blind, edge, verification) | low | patch | `settle()` announces every outcome; the alert is now inserted as well. |
| Every Dismiss button is named "Dismiss" (blind, edge) | low | patch | `aria-label={DISMISS}` only; row actions elsewhere include the file name. |
| No test of focus returning to the row when the pane closes (verification) | low | patch | Pre-verified: no test closes the pane on the Sources tab; the spec AC names it. |
| `SourcesCard` only forwards props; unused `data-testid="sources-card"` and `data-source-row-item` (blind, edge) | low | patch | No reader of either attribute; the wrapper adds a duplicate prop type. |
| Alert uses `break-all`; the rest of the diff uses `overflow-wrap:anywhere` (blind) | low | patch | `source-upload.tsx` alert lead line. |
| ParsingBar comment says "at 40%" but the reduced-motion bar is full width at 40% opacity (blind) | low | patch | The classes match the spec ("still"); the comment is wrong. |
| Download link classes joined without `cn` (blind) | false | rejected | `button.tsx:49` keeps type classes outside `cn()` by design; `buttonVariants` emits no text class to collide with `text-control`. |
| Stretched hit area blocks text selection (blind) | false | rejected | The frozen spec requires the whole row to be clickable through the open button. |
| Drop hint duplicates limits and drops "notes" (blind) | false | rejected | The copy is verbatim from the frozen spec. |
| "Paste text" hard-coded `h-[38px]` (blind) | low | rejected | Cosmetic drift risk only; no current mismatch. |
| Class-name and lucide-class assertions in tests (blind) | low | rejected | Same pattern as the Assessments redesign; no demonstrated harm. |
| No mouse-dismiss test; no dismiss-all; empty summary span; parse-null count mismatch (blind, edge) | low | rejected | Rare or spec-defined behaviour; fixes add branches. |
| Keyboard Dismiss skips remaining alerts to Choose files (edge) | low | rejected | Rare; the fix adds focus-management branches. |
| Removed "newest first" caption (edge) | low | rejected | Order is still visible; low confidence harm. |
| axe can't check new colour contrast in jsdom (blind) | low | rejected | Existing tokens already used together elsewhere; checked by the manual screenshot pass. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab in light and dark at 1440px and compare it with the mockup.
