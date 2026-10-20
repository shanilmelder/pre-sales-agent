---
title: 'Story 2.3: Live updates and the source viewer'
type: 'feature'
created: '2026-10-20'
status: 'done'
baseline_commit: 'd55e71892c0dee3cec2199e7c930c54a566ec587'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-2-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Opportunity event stream (Story 5.2) carries only run progress and `gaps.changed`. So the Sources tab polls every 2 s to show parse state, nothing tells the user when the stream drops, and an Opportunity Source can't be opened to read its extracted text or download the original.

**Approach:**
- Stream the Opportunity's trace events next to its progress rows, re-authorizing each event for each subscriber.
- Share one reconnecting connection per Opportunity, and show its state in a workspace status bar.
- Drive the Sources pills from the stream.
- Open a selected Source in the right-pane inspector, with its text and a signed **Download original** link.

## Boundaries & Constraints

**Always:**
- **NOTIFY:** `platform.trace.append` sends `pg_notify('psa_events', {event_id, opportunity_id, source: "trace"})` when `opportunity_id` is set. It's delivered on commit, carries ids only, and the channel constant moves into `platform` (workflows and gaps import it).
- **Stream:**
  - `event_stream` forwards `trace` notifications for its Opportunity. It re-reads each row and builds the frame `{event_type, subject_type, subject_id, subject_version, occurred_at, summary}` with `summary` = the event type. The trace payload is never sent.
  - Replay after `Last-Event-ID` merges the Opportunity's progress rows and trace rows after that id, ordered by id. An id unknown in both tables streams from now.
  - Before each live frame (progress, trace and `gaps.changed`), the stream re-checks that the subscriber can still read the Opportunity (`opportunities.readable_resource` in a short Unit of Work). Once they can't, the stream ends.
  - The documented 200 schema becomes the progress frame or a trace frame. The trace frame's `event_type` is a string.
- **Parse transitions trace** (AD-3), so every pill change reaches the stream:
  - New `intake.source.parse_started {version}`, appended when the job sets `parsing`.
  - New `intake.source.parse_failed {version, error_code}`, appended by `_mark_failed` when the row changed.
- **Source viewer API** (anyone who can read the Opportunity, sales representatives included; 404 like `get_passage`):
  - `GET /opportunities/{id}/sources/{source_id}/versions/{version}/text` returns `{version, char_count, text}`. 404 `not_found` unless that version is `parsed`.
  - `POST …/versions/{version}/download-link` returns `{url, expires_at}` from `platform.downloads.sign` (`PSA_DOWNLOAD_LINK_TTL_S`), with the version's stored filename.
- **Web connection** (`lib/opportunity-events.ts`):
  - One shared EventSource per Opportunity serves `useGapsEvents`, `useOpportunityEvents` (moved onto it) and the new Source subscribers.
  - It tracks the last frame id. When the browser gives up (`readyState` CLOSED, e.g. the Next route answered 502 or 401), it reopens after a capped backoff (1, 2, 5, then 10 s) with `?last_event_id=`. The `/api/opportunities/[id]/events` route forwards that as `Last-Event-ID` when the header is absent.
- **Status bar:** a slim bar at the bottom of the Opportunity workspace, shown only while the shared connection is down.
  - It reads "Reconnecting…" from the first drop, and "Offline — edits disabled" after 60 s down.
  - It is a polite live region and has no toast. On reconnect it disappears, and subscribers re-read.
  - **Decided (2026-10-21):** while it reads "Offline — edits disabled", `WorkspaceTabs` puts the active tab panel in a `<fieldset disabled>`. Every button and input in it goes inert, filters and Retry included. Links and tab switching still work.
- **Sources tab:**
  - Any `intake.source.*` frame, or a (re)connect, re-reads the list through the existing `loadSources` and `mergeSources` guard.
  - The 2 s poll runs only while the stream isn't connected.
- **Inspector:**
  - Clicking or pressing Enter on a Sources row opens it in the right pane (the Knowledge `SourcesTab` pattern).
  - It shows the kind, filename, `v{version} of {version_count}`, size, added by and at, and the parse pill (with its reason when failed).
  - It loads the extracted text automatically once the version is `parsed`, in a scrollable `<pre>`. Before that: "Available once parsing finishes". When failed: "No text was extracted from this version."
  - **Download original** links to a new same-origin route `/api/opportunities/[id]/sources/[sourceId]/versions/[version]/download`, which mirrors the Knowledge download route.
- **Privacy:** logs and frames carry ids, codes and sizes only, never text or filenames.

