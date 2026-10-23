---
title: 'Redesign the Trace tab to match the new mockups'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '8d1443233b2290e575b4eb285a1fec12021caa46'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/spec-9-8-decision-trace.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-overview-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Trace tab (Story 9.8) does not match the new mockup (`new-mockups/Presales Agent Design Spec (standalone).html`, Opportunity → Trace and its inspector pane). It shows labelled native selects above a plain row list, and the inspector is a flat label/value list.

**Approach:** Restyle the tab to the mockup: a title row with dashed filter chips, one card of 4-column event rows with actor initials tiles, an append-only footnote, and a sectioned inspector. Same API read, same URL state, same keyboard model; frontend only.

## Boundaries & Constraints

**Always:**
- **Title row:** a visible `h2` "Trace" (16px semibold, flex-1) with the Subject, Actor and Event filters on the right as dashed chips with a chevron, each opening its existing select (same options, same "Any …" choice) in a popover. An applied filter reads "Label: value" in the primary tint; "Clear filters" follows when any is applied. URL behaviour is unchanged (replace, page 1). Shown only when there are events or a filter is applied, as now.
- **Event rows:** one `ui/card` (12px radius, shadow, overflow hidden). Each row is a 4-column grid `130px 190px minmax(0,1fr) 190px`, 16px gap, 13px text, row padding `rowpad + 2px` and 20px sides, border between rows: time (secondary, relative with absolute on hover), actor (22px initials tile + name), event label (medium weight), subject link (right-aligned, 12px medium, primary text). The selected row has the primary tint background. Below `md`, the grid collapses so nothing scrolls horizontally (time and actor stack above the event; subject on its own line).
- **Actor tile:** same as the Overview's Recent activity — rounded square, primary tint for agents and system; circle, green tint for people; `actorInitials`. Extract it into one shared component used by both.
- **Footnote:** "Trace rows are append-only and cannot be edited." (12px, secondary) under the card, shown whenever rows are shown. Pagination keeps its current behaviour, restyled with `ui/button` outline links.
- **Inspector** (right pane), sections divided by borders, 20px padding: header — eyebrow "Trace event · {absolute time}", the event label as the 16px-semibold focusable heading, then the actor tile, name (agent version as now) and "· {Agent|Person|System}", and the existing "Open in {tab}" outline link. **Payload** — eyebrow heading, a `120px 1fr` grid: Event, Actor, Subject ("{label} v{n}"), Subject id, then each payload field with `fieldLabel`/`fieldValue`, wrapping long values. **Change** (only for `estimates.estimate_line.edited`) — a red-tint "−" row with the before hours and role mix and a green-tint "+" row with the after values, each sign also as text for screen readers. Footer line: "Trace rows are append-only. Model reasoning is not stored, only decisions and Evidence."
- Empty, no-matches and failed-read states keep their text; keyboard (roving tabindex, j/k, arrows, Enter/Space opens and focuses the heading, focus returns on close) is unchanged. Tokens, `ui/*` and light/dark both work; every colour cue also has text.

**Never:** Show what the API lacks: Evidence chips, model name, correlation id, "Authorised by", or a version comparison for any other event. Add an API call, backend change, polling or live updates. Change the event/subject catalogues, the URL format, other tabs, the shell, or `ui/*` primitives.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Mixed actors | Agent, person and system events | Agent/system square primary tiles, person green circle; names shown | N/A |
| Filter applied | `?actor=agent` | Actor chip reads "Actor: Agent" tinted; Clear filters shown | N/A |
| No matches | Filter with 0 results | No card or footnote; "No events match these filters." + Clear filters | N/A |
| Line edited | `estimate_line.edited` selected | Inspector shows Change with − before / + after hours and role mix | N/A |
| Other event | Any other event selected | No Change section | N/A |
| Subject without tab | `knowledge.checklist` | Subject as plain secondary text; no Open link | N/A |
| Read fails | Trace read null | "The Decision Trace could not be loaded…" | Message |

</frozen-after-approval>

## Code Map

All under `web/src/`.
- `components/opportunities/trace-list.tsx` -- `TraceList` (row grid, keep roving tabindex/`data-trace-row`/`data-trace-id`/`role=grid`), `TraceInspector` (rebuild into sections; keep `focusRequest` heading focus), `TraceFilterBar` (swap labelled selects for chips; keep `withCurrent`, `navigate`, `useTransition`, `aria-busy`), `TracePagination`, `TraceSection` (title row, footnote).
- `components/opportunities/filter-bar.tsx:~271` -- private `FilterChip` (dashed popover chip, "Label: value" tint) and the Clear filters link styling; export `FilterChip` and reuse it, no behaviour change for the Opportunities list.
- `components/opportunities/overview-summary.tsx:~591` -- `RecentActivity`'s inline initials tile; replace with the shared tile.
- New `components/opportunities/actor-tile.tsx` -- `ActorTile({ actor, size })`, `aria-hidden`, `data-actor-type`.
- `app/opportunities/[id]/trace.tsx` -- drop the `sr-only` h2 (the title row renders it); otherwise unchanged.
- `lib/trace.ts` (+ `lib/trace.test.ts`) -- add `lineEditChange(event)` returning `{before, after}` labels (e.g. "12.0 h · Engineer 70% · PM 20% · QA 10%") or null; reuse `actorTypeLabel`, `actorText`, `subjectText`, `fieldLabel`, `fieldValue`, `absoluteTime`, `relativeTime`. Use `hours` from `lib/estimates.ts` if it fits.
- `lib/overview.ts` -- `actorInitials` stays; import it from the tile.
- Tests: `components/opportunities/trace-list.test.tsx` (selectors on labels/selects change to chips), `app/opportunities/pages.test.tsx:~1977` (Trace block; heading now visible), overview activity tests (`data-actor-type` must survive).

## Tasks & Acceptance

**Execution:**
- [x] `lib/trace.ts` + test -- `lineEditChange` and its edge cases (missing/odd payload → null)
- [x] `components/opportunities/actor-tile.tsx`, `overview-summary.tsx` -- shared tile; Overview unchanged visually
- [x] `components/opportunities/filter-bar.tsx` -- export `FilterChip`
- [x] `components/opportunities/trace-list.tsx`, `app/opportunities/[id]/trace.tsx` -- the redesign
- [x] `trace-list.test.tsx`, `pages.test.tsx` -- update and add a test per matrix row

**Acceptance Criteria:**
- Given seeded trace events, when the tab renders at 1440px in light and dark, then it matches the mockup's layout; at 390px nothing scrolls horizontally.
- Given a row, when activated by keyboard, then the inspector opens with its heading focused, and closing returns focus to the row.
- Given lint, typecheck, tests and build in `web/`, when run, then all pass.

## Implementation Notes

- `ActorTile` takes `size` 22 (Trace rows and inspector, 10px semibold initials) or 24 (Overview, unchanged). It carries `data-actor-type`; the Overview `li` keeps its own `data-actor-type` too, and each Trace row has one.
- `filter-bar.tsx` also exports `clearFiltersClass` so the Trace "Clear filters" link matches the Opportunities one; the Opportunities bar uses it unchanged.
- Row padding "rowpad + 2px" is `calc((var(--row-height) - 32px) / 2 + 2px)`, since `--row-height` is 32px plus twice the density's row padding. The row's button and subject cell sit in a CSS subgrid from `md` up, so the 4 columns line up while the button stays one Tab stop.
- The Payload's Event row shows the raw `event_type` (the heading already shows it in words).
- The failed-read state keeps a visible "Trace" `h2` in `trace.tsx`, since the sr-only one is gone and `TraceSection` doesn't render there.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| `lineEditChange` duplicates role keys instead of `ROLES`/`roleMixLabel` (blind) | medium | patch | `lib/estimates.ts:34` `ROLES` and `:60` `roleMixLabel` already exist; a new role there would null the Change section. |
| Payload shows role mixes as raw JSON above the formatted Change (blind) | low | patch | `fieldValue` JSON-stringifies objects; line-edit payload carries `before_role_mix`/`after_role_mix`. |
| Subgrid column gap 12px not 16px; side padding inside the 130/190px tracks (blind) | low | patch | Button sets `gap-x-3` on an `md:grid-cols-subgrid`, overriding the parent `gap-x-4`; `pl-5`/`pr-5` sit in edge tracks. |
| Duplicate React keys when a payload field's label equals Event/Actor/Subject/Subject id (blind, edge) | false | rejected | No catalogued payload has an `event`, `actor`, `subject` or `subject_id` field (`catalogue.py`; `event_type` is a ClassVar). |
| Role-mix percent not rounded (blind, edge) | false | rejected | `EstimatesEstimateLineEdited` types role mixes as `dict[str, int]`. |
| Extra roles beyond the three are silently dropped (edge) | low | rejected | Superseded by the `ROLES` patch; the backend mix is exactly `{engineer, project_manager, qa}`. |
| `outlineLink` concatenates classes without `cn` (blind) | false | rejected | `ui/button.tsx:49` keeps type classes outside `cn` on purpose; `source-inspector.tsx` uses the same pattern. |
| Header eyebrow not uppercase (blind) | false | rejected | The mockup's "Trace event · {when}" line is 12px/500, not uppercase, unlike its section headings. |
| Null subject version no longer shows "None" (blind) | false | rejected | `subjectText` shows the label alone; no information is lost. |
| Empty-state test lacks heading check; Overview `data-actor-type` double count; `fireEvent` vs `userEvent` (blind) | low | rejected | Overview test reads the `li` attribute directly (`pages.test.tsx:983`); verification layer found no gaps; rare-impact test style. |
| No 390px check; spec logs empty; Implementation Notes decisions (blind) | false | rejected | Fixes edit this build's spec; 390px is covered by the manual checks in step 5. |
| Subject cell outside the button is not clickable (blind) | low | rejected | Pre-existing (Story 9.8 had the same structure); fix adds click forwarding. |
| "Trace rows are append-only" appears twice with the inspector open (blind) | false | rejected | Both texts are required verbatim by the frozen intent. |

## Verification

**Commands:**
- `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` (in `web/`) -- expected: all pass.

**Manual checks:**
- Screenshot the tab with the inspector open, light and dark at 1440px, and compare with the mockup.
