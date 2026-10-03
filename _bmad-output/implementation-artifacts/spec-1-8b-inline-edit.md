---
title: 'Story 1.8 (Part B): Owner edits title and target proposal date inline'
type: 'feature'
created: '2026-10-04'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: '9a3ba06122d83c870253fad5b0e17f995c7d6c45'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Once an Opportunity is created, its title and target proposal date can't be changed. The workspace header shows them read-only.

**Approach:** Add `PATCH /api/v1/opportunities/{id}` for the title and target proposal date, open only to the owner and protected with `If-Match`, with every change traced. In the workspace header, the owner edits both fields inline and saves on blur.

## Boundaries & Constraints

**Always:**
- **API (AD-11, AD-15, AD-3):**
  - The body is `{title?, target_proposal_date?}`. Unknown fields give 422, and an omitted field stays unchanged. `If-Match` is required (428 if missing).
  - A new action `opportunities.opportunity.update` is granted to the owner only, with no role granting it. Other readers get 403 `forbidden`; non-readers and unknown ids get the same 404 as `GET`.
  - Order: authorize, then field rules, then `row_version`, then write, then trace, all in one UoW.
  - The title is trimmed and may be at most 200 characters. A blank title falls back to the customer name, as on create.
  - The date may not be in the past (UTC today). This is checked only when it differs from the stored date, so an already-past date can still be resent unchanged.
  - When no field actually changes, nothing is written and nothing is traced, and the response is 200 with the current ETag. A stale `If-Match` still gets 412.
  - A real change bumps `row_version` once and appends `opportunities.opportunity.updated` with payload `{fields: [...]}`, naming the changed fields only. Values never go into the trace or the logs.
  - The read model gains `can_edit`, which is true only for the owner and only hides controls; the API decides on every write.
- **Web (header):**
  - When `can_edit` is true, the title and the target date are click-to-edit. Each is a button labelled "Edit title" or "Edit target proposal date" that becomes a text input or a date input (`min` = UTC today). Everyone else sees plain text.
  - Blur or Enter saves, and Esc reverts and leaves the field. A save with an unchanged value sends nothing.
  - The save is optimistic: the new value shows at once.
  - On a 422 the value rolls back and the API's reason shows inline under the field, and the field is announced.
  - On a 412 the message "Changed by [user] since you opened it." appears with a Reload button. Nothing is overwritten. Reload refetches and discards the local edit.
  - On a 403, 404 or network error the value rolls back with a short inline message.
  - Success is announced in the polite live region. The header uses the returned `row_version` for its next save, and the page refreshes the server data so Overview and Collaborators pick up the new version. A title edit followed by a collaborator change must not hit a false 412.

**Never:** No editing of customer, products or industry; no ⌘Z undo; no diff view on 412; no auto-retry; no stored status; no SSE.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Title | Owner, current `If-Match`, `{title:"New"}` | 200, new ETag, `row_version`+1, one event `{fields:["title"]}` | N/A |
| Both | `{title, target_proposal_date}` both changed | One bump, one event `{fields:["title","target_proposal_date"]}` | N/A |
| Blank title | `{title:"  "}` | Title becomes the customer name; event only if that differs | N/A |
| Too long | 201-char title | 422 | Web rolls back with reason |
| Past date | Owner sets yesterday | 422 | Web rolls back with reason |
| Past date kept | Stored date already past, body resends it with a new title | 200; only the title changes | N/A |
| No change | Same values or `{}` | 200, no bump, no event | Stale `If-Match`: 412 |
| Stale | Old `If-Match` | 412; web shows "Changed by X since you opened it." and Reload | Missing `If-Match`: 428 |
| Not owner | Collaborator, HoD or admin | 403 `forbidden`; web shows no edit controls (`can_edit` false) | N/A |
| Non-reader | PATCH an Opportunity they can't read, or an unknown id | 404, same body as `GET` | N/A |
| Then share | Owner edits title, then adds a collaborator without reloading | Both succeed with no 412 | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/identity/actions.py`, `backend/app/modules/identity/domain/policy.py:57-75` -- add `OPPORTUNITY_UPDATE`: in `POLICY` with an empty role set, and in `OWNER_GRANTS`. `test_authorize.py` covers policy rows.
- `backend/app/platform/trace/catalogue.py:89-110` -- next to `OpportunitiesOpportunityCreated`, add `OpportunitiesOpportunityUpdated` with `fields: list[Literal["title","target_proposal_date"]]`.
- `backend/app/modules/opportunities/application/models.py:12-56` -- follow `NewOpportunity` (`extra="forbid"`, validators from `domain/opportunity.py`) for an `OpportunityChanges` model. The model checks shape only: title trimmed, at most `TITLE_MAX`, blank allowed. The past-date rule needs the stored value, so it runs in the command, not in a validator. Add `can_edit: bool` to `Opportunity` (L122).
- `backend/app/modules/opportunities/application/opportunities.py` -- copy the shape of `_change_member` (L278): `_load_readable`, `identity.authorize`, `parse_if_match`, `MAX_ROW_VERSION`, the no-op stale check, `repository.bump_row_version`, `trace.append`, `_log.info` with ids only, return `get`. Set `can_edit` in `_detail` (L92). Raise `UnprocessableError` (`platform/errors.py:134`) with a readable detail, e.g. "The target proposal date can't be in the past.", using `domain/opportunity.check_target_date`.
- `backend/app/modules/opportunities/adapters/repository.py` -- add `update_fields(uow, id, *, title=None, target_proposal_date=None)`, called after `bump_row_version` (L238).
- `backend/app/modules/opportunities/api/routes.py:240-257` -- a PATCH route modelled on `add_collaborator`: `operation_id="update_opportunity"`, `_WRITE_RESPONSES`, `IfMatchHeader`, `_with_etag`.
- `backend/tests/test_opportunities.py` -- seeding, token and role helpers to reuse. Put new tests in `test_opportunities_update.py`, run as `psa_app`.
- `web/scripts/gen-api.mjs` (`npm run gen:api`) → `web/src/lib/api/schema.d.ts`. CI checks drift.
- `web/src/app/opportunities/actions.ts:150-195` -- `changeCollaborator` maps 412/422/403/404 and `problem()`. Add `updateOpportunity({opportunityId, rowVersion, title?, target_proposal_date?})` the same way, validating input like `isCollaboratorInput`.
- `web/src/components/opportunities/collaborators.tsx` -- `staleMessage` (L35), Reload via `loadOpportunity` (L153), `announce`, `router.refresh()` after success. Reuse these; move `staleMessage` to `lib/opportunities.ts` if both components need it. It keeps `row_version` in local state from `initial`, so it must follow a newer version after a refresh (remount keyed by `row_version`, or sync state when `initial.row_version` grows).
- `web/src/components/opportunities/workspace-header.tsx` -- a server-safe header rendered by `app/opportunities/[id]/layout.tsx`. Add a client `inline-field.tsx` (or make the editable parts client components) and keep the read-only rendering for non-owners.
- `web/src/lib/opportunities.ts` -- `formatDate`, `utcToday`, `codePointLength` (title length in code points, as the API counts it).

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/identity/{actions.py,domain/policy.py}`, `backend/app/platform/trace/catalogue.py`, `backend/app/modules/opportunities/{application/models.py,application/opportunities.py,adapters/repository.py,api/routes.py}` -- the action and owner grant, the event, `OpportunityChanges`, `can_edit`, the `update` command and the PATCH route
- [x] `backend/tests/test_opportunities_update.py`, `backend/tests/test_authorize.py` -- every backend matrix row, checking trace rows (count, payload, no values), ETag and `row_version`
- [x] `web/src/lib/api/schema.d.ts` -- regenerate
- [x] `web/src/app/opportunities/actions.ts`, `web/src/components/opportunities/{inline-field.tsx,workspace-header.tsx,collaborators.tsx}`, `web/src/lib/opportunities.ts` -- server action, inline editing in the header, version sync with Collaborators
- [x] Web tests (`actions.test.ts`, `inline-field.test.tsx`, `workspace-header.test.tsx`, `collaborators.test.tsx`, `pages.test.tsx`) -- blur, Enter, Esc and unchanged-value no-op, 422 rollback with reason, 412 message with Reload, owner-only controls, the "Then share" row, axe

**Acceptance Criteria:**
- Given the owner, when they edit the title and blur, then the header shows the new title, a reload keeps it, and the trace holds one `opportunities.opportunity.updated` event naming `title`.
- Given CI, when it runs, then backend and web checks (including the generated-client drift check) pass.

## Implementation Notes

- `OpportunityChanges` treats an omitted or `null` field as unchanged. Body shape (unknown fields, title length, date format) is validated by FastAPI before the command runs, as for create; the command then runs authorize, the past-date rule, `If-Match`, write, trace.
- The 422 detail for the past date is the readable "The target proposal date can't be in the past."; the server action turns the generic "Invalid fields: body.title" into a sentence. The header also refuses a title over 200 code points without calling the API.
- Header and Collaborators follow a newer `row_version` from `router.refresh()` by adjusting state during render (no remount, so focus and notices survive).
- Local DB tests need `127.0.0.1` rather than `localhost` in `PSA_DATABASE_URL` on Windows (IPv6 fallback makes every connection slow).

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH | `update()` compares fields against an unlocked snapshot that may be older than `If-Match` | false | Under READ COMMITTED the snapshot is read after the client's version was committed, so `record.row_version >= expected`. When it's greater, the bump fails with 412. Only a fabricated future `If-Match` could race | reject |
| 2 | BH | Explicit `null` treated as "unchanged" | low | Matches "omitted field stays unchanged"; neither field can be cleared, and the web never sends null | reject |
| 3 | BH | No tests for impossible dates or explicit nulls | low | Pydantic's date parsing handles them; framework behaviour | reject |
| 4 | BH | 422 reason mapping depends on the "Invalid fields: body.x" wording | low | The web only sends strings in the right shape; the API's own sentences pass through | reject |
| 5 | BH | When the 412 follow-up read can't find the Opportunity, the result is stale with no name | low | Reload then takes the not-found branch and shows "no access"; nothing is overwritten | reject |
| 6 | BH, ECH | After 403 or 404 the editors stay active, so saves keep failing | low | No refresh, so `can_edit` stays stale; direct fix is `router.refresh()` on those results | patch |
| 7 | BH | Header 412 notice stays after a refresh brings a newer version | low | Header stays locked until its own Reload; direct fix is to clear `stale` where a newer version is adopted | patch |
| 8 | BH, ECH, VG | A cleared or half-typed date reverts silently, and no test covers it | low | Same outcome as Esc (nothing sent, old value back). VG gap: the `!raw` guard is untested | patch (test) |
| 9 | BH | Opening the date picker could blur the input | maybe-false | Chromium's picker keeps focus on the input; needs a real-browser check. Low at most | reject |
| 10 | BH | "Today" is the UTC date | low | Project convention, the same rule as create (`utcToday`, backend `datetime.now(UTC)`) | reject |
| 11 | BH | Overlay button stops the owner selecting the title text | low | A click-to-edit design choice; fixing it means restructuring the control | reject |
| 12 | BH | `user-inspector.tsx` keeps its own `staleMessage` | low | Pre-existing copy in another module | reject |
| 13 | BH | No UTC-boundary, concurrent-PATCH or 428-vs-422 precedence tests; one action test is a tautology | low | `bump_row_version` locking is already covered from 1.7; the precedence follows spec order and is tested for the stale case | reject |
| 14 | BH | `schema.d.ts` was left out of the review diff | false | Excluded on purpose; CI's drift check covers it (`ci.yml:135-140`) | reject |
| 15 | ECH | A collaborator change between a header save and the refresh landing gets a false 412 | low | A window of one refresh round trip; recovers with Reload and overwrites nothing. A fix needs shared client state | reject |
| 16 | ECH | A non-owner with a malformed body gets 422 rather than 403 | low | FastAPI validates the body before the command, as on create; leaks nothing | reject |
| 17 | ECH | A save result can replace a newer refreshed version | low | Needs an outside change during a save; direct fix is a functional `setCurrent` keeping the higher `row_version` | patch |
| 18 | ECH | `value` changing mid-edit shifts the baseline the draft is compared with | low | Only when a refresh lands during an edit and the draft equals one of the two values | reject |
| 19 | VG | No test that Collaborators ignores an older refreshed `row_version` | low | Removing the `>` guard keeps the suite green | patch (test) |
| 20 | VG | Header Reload failure paths (error, not-found) untested | low | Unlocking on a failed Reload would stay green | patch (test) |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run gen:api && git diff --exit-code src/lib/api/schema.d.ts && npm run lint && npm run typecheck && npm test && npm run build` -- expected: no drift, all pass

**Manual checks (human):**
- As the owner, edit the title and date in the header, then add a collaborator. Then edit in two browser tabs to see the 412 with Reload.