**Never:**
- No WebSockets.
- No passage highlighting (Story 2.5 Part B already has it), no version history list and no earlier-version downloads.
- No migration.
- The trace payload never goes into a frame.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Trace live | A Source is added while a reader is subscribed | A frame `event: intake.source.added` with `id` = the trace id; the list re-reads | N/A |
| Other Opportunity | A trace row for Opportunity B | Not sent to A's subscribers | N/A |
| No Opportunity | A trace row with null `opportunity_id` | No NOTIFY | N/A |
| Replay | `Last-Event-ID` = a progress id; trace and progress rows follow it | Both kinds replayed, in id order, no duplicates | Unknown id: from now |
| Revoked | The subscriber loses access mid-stream | The next event ends the stream; nothing is sent | N/A |
| Parse lifecycle | Upload, then the worker parses | Pills go Queued → Parsing → Parsed with no poll | Failure: `parse_failed` frame, red pill |
| Drop | The backend goes away for 70 s | "Reconnecting…", then "Offline — edits disabled" at 60 s; on return the bar hides and the list catches up | Backoff capped at 10 s |
| Text | Text route on a parsed version | 200 with the exact stored text | 404 when not parsed or not in this Opportunity |
| Download | A sales representative clicks Download original | The file streams as an attachment | 403 on a bad or expired token |

</frozen-after-approval>

## Code Map

