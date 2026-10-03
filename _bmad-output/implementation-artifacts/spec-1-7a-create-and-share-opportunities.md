---
title: 'Story 1.7 (Part A): Create and share Opportunities'
type: 'feature'
created: '2026-10-04'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'f4546406e1c99a0e29d36287c7c7ade69d5c9f55'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** There is nothing to work on yet. Presales engineers need to create an Opportunity, share it with the people on the deal, and know that nobody else can see it.

**Approach:** Add an `opportunities` module with create, read, list and collaborator commands on the AD-3 path. Opportunity access goes through `identity.authorize` with a resource-scoped rule. In the web app, My Opportunities and All Opportunities become real paginated lists, there is a create page (`c` / New Opportunity), and an Opportunity page where the owner manages collaborators through user search. The All Opportunities filters are Part B (see deferred-work.md).

## Boundaries & Constraints

**Always:**
- **Fields:**
  - **Title:** optional, ≤200 characters; defaults to the customer name.
  - **Customer name:** required, ≤200.
  - **Products in scope:** 1–20 free-text names, each trimmed, 1–100 characters, de-duplicated case-insensitively.
  - **Industry:** required free text, ≤100.
  - **Target proposal date:** a calendar date, not in the past.
  - **System fields:** a UUIDv7 `id`, `owner_id` set to the creator, `row_version`, and `created_at`.
- **Access:**
  - **Create:** `presales_engineer` only.
  - **Read:** the owner, the collaborators, `head_of_delivery` and `platform_administrator`.
  - **Collaborators:** only the owner adds or removes them.
  - **Everyone else:** a 404 `not_found` problem response, identical to the one for an id that doesn't exist, so nothing leaks.
  - **Where the rule lives:** in `identity` policy, using a `Resource` that carries owner and member ids.
- **Collaborators:**
  - Picked from user search, which matches the name or email of users who hold at least one role.
  - The owner can't be added or removed.
  - Changes take effect on the next request, use `If-Match` against the Opportunity's `row_version`, and adding an existing member (or removing a missing one) is a no-op.
- **Trace:**
  - `opportunities.opportunity.created`, with an empty payload.
  - `opportunities.collaborator.added` / `removed`, with payload `{user_id}`.
  - Every event has `opportunity_id` set and the subject set to the Opportunity. No customer content in payloads or logs.
- **Lists:**
  - My Opportunities shows the ones the user owns or collaborates on. All Opportunities shows every one the user can read.
  - Columns: customer, derived status, owner name and target proposal date. Rows are 32px with `j`/`k` and Enter to open, paginated.
  - Empty state: "No Opportunities yet. Press c to create one."
  - Skeleton rows show for at least 150 ms on first load.
- **Status:** derived by a query, never stored. Every Opportunity is `intake` in this story.

**Never:**
- No filters on All Opportunities (that's Part B).
- No workspace tabs, inline editing or ownership transfer (Story 1.8+).
- No deletion.
- No notifications.
- No foreign keys across modules.
- `opportunities` never imports `identity`'s `domain` or `adapters`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create | PSE, valid fields | 201, owner = caller, status `intake`, one `created` event | N/A |
| Create denied | User without `presales_engineer` | 403 `forbidden`; New Opportunity and `c` hidden | N/A |
| Invalid | Past date, no products, over-length, 21 products | 422 naming the fields | Form shows field errors |
| Read | Owner, collaborator, HoD or admin | 200 | N/A |
| Hidden | Any other user, or an unknown id | 404 `not_found`, same body for both | UI: "You don't have access to this Opportunity" |
| Add collaborator | Owner, current `If-Match`, user with a role | 200; that user can read it on their next request; `added` event | N/A |
| Remove | Owner removes a collaborator | 200; their next read is 404; `removed` event | N/A |
| Bad member | Add the owner, or a user with no roles | 422 | N/A |
| Not owner | A collaborator, HoD or admin adds or removes | 403 `forbidden` (they can read it) | N/A |
| Stale | Old `If-Match` | 412 | UI: "Changed by {name} since you opened it." with Reload |
| My vs All | User A owns X and collaborates on Y; HoD | A: My = All = {X, Y}. HoD: All = every Opportunity, My = only their own | N/A |
| Empty | No Opportunities | Empty-state sentence; skeleton ≥150 ms first | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/identity/actions.py`, `domain/policy.py` -- `Action` StrEnum, `POLICY`, `Principal(actor, roles)`, `Resource(type, id)`, `is_allowed`.
  - Add `opportunities.opportunity.create`, `.read`, `opportunities.collaborator.add`, `.remove` and `identity.user.search`.
  - Extend `Resource` with optional `owner_id` / `member_ids` and a resource-scoped rule in `is_allowed` (owner or member, or a role grant).
  - The actor's user id is `UUID(principal.actor.id)`.
- `backend/app/modules/identity/application/{public.py,role_admin.py}` and `adapters/repository.py` -- the pattern to follow. Add public queries `search_users(uow, actor, q, limit)` (users with ≥1 role; name/email `ILIKE`) and `user_names(uow, ids)` for `opportunities` to call.
- `backend/app/modules/identity/api/admin_routes.py` -- the route pattern: `CurrentPrincipal`, `UoW`, raw `If-Match` header, `ETag`, documented problem responses.
- `backend/app/platform/{errors.py,concurrency.py,trace/catalogue.py,uow.py,ids.py}` -- `NotFoundError` (404), `ConflictError`, `RowVersionMismatchError`, `parse_if_match`, `etag`, `@register` payloads, `new_id()`.
- `backend/app/modules/__init__.py` and `tests/test_architecture.py` -- the module layout `api/ application/ domain/ adapters/`. Cross-module calls go through `application/public.py` only.
- `backend/migrations/versions/` -- the latest revision is the Story 1.4b identity migration. Default privileges already grant `psa_app` DML on new tables.
- `backend/tests/test_role_admin.py` -- token stubbing, users seeded with roles, and the two-UoW pattern.
- `web/src/app/{my-opportunities,opportunities}/page.tsx` -- placeholders inside `AppShell`; replace them.
- `web/src/components/admin/{users-table,users-admin}.tsx`, `web/src/app/admin/users/{page,actions}.tsx` -- reuse the list pattern: roving tabindex, `j`/`k`/Enter, pagination, a server action calling `createServerApiClient()`, and the 412 notice.
- `web/src/lib/shortcuts.ts`, `web/src/components/shell/keyboard-shortcuts.tsx` -- the shared shortcut definition. Add `c` (single key, create), active only for users who can create.
- `web/src/lib/navigation.ts` -- `Role` type. `landingFor` stays as it is.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/identity/{actions.py,domain/policy.py,application/user_search.py,application/public.py,adapters/repository.py}`, `backend/app/platform/trace/catalogue.py` -- actions, the resource-scoped rule, user search and name lookup, three trace payloads
- [x] `backend/app/modules/opportunities/{domain,application,adapters,api}/…`, `backend/migrations/versions/20261004_0004_opportunities.py`, `backend/app/main_api.py`, `backend/migrations/env.py` -- tables `opportunities_opportunities` and `opportunities_collaborators`; commands `create`, `add_collaborator`, `remove_collaborator`; queries `get`, `list_mine`, `list_all`; `derived_status()`; routes `POST/GET /api/v1/opportunities`, `GET /api/v1/opportunities/{id}`, `PUT/DELETE /api/v1/opportunities/{id}/collaborators/{user_id}`, `GET /api/v1/users/search?q=`
- [x] `backend/tests/test_opportunities.py`, `backend/tests/test_user_search.py`, `backend/tests/test_authorize.py` -- every matrix row as `psa_app`, plus the policy unit tests
- [x] `web/src/lib/api/schema.d.ts`, `web/src/app/{my-opportunities,opportunities}/page.tsx`, `web/src/app/opportunities/{new/page.tsx,[id]/page.tsx,actions.ts}`, `web/src/components/opportunities/{opportunities-table,create-form,collaborators}.tsx`, `web/src/lib/shortcuts.ts` -- lists with skeleton and empty state; create page that lands on the new Opportunity; Opportunity page showing the fields, status, owner and collaborators, with search-and-add and remove for the owner; "You don't have access to this Opportunity" on 404; `c` shortcut and New Opportunity button for PSEs only
- [x] `web/src/components/opportunities/*.test.tsx`, `web/src/app/opportunities/**/*.test.tsx` -- matrix rows on the web side, keyboard, axe

**Acceptance Criteria:**
- Given a PSE creates an Opportunity and adds a collaborator, when the collaborator opens My Opportunities on their next request, then it is listed, and the trace holds `created` and `collaborator.added` with `opportunity_id` set.
- Given CI, when it runs, then backend lint, mypy, import contracts, `alembic check` and pytest, and web lint, typecheck, test and build all pass.

## Implementation Notes

- Lists share one endpoint: `GET /api/v1/opportunities?scope=mine|all` (default `all`), newest first, `page`/`page_size` as in Users & roles (50, max 200).
- Policy: `POLICY` keeps role grants (`create`: PSE; `read`: HoD, admin; collaborator add/remove: none; `identity.user.search`: any role). `OWNER_GRANTS` (read, add, remove) and `MEMBER_GRANTS` (read) are the resource-scoped rule. `identity.can()` asks the policy without raising, so reads answer 404 instead of 403.
- Bad members are 422 with code `invalid_collaborator` (new `UnprocessableError` in `platform/errors.py`); an unknown user id is treated like a user with no role.
- Create body validation (FastAPI/Pydantic, 422 `validation_error` naming `body.<field>`) runs before `authorize`, so a non-PSE sending an invalid body gets 422, not 403. "Not in the past" is checked against today's UTC date; the form's `min` uses the browser's local date.
- `Opportunity` carries `last_changed_by` (latest trace actor on the Opportunity) for the 412 notice and `can_manage_collaborators` (display only).
- The empty state shows the spec sentence to PSEs; others (who have no `c`) see "No Opportunities yet."
- An import-linter contract forbids `app.modules.opportunities` from importing identity's `domain`/`adapters`.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH | Users with no roles keep owner/collaborator access through the API | medium | `is_allowed` grants `OWNER_GRANTS`/`MEMBER_GRANTS` without a role, and a test locks this in. Story 1.4: no roles means no access. Requiring ≥1 role is direct | patch |
| 2 | BH | Any role can list the whole user directory (names and emails) one letter at a time | medium | `USER_SEARCH` granted to all roles with `min_length=1`. Only Opportunity owners (PSEs) need the picker | patch |
| 3 | BH, ECH | The form's "today" is local, the API's is UTC, so a date the form allows can get a 422 | medium | `localToday()` vs `datetime.now(UTC).date()`; using UTC in the form is direct | patch |
| 4 | VG | User search ordering untested | medium | Dropping `order_by` stays green | patch |
| 5 | BH | `_change_member` "write found membership already changed" rollback untested | medium | No test reaches that branch | patch |
| 6 | ECH | `If-Match` = 2³¹−1 passes the guard, then the bump overflows → 500 | low | Guard is `>`; direct `>=` | patch |
| 7 | BH, ECH | Search error sticks after clearing; old results show for a new query during the debounce (Add on a non-match) | low | `searchError`/`results` aren't reset and results aren't tied to their query; direct | patch |
| 8 | BH | `can_manage_collaborators` derived from ADD only, but drives Add and Remove | low | Direct: require both actions | patch |
| 9 | VG | Owner/member grants ignore `resource.type` | low | Any future owned resource would grant Opportunity actions; a direct type check | patch |
| 10 | ECH | Client length counts UTF-16 units, API counts code points; slicing the search query can split a surrogate pair | low | Emoji input is wrongly rejected, or URL encoding throws; `Array.from` is direct | patch |
| 11 | ECH | `page > 1` with `total == 0` shows an empty page with Previous | low | The redirect only runs when `total > 0`; direct | patch |
| 12 | VG, BH | The 422 field mapping parses detail text the backend doesn't pin | low | The backend only checks a substring; pin the exact `detail` format in the backend test (structured field lists would add API surface) | patch |
| 13 | BH | Skeleton shows ≥150 ms even with server-rendered data | false | The frozen spec requires skeleton rows ≥150 ms on first load | reject |
| 14 | BH | No DB CHECK constraints for field rules | low | The only write paths are the validated commands; adds a migration | reject |
| 15 | BH | A 412 fetches the Opportunity, then Reload fetches it again | low | One extra request on a rare path | reject |
| 16 | BH, ECH | Deep OFFSET; total and page from two statements | low | Small tables; same accepted trade-off as Story 1.6 | reject |
| 17 | BH | Opportunity page has no back link; doesn't show `created_at` or who created it | low | The workspace header arrives in Story 1.8 | reject |
| 18 | ECH | Status pill crashes on an unknown status | low | Status enum comes from the generated schema; only version skew triggers it | reject |
| 19 | ECH | Target loses their role between the role check and the collaborator insert | low | One-request window; closing it needs a cross-module lock | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic upgrade head && uv run alembic check && PSA_DATABASE_URL=<psa_app> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks (human, signed in):**
- As a PSE: press `c`, create an Opportunity, add a collaborator. Signed in as that collaborator, it appears in My Opportunities. A third user without access opening the URL gets "You don't have access to this Opportunity".
