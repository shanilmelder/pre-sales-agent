---
title: 'Story 1.6: Administrator assigns roles'
type: 'feature'
created: '2026-10-03'
status: 'done'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'ca708bca96e2e22a2770fba87600b7ed73c5b1bf'
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** New users have no roles, and the only way to grant one today is SQL. Administrators need a screen to give each person the access their job needs, safely and with an audit trail.

**Approach:** Add `identity` commands `assign_role` and `remove_role`, following the AD-3 path (authorize, rules, `row_version`, write, trace), plus an admin-only users query. Expose them under `/api/v1/admin/users`. Build Admin → Users & roles: a paginated list, with an inspector in the right pane where role toggles save immediately with `If-Match`.

## Boundaries & Constraints

**Always:**
- **Roles:** only the nine `Role` values. Assign and remove are idempotent at the data level: assigning a held role or removing a missing one changes nothing and writes no trace event, and still returns the current user.
- **Every change** (each assign or remove):
  - runs in one Unit of Work;
  - checks `If-Match` against the target user's `row_version` and bumps it atomically;
  - appends `identity.user.role_assigned` or `identity.user.role_removed`. The actor is the admin, the subject is the target user (`subject_version` = the new `row_version`), the payload is `{role}`, and `opportunity_id = null`.
- **Last administrator:** removing `platform_administrator` from the last holder is rejected with 409 `last_administrator` and the detail "At least one platform administrator is required". Concurrent removals are serialised with a row lock, so two admins can never remove each other into zero.
- **Authorization:** every Users & roles endpoint calls `authorize` with the new action `identity.user.list` (read) or the existing assign and remove actions. Non-admins get 403 `forbidden`.
- **Effect:** roles are read per request, so changes apply on the target's next request.
- **Concurrent edit:** a 412 shows inline "Changed by {name} since you opened it." with Reload. {name} is the actor of the latest role trace event on that user, or "another administrator" when there is none. Nothing is overwritten.