- `backend/app/modules/workflows/application/events.py` -- `event_stream`, `_replay`, `_notified`, `frame`. Extend these. The route `stream_opportunity_events` is in `workflows/api/routes.py:145`; pass the actor into the stream so it can re-authorize.
- `backend/app/modules/workflows/adapters/repository.py:21-23,350-430` -- `EVENTS_CHANNEL`, `PROGRESS_SOURCE`, `get_progress` and `progress_after`. Add trace reads here on `TraceEvent`, which modules already read directly; see the opportunities and conflicts repositories.
- `backend/app/modules/workflows/application/models.py:61` -- `ProgressEventData`. Add `TraceEventData`.
- `backend/app/modules/gaps/adapters/repository.py:120` -- a duplicate `EVENTS_CHANNEL`. Import it from platform instead.
- `backend/app/platform/trace/writer.py` -- `append`: add the NOTIFY. `catalogue.py:138-170` -- the existing `IntakeSource*` payloads. Add `IntakeSourceParseStarted` and `IntakeSourceParseFailed`.
- `backend/app/modules/intake/application/jobs.py:92,148` -- `_mark_failed` and the `parsing` update. Append the new trace events there. `repository.update_parse` returns whether the row changed.
- `backend/app/modules/knowledge/application/sources.py:340-390` -- the `source_text` and `download_link` pattern to mirror in a new `intake/application/source_viewer.py`. Export it through `intake/application/public.py`. The routes go in `intake/api/routes.py`, next to `retry_source_parse`.
- `web/src/lib/opportunity-events.ts` -- the shared-source registry `subscribeGaps`. Generalise it to a per-type dispatch plus connection state, and expose `useEventStreamStatus`. Callers: `workspace-tabs.tsx`, `gaps-list.tsx`, `gaps-live-refresh.tsx` and `specialist-assessments.tsx:707`.
- `web/src/app/api/opportunities/[id]/events/route.ts` -- accept `?last_event_id=`.
- `web/src/components/opportunities/sources-list.tsx` -- `SourcesSection`'s poll and row selection. `web/src/components/knowledge/source-inspector.tsx` and `knowledge/sources-tab.tsx` -- the inspector and right-pane patterns (`RightPaneContent`, `useShell`).
- `web/src/app/api/knowledge/sources/[id]/versions/[version]/download/route.ts` -- the template for the new download route.
- `web/src/app/opportunities/actions.ts` -- add `loadSourceText`. `web/src/lib/api/schema.d.ts` -- regenerate it from a fresh local backend (`npm run gen:api`).

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/{events.py,trace/writer.py,trace/catalogue.py}`, `workflows/adapters/repository.py`, `gaps/adapters/repository.py` -- the shared channel constant, the trace NOTIFY, and the two new payloads
- [x] `backend/app/modules/workflows/{application/events.py,application/models.py,api/routes.py}` -- trace frames, merged replay, per-event re-authorization
- [x] `backend/app/modules/intake/application/{jobs.py,source_viewer.py,public.py,models.py}`, `intake/api/routes.py` -- parse traces, plus the text and download-link endpoints
- [x] `backend/tests/test_workflows_events.py`, `test_intake_parse_job.py`, new `test_intake_source_viewer.py` -- every backend matrix row
- [x] `web/src/lib/opportunity-events.ts` (+test), `app/api/opportunities/[id]/events/route.ts` (+test) -- the shared reconnecting connection and status
- [x] `web/src/components/opportunities/{connection-status.tsx,source-inspector.tsx,sources-list.tsx,workspace-tabs.tsx,specialist-assessments.tsx}`, `app/opportunities/actions.ts`, new download route, `schema.d.ts`, and tests with axe -- status bar, inspector, live pills

**Acceptance Criteria:**
- Given the worker running, when a collaborator uploads three files, then every pill moves to Parsed without a refresh and with no 2 s poll requests while connected.
- Given an open Opportunity page, when the API restarts, then the bar shows "Reconnecting…" and clears by itself after the API is back, and frames written meanwhile are applied.
- Given a parsed Source, when a reader selects it, then the inspector shows its metadata, version and full text, and Download original saves the original file.
- Given CI, when it runs, then the backend and web checks pass.

## Implementation Notes

- `parse_started` is appended only on the `queued` → `parsing` move, so a reclaimed or retried run of a row already `parsing` adds none. `parse_failed` is appended only when `update_parse` changed the row.
- Replay reads at most 500 rows of each kind (`merge_replay`). When one kind fills its limit, nothing after its last row is sent, so the next reconnect resumes without skipping rows of the other kind.
- Web: `subscribe` in `lib/opportunity-events.ts` is the single shared connection; `useOpportunityEvents`, `useGapsEvents`, `useSourceEvents` and `useEventStreamStatus` are thin hooks over it, so `specialist-assessments.tsx` needed no change.
- The Sources row's file name is the open button (one Tab stop per row). While offline the disabled `fieldset` also disables it, so the inspector can't be opened offline (accepted with the 2026-10-21 decision).
- The text and download-link endpoints accept any existing version; the UI only offers the latest.
- `schema.d.ts` was regenerated from a dumped `app.openapi()`, not the Docker `api`.
- `SourcesSection` uses `useShell`, so its tests render inside `ShellProviders`. Three `gaps.changed` stream tests in `test_gaps_answers.py` now wait for the id-less frame, since trace frames arrive too.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH | A replay capped at 500 rows per kind stops at the horizon; live frames then move the client's `Last-Event-ID` past the gap, so the rows after the horizon are lost | medium | `_replay` returns `merge_replay` once and the live loop starts; a reconnect only resumes from the last frame the client saw | patch |
| 2 | BH, ECH | Overlapping Sources re-reads apply in any order, and one dropped for a local mutation is never repeated, so a pill can stay stale while the poll is off | medium | `reread` checks only `mutation`; no sequence guard, no follow-up read | patch |
| 3 | BH, ECH | `parse_started` is traced twice when two runs both read `queued` before the update | low | The append depends on `target.status`, not on whether `update_parse` changed the row; direct fix | patch |
| 4 | BH | The download route doesn't pass the browser's abort to the backend fetch, so a cancelled download keeps streaming | low | `fetch(..., { cache })` without `signal`; direct fix | patch |
| 5 | VG | No test shows `gaps.changed` is withheld once the subscriber lost access | medium | The revocation test only reaches the trace path; the Gaps tests run as the owner | patch (test) |
| 6 | BH, ECH | After a refusal (404 or 401) the client reopens every 10 s forever and shows "Offline", not "no access" or "sign in" | low | The spec reopens on CLOSED, 401 included; the cost is one request per 10 s and any action shows the real error; telling refusals apart needs a probe request | reject |
| 7 | BH | On a quiet Opportunity a revoked subscriber's stream stays open | low | Nothing is sent to them without a frame, and keep-alives carry no content | reject |
| 8 | BH | Every trace type is streamed, without a per-type allowlist | false | The Decision Trace (`list_opportunity_trace`) already shows every reader the same event types and subject ids | reject |
| 9 | BH | No `(opportunity_id, id)` index for the trace replay query | low | Used only on reconnect with an id; the `(opportunity_id, occurred_at)` index narrows to the Opportunity; the intent excludes migrations | reject |
| 10 | BH | Two short Units of Work per frame per subscriber, with no debouncing | low | No named harm at R1 scale | reject |
| 11 | BH, ECH | The offline fieldset disables read-only controls too, including opening the inspector | false | Decided by the user on 2026-10-21 (whole tab inert) | reject |
| 12 | BH | Download errors save as a JSON file or fail silently | low | Same as the Knowledge download route (Story 3.2); rare | reject |
| 13 | BH | Very large texts load in one response and one `<pre>` | low | At most 5,000,000 characters; rare; the fix adds paging | reject |
| 14 | BH | Missing tests for parse frames end to end, the int32 version bound and focus return | low | The trace path is covered generically; the rest are cosmetic | reject |
| 15 | BH | The `WithLiteralType` split of the frame union is fragile | low | No current caller breaks; it is hypothetical | reject |
| 16 | BH | Over-long header comment line; `_TEXT_RESPONSES` overrides `_VIEWER_RESPONSES[404]` | low | The comment was already re-wrapped; the override is cosmetic | reject |
| 17 | VG | Role changes aren't seen by an open stream (the stream keeps the Principal taken when it opened) | low | The API authorizes from the token alone (epic context); membership changes are caught | reject |
| 18 | VG | The replay isn't re-checked per row | low | The window is the replay itself, right after the open-time check | reject |
| 19 | ECH | A failed text load has no Retry in the inspector | low | Reselecting the Source reloads it; rare | reject |
| 20 | ECH | A database error in the re-authorization ends the stream abruptly | low | The client reconnects with `Last-Event-ID`, which is the intended recovery | reject |

## Design Notes

- The design keeps the Story 5.2 transport. The browser's EventSource hits a same-origin Next route, which adds the Auth0 bearer token server-side. This satisfies "fetch-based SSE with the bearer token" without exposing the token to the page.
- Native EventSource reconnects send `Last-Event-ID` by themselves. Only the manual reopen after CLOSED needs the query parameter.

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass
