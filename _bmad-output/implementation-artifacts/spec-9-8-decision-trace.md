---
title: 'Story 9.8 (demo slice): read-only Decision Trace tab'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '7ea09672ff8aac5ecfd7426f78b832be738e9dac'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-9-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Every step of the flow already writes typed, append-only trace events (Sources parsed, Requirements extracted and edited, Gaps raised and converted, Estimate versions created, Assumptions accepted, Red Team reviews), but nobody can see them. "How did we arrive at this number?" has no answer in the UI (FR-41).

**Approach:** Fill the existing **Trace** tab (`8`) with a read-only, reverse-chronological timeline of the Opportunity's `platform_trace_events`, filterable by subject, actor type and event type (kept in the URL), with an inspector that renders the selected event's payload field by field.

## Boundaries & Constraints

**Always:**
- **API:** `GET /opportunities/{id}/trace?page=&page_size=&subject_type=&actor_type=&event_type=` in the `opportunities` module (it can read the platform table; platform can't import modules). Authorised with `opportunities.readable_resource`, so anyone who can read the Opportunity (sales representatives included) sees it; others get the 404-equivalent.
  - Offset pagination like the existing list APIs: `{page, page_size, total, items}`, `page_size` default 50, max 100. Ordered `occurred_at desc, id desc` (served by the `(opportunity_id, occurred_at)` index).
  - Each item: `id`, `occurred_at`, `event_type`, `actor {type, id, name}`, `subject {type, id, version}`, `payload` (the stored JSON, already ids and counts only). User names come from `identity.user_names`; an agent's name is its role in words from the `<agent_id>@<semver>` id (e.g. "Red Team Agent") with the version kept for the inspector; system actors read "System".
  - Filters are exact matches on the stored values; unknown values return an empty page, not an error. Also returns the filter options present for this Opportunity (distinct subject types, actor types, event types) so the UI only offers real ones.
- **No write path:** no update or delete endpoint. The existing test that `psa_app` can't UPDATE or DELETE `platform_trace_events` stays.
- **Catalogue test (CI):** every `event_type` appended anywhere in `backend/app` has a registered payload model, and no payload model has a field whose name contains `prompt`, `reasoning`, `thought` or `chain`.
- **Web:**
  - `[id]/trace.tsx`, routed like the other tabs. Dense 32px rows: time (relative, absolute on hover/inspector), actor, the event in plain words (a label map per `event_type`, e.g. `estimates.assumption.accepted` → "Assumption accepted", falling back to the raw type), and the subject as a link to its tab (Requirement → Requirements, Gap or Clarification Question → Gaps, Estimate Version or Assumption → Estimate, Red Team Review → Assessments, Source → Sources).
  - Filters: three selects (Subject, Actor, Event) whose state lives in the URL search params, so a filtered view can be shared and survives reload. Pagination with Previous/Next and "Page n of m"; no infinite scroll.
  - The keyboard model (`j`/`k`, arrows, Enter opens the inspector) and axe checks as in the Gaps tab.
  - Inspector: event label, absolute time (UTC), actor (with agent version), subject type, id and version, and each payload field as a label/value row (counts, ids, kinds), in catalogue order.
  - Empty: "No decisions recorded yet." Filtered to nothing: "No events match these filters." with Clear filters.
- **Privacy:** the endpoint returns only stored trace payloads (ids, counts, kinds); nothing new is logged.

**Never:** No version filter, no Evidence chips or struck-through superseded references (no payload carries Evidence yet), no lineage or version compare (9.9), no completeness test (9.10), no live updates, no 5,000-event performance gate, no export. These stay `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Timeline | Opportunity with events from a user, an agent and the system | Newest first; names "[NAME]", "Red Team Agent", "System"; total correct | N/A |
| Other Opportunity | Events on another Opportunity and with null `opportunity_id` | Not returned | N/A |
| Filter | `actor_type=agent&event_type=estimates.estimate_version.created` | Only matching events; options list unchanged | N/A |
| Unknown filter | `subject_type=nope` | Empty page, 200 | N/A |
| Paging | 120 events, `page=3&page_size=50` | 20 items, total 120 | `page_size=500` → 422 |
| Who | Sales rep / non-member | 200 / 404 | N/A |
| Catalogue | A payload model with a `prompt_text` field, or an unregistered `event_type` in code | The CI test fails | N/A |
| URL state | Reload `/trace?actor=agent` | The Agent filter is still applied | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/platform/trace/models.py:32-52` `TraceEvent` (`opportunity_id`, `actor_type` user/agent/system, `actor_id`, `event_type`, `subject_type`, `subject_id`, `subject_version`, `payload`, `occurred_at`); indexes `(opportunity_id, occurred_at)` and `(subject_type, subject_id)`. No read helper exists.
- Query pattern: modules read `TraceEvent` from their own adapters, e.g. `backend/app/modules/opportunities/adapters/repository.py:312`. Put the new query there; route in `backend/app/modules/opportunities/api/routes.py` (router mounted at `main_api.py:117`); offset paging as at `routes.py:108,156-160` and repository `:230`.
- Auth: `opportunities.readable_resource` (`opportunities/application/opportunities.py:137`), as `gaps/application/gaps.py:153` uses it.
- Names: `identity.user_names(uow, ids)` (`identity/application/user_search.py:53`), imported in `identity/application/public.py:32` — export it in `__all__` if missing. Agent ids from `agents/contract.py:127`.
- Catalogue: `backend/app/platform/trace/catalogue.py` (`CATALOGUE` :40, `register` :43, naming rule :15-28); existing tests `backend/tests/test_trace.py` (no-UPDATE/DELETE :186). Find appended event types by scanning `backend/app` for `trace.append(` payload classes, or by importing every module and comparing payload classes used with `CATALOGUE`.
- Subject types: `identity.user`, `opportunities.opportunity`, `intake.source`, `intake.extraction`, `intake.requirement`, `gaps.detection`, `gaps.gap`, `gaps.clarification_question`, `estimates.estimate_version`, `estimates.assumption`, `assessments.review`.
- Web: `web/src/lib/workspace.ts:12` (`trace`, key `8`); `web/src/app/opportunities/[id]/[tab]/page.tsx:20-32` (add `trace.tsx`); reuse `components/opportunities/gaps-list.tsx` (`GapsList` :54 keyboard, `GapsSection` :215 inspector) and `status-pill.tsx`; URL params like `web/src/app/admin/users/page.tsx:80-97`. Regenerate `schema.d.ts` from a local uvicorn, not the Docker `api`.
- No migration.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/opportunities/**` (trace query, read model, route), `identity` public export if needed
- [x] `backend/tests/test_opportunity_trace.py` and the catalogue test -- every matrix row, against Postgres
- [x] Web: `schema.d.ts`, `lib/trace.ts` (labels, subject links), `trace.tsx`, list, filters, inspector, tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity after the full flow, when the Trace tab opens, then it lists Source, Requirement, Gap, Estimate, Assumption and Red Team events newest first with readable actors and events, filtering to "Agent" shows only agent events, and the inspector shows the selected event's fields.
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | verify | No test of focus returning to the row when the inspector closes | medium | patch | Pre-verified: no test in trace-list.test.tsx closes the pane. Fixed. |
| 2 | edge | Non-object JSONB payload makes `dict()` raise → 500 | false | reject | Every row is written by `trace.append` from a `TracePayload` model dump, always an object. |
| 3 | edge | Empty filter value filters on "" instead of none | low | patch | Direct correction (`or None`). Fixed. |
| 4 | edge | j/k with focus on a subject link jumps to the first row | low | reject | The link has `tabIndex=-1` and a click on it navigates away; not reachable by keyboard. |
| 5 | edge+blind | Catalogue scan misses aliased or module-level `append` calls | low | reject | Every append in the app uses `trace.append(...)` inside a function today; a stronger guard adds machinery for a case not shown. |
| 6 | blind | Web `EVENT_LABELS` can drift from the catalogue; 8.8's `estimate_version.exported` missing | low | patch | Add the 8.8 label now (raw type is the fallback); a drift test is out of scope. Fixed. |
| 7 | blind | Filter params have no `max_length` | low | patch | Limits must be enforced in the API (no reverse proxy); the web caps at 200. Fixed. |
| 8 | blind | Five queries per page; options scan the whole trace | low | reject | Fine at demo volumes; the 5,000-event gate is excluded by intent. |
| 9 | blind | Offset pages shift when new events arrive | false | reject | The intent chose offset pagination like the existing list APIs. |
| 10 | blind | Forbidden-word list is name-based only | false | reject | The intent fixes the four words. |
| 11 | blind | Registration test doesn't check the reverse (dead catalogue entries) | low | reject | Not asked by the intent; no harm to users. |
| 12 | blind | Subject link unreachable by keyboard | medium | patch | Grid handles only up/down and the link is `tabIndex=-1`; add it to the inspector. Fixed. |
| 13 | blind | Subject links go to the tab, not the item | false | reject | The intent says "a link to its tab". |
| 14 | blind | Acronym agents read "Pm Agent" | low | reject | No such agent exists; current ids read correctly ("Red Team Agent", "Estimating Agent"). |
| 15 | blind | ~700 lines of formatting-only churn in data.ts, pages.test.tsx, [tab]/page.tsx | medium | patch | Hides the real change and conflicts with the parallel 8.8 branch editing pages.test.tsx. Fixed. |
| 16 | blind | Trace tab awaits API calls sequentially | low | reject | One extra round trip on a local demo. |
| 17 | blind | Relative times never refresh | low | reject | Cosmetic; absolute time is in the inspector. |
| 18 | blind | Label wording inconsistencies; long id lists unbounded | low | reject | Cosmetic. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