**Never:** No user creation, deletion or deactivation; no profile editing; no Auth0 calls; no diff view; no bulk edit. No email or name in trace payloads or logs.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Assign | Admin, `If-Match` current, role not held | 200 user with role; `row_version` +1; one `role_assigned` event | N/A |
| Remove | Admin, current, role held, not the last admin | 200 without role; +1; one `role_removed` event | N/A |
| No-op | Assign a held role / remove a missing one | 200 unchanged, no event, no version bump | N/A |
| Stale | `If-Match` older than the stored version | 412 `row_version_mismatch`; nothing written | UI: inline message with Reload |
| Missing If-Match | Write without the header | 428 `if_match_required` | N/A |
| Last admin | Remove `platform_administrator` from the only holder (incl. self) | 409 `last_administrator`, the exact detail text | UI shows the detail inline |
| Race | Two admins each remove the other's admin role at once | Exactly one succeeds; the other gets 409 | Row lock |
| Non-admin | Any Users & roles endpoint | 403 `forbidden` | UI: Admin hidden (Story 1.5) |
| Unknown | Bad role value / unknown user id | 422 / 404 `not_found` | N/A |
| Next request | Target user's next `/me` after assign | Includes the new role | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/identity/actions.py` -- `Action` StrEnum with `USER_ASSIGN_ROLE`/`USER_REMOVE_ROLE`; add `USER_LIST = "identity.user.list"`. `domain/policy.py` `POLICY`: add it for `PLATFORM_ADMINISTRATOR`.
- `backend/app/modules/identity/adapters/{models,repository}.py` -- `IdentityUser(RowVersioned)`, `IdentityUserRole(user_id, role)`; `get_by_sub`, `insert_if_absent`, `load_roles`. Add list (paginated, with roles), get by id, add or remove role, a version bump (`UPDATE … SET row_version = row_version + 1 WHERE id = :id AND row_version = :expected`, where 0 rows means 412), and an admin-holders lock (`SELECT … FROM identity_user_roles WHERE role = 'platform_administrator' FOR UPDATE`).
- `backend/app/modules/identity/application/provisioning.py` -- `CurrentPrincipal`, `user_actor`, `USER_SUBJECT = "identity.user"`, `provision_or_load` (the pattern for trace append in a UoW).
- `backend/app/modules/identity/application/public.py` -- re-exports; add the new commands and read models.
- `backend/app/modules/identity/api/routes.py` -- `router`, `AUTH_RESPONSES`; add the admin routes here or in a sibling router included by `main_api.py:106`.
- `backend/app/platform/concurrency.py` -- `IfMatch` handler type (428/412), `etag()`, `RowVersionMismatchError`; return an `ETag` header on user reads and writes.
- `backend/app/platform/errors.py` -- `ProblemError` subclasses; add `ConflictError`-style `LastAdministratorError` (409) and a `NotFoundError` (404) if missing.
- `backend/app/platform/trace/catalogue.py` -- `@register` payloads; add `IdentityUserRoleAssigned`/`IdentityUserRoleRemoved` with `role: str`.
- `backend/tests/conftest.py` -- `db_app`, `sync_engine`, `make_client`, `run_async`; token stubbing lives in `tests/test_auth.py`/`test_provisioning.py`.
- `web/src/app/admin/page.tsx` -- admin-gated placeholder inside `AppShell`. It becomes Users & roles at `/admin/users`, and `/admin` redirects there for admins.
- `web/src/components/shell/{right-pane,shell-context}.tsx` -- the right pane currently shows "Nothing selected."; let pages provide its content (the inspector) through context.
- `web/src/lib/api/{server.ts,schema.d.ts}` -- `createServerApiClient()` with Bearer; regenerate the schema (`npm run gen:api`).
- `web/src/app/settings/actions.ts` -- the server-action pattern for writes.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/trace/catalogue.py`, `backend/app/platform/errors.py`, `backend/app/modules/identity/{actions.py,domain/policy.py}` -- two trace payloads, 409 and 404 errors, the `USER_LIST` action
- [x] `backend/app/modules/identity/adapters/repository.py` -- list, get, add or remove role, version bump, admin lock
- [x] `backend/app/modules/identity/application/{role_admin.py,public.py}` -- `list_users`, `get_user`, `assign_role`, `remove_role` (UoW first, authorize, last-admin rule under the lock, version, write, trace); the read model `AdminUser {id,name,email,roles,row_version,last_changed_by}`
- [x] `backend/app/modules/identity/api/admin_routes.py`, `backend/app/main_api.py` -- `GET /admin/users?page=&page_size=` (50 by default), `GET /admin/users/{id}`, `PUT` and `DELETE /admin/users/{id}/roles/{role}` with `If-Match`; ETag on responses; documented problem responses
- [x] `backend/tests/test_role_admin.py` -- every matrix row against Postgres as `psa_app`, including the race (two UoWs) and the trace rows
- [x] `web/src/lib/api/schema.d.ts`, `web/src/app/admin/{page.tsx,users/page.tsx,users/actions.ts}`, `web/src/components/admin/{users-table,user-inspector}.tsx`, right-pane content slot -- paginated list (32px rows, keyboard-selectable, Enter opens the inspector); the inspector has nine labelled role switches that save on change; inline 412 with Reload and 409 detail; a success announcement
- [x] `web/src/components/admin/*.test.tsx`, `web/src/app/admin/users/page.test.tsx` -- list, toggle success, 412 with Reload, 409, non-admin, axe

**Acceptance Criteria:**
- Given an admin assigns `pm_reviewer` to a user, when that user's next `/me` runs, then it includes `pm_reviewer`, and one trace row records the admin as actor, the user as subject and `{"role":"pm_reviewer"}`.
- Given CI, when it runs, then backend lint, mypy, `alembic check` and pytest, and web lint, typecheck, test and build all pass.

## Implementation Notes

- Commands live in `identity/application/role_admin.py`. They take the raw `If-Match` header and parse it *after* `authorize`, so a non-admin always gets 403, even with no header. Order inside the UoW: authorize, 404, last-admin rule (under `lock_admin_holders`, `FOR UPDATE ORDER BY user_id`), no-op check, then the atomic `row_version` bump (0 rows means 412), the role write and the trace event.
- A no-op still checks `If-Match`, so a stale view gets 412 and is told to reload instead of a silent 200.
- `last_changed_by` is read from the trace (the latest `role_assigned`/`role_removed` event per subject, `DISTINCT ON`), joined to `identity_users` by actor id. The web action fetches it after a 412 to fill "Changed by {name}".
- `ConflictError` (409 base) and `NotFoundError` (404) were added to `platform/errors.py`; `LastAdministratorError` subclasses `ConflictError`.
- Right-pane slot: `RightPaneContent` portals children into the pane, keeping them in the page's React tree; the pane shows "Nothing selected." only while no content is mounted.
- `/admin` redirects admins to `/admin/users`; non-admins still see the in-shell access message there.

## Spec Change Log

## Review Triage Log

Iteration 0. Layers: blind-hunter (BH), edge-case-hunter (ECH), verification-gap (VG).

| # | Source | Finding | Verdict | Evidence | Route |
|---|---|---|---|---|---|
| 1 | BH, ECH | A role written without a version bump (direct SQL, seed, test `_grant`) causes a 500 | medium | `_change_role` raises `RuntimeError` when `write()` returns False after a successful bump; it should be a 412 reload | patch |
| 2 | BH | Keyboard focus is lost after every toggle and on 412 | medium | Switches get `disabled` while pending, so focus drops to `<body>`; nothing moves focus to Reload | patch |
| 3 | BH | Every table row is a Tab stop; Enter doesn't move focus to the inspector | medium | No roving `tabIndex`; EXPERIENCE: focus moves into the inspector when it opens | patch |
| 4 | BH, VG, ECH | A `?page=` past the end shows "No users yet." and an inverted range | low | `parsePage` allows up to 999999; `Pagination` doesn't clamp; direct | patch |
| 5 | ECH | `If-Match` above int32 gives a 500 | low | `parse_if_match` accepts 18 digits; the `Integer` bind overflows; direct guard → 412 | patch |
| 6 | ECH | A huge `page` gives an OFFSET overflow 500 | low | No upper bound on `page`; direct `Query(le=…)` | patch |
| 7 | ECH | Reload after a 412 that returns not-found or forbidden gets stuck | low | Only `ok` is handled; mapping the other results is direct | patch |
| 8 | ECH | The list keeps stale rows after a server refresh with the same key | low | `key` covers only the page, so state isn't resynced and the next save gets a 412; direct | patch |
| 9 | VG | `last_changed_by` latest-event ordering untested | medium | Reversing `DESC` stays green (only single-event tests) | patch |
| 10 | VG | List ordering (case-insensitive name, then id) untested | medium | Removing `lower()` stays green | patch |
| 11 | VG, BH | `changeRole`/`loadUser` 403 and 404 mapping, plus inspector messages, untested | medium | Deleting those cases stays green | patch |
| 12 | BH | List test skips its checks when total > 200 | low | `if total <= 200:` guard; GET the admin by id instead | patch |
| 13 | BH | Nothing checks that admins see the Admin nav link any more | low | The old `/admin` test was replaced by the redirect test | patch |
| 14 | BH | Privilege changes have no confirmation | false | The frozen spec says role switches save on change | reject |
| 15 | BH | The 412 message may name the wrong person | false | Only role changes bump `identity_users.row_version` today | reject |
| 16 | BH | No index for `last_role_changers`; cast on the join | low | `(subject_type, subject_id)` index exists (0002); small tables | reject |
| 17 | BH | `_only_admins` breaks parallel tests | low | Tests run serially; no xdist | reject |
| 18 | BH | Denied privilege attempts aren't audited | low | Not required by the spec; AD-15 audits agent denials | reject |
| 19 | BH | List and count can disagree; `AdminUser.id` typed `str` | low | Read-committed drift between two reads is harmless; IDs are strings by convention | reject |
| 20 | VG | 409 last-admin is checked before 412 | low | Deliberate (Implementation Notes); either order is safe | reject |
| 21 | ECH | An admin demoted mid-request can still act | low | The window is one request; closing it needs extra locking | reject |
| 22 | BH | `If-Match` edge forms (`*`, weak, unquoted) untested here | false | Covered by `test_concurrency.py` for `parse_if_match` | reject |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && PSA_DATABASE_URL=<psa_app> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks (human, signed in as admin):**
- Admin → Users & roles. Toggle a role for another user and reload their session: access changes. Editing the same user in two tabs: the second gets the inline 412 with Reload. Removing your own admin role while you are the only admin: rejected with the message.
