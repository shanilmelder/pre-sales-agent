---
title: 'Story 1.9 (demo slice): Auth0 roles and permissions replace platform-stored roles'
type: 'refactor'
created: '2026-10-06'
status: 'done'
baseline_commit: '0df4f04ed844f9aa0d9417140d4b340cc5ff7d51'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-1-context.md'
  - '{project-root}/_bmad-output/planning-artifacts/architecture/architecture-pre-sales-agent-2026-10-01/ARCHITECTURE-SPINE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Roles are stored in `identity_user_roles` and assigned in the app's Users & roles page, so access is managed in two places. The user wants Auth0 to be the single place where roles and permissions are managed.

**Approach:** Auth0 RBAC assigns roles and their permissions. The access token carries the `permissions` claim (RBAC "Add Permissions in the Access Token") and a namespaced roles claim from the Post-Login Action. The API authorizes from the token alone. Opportunity owner/collaborator grants stay in the platform. This reverses AD-15, and the spine is updated in the same change.

**Decisions:**
- Permissions live in Auth0. Each Auth0 permission name equals an `Action` value, e.g. `opportunities.opportunity.create`. They replace the role→action `POLICY` map. Owner/member grants and the sales-representative exclusions stay in code and use the token's roles.
- No "holds a role" filter on other users: any provisioned user can be found in people search and added as a collaborator.
- A developer seed script (`backend/scripts/seed_auth0.py`, run by hand with a Machine-to-Machine app's credentials) creates the API permissions, RBAC settings, nine roles, role→permission links and optional user role assignments in Auth0. It only adds, never removes. The app itself never calls the Management API. (Added by the user on 2026-10-06 during implementation.)
- Users & roles becomes read-only. It shows each user's roles from a display-only cache that is refreshed from their token at sign-in, so roles are shown as of each user's last sign-in. The cache is never used for authorization or filtering. Roles are edited in the Auth0 dashboard, and the page links there.

## Boundaries & Constraints

**Always:** Token validation is unchanged (RS256, JWKS, `iss`, `aud`, `exp`). Claims must be lists of strings; unknown or malformed values are ignored and logged with the user id. A missing claim means none granted, never a 401. `/api/v1/me` returns `roles` and `permissions`. Users are still provisioned locally on first sign-in. The cache is rewritten only when the token's roles differ from it. README Auth0 setup and AD-15 are updated.

**Never:** No Auth0 Management API calls from the app (the seed script is a dev tool). No per-Opportunity data in Auth0. No authorization or filtering from the cache. No role editing in the app. No new role trace events; existing `identity.user.role_assigned/removed` history stays readable.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Permission granted | `permissions` has `opportunities.opportunity.create` | can create an Opportunity | N/A |
| Role without permission | roles `[presales_engineer]`, no permissions | create returns 403; owner/collaborator access still works | 403 problem+json |
| Claims absent | valid token, no roles/permissions claims | no roles, no permissions, no-access page | N/A (not 401) |
| Unknown values | `intern` role, `foo.bar.baz` permission | ignored, warning logged | N/A |
| Sales rep on Opportunity | roles `[sales_representative]`, collaborator | adds Sources; editing Requirements returns 403 | 403 |
| Role changed in Auth0 | admin removes a role | takes effect, and the cache updates, when the user's next token is issued | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/identity/application/authentication.py` -- `_identity()`/`TokenIdentity`: parse `permissions` and `https://pre-sales-agent/roles` next to name/email
- `backend/app/modules/identity/application/provisioning.py:49-80` -- `provision_or_load`: roles and permissions from the token; sync the cache when it differs; keep unknown-value filtering
- `backend/app/modules/identity/domain/policy.py` -- `Principal` gains `permissions: frozenset[Action]`; role grants use `action in permissions`; delete `POLICY`; keep `RELATION_EXCLUDED_ROLES`, `OWNER_GRANTS`, `MEMBER_GRANTS`
- `backend/app/modules/identity/application/authorize.py` -- caller of the policy; update for permissions
- `backend/app/modules/identity/actions.py` -- remove `USER_ASSIGN_ROLE`/`USER_REMOVE_ROLE`
- `backend/app/modules/identity/adapters/repository.py` -- drop `_HAS_ROLE` from `search_users`/`user_names`; delete `add_role`/`remove_role`/`lock_admin_holders`; add a cache replace (delete + insert for one user)
- `backend/app/modules/opportunities/application/opportunities.py:401-404` -- remove the "holds a role" collaborator check and `InvalidCollaboratorError` if unused
- `backend/app/modules/identity/application/role_admin.py`, `api/admin_routes.py` -- keep list/get; delete assign/remove and their routes
- `backend/app/modules/identity/domain/roles.py` -- docstring; values must match Auth0 role names
- `backend/app/modules/identity/application/profile.py` -- `Me` adds `permissions: list[str]` (sorted); `CurrentUser` exposes them
- `backend/app/modules/opportunities/application/opportunities.py:145-155`, `gaps/application/gaps.py:194` -- keep: they read `actor.roles`, which now come from the token
- `web/src/lib/navigation.ts` (`isAdmin`, `visibleNav`), `web/src/lib/shortcuts.ts:36` (`canCreateOpportunity`) -- take `me.permissions` (`identity.user.list`, `opportunities.opportunity.create`); callers: `app/admin/page.tsx`, `app/admin/users/page.tsx`, `opportunities/list-page.tsx`, `opportunities/new/page.tsx`, `shell/command-palette.tsx`, `shell/sidebar.tsx`. `landingFor` and `access-gate.tsx` stay role-based
- `web/src/components/admin/user-inspector.tsx`, `users-table.tsx`, `web/src/app/admin/users/actions.ts` -- remove role checkboxes and actions; add "Manage roles in Auth0" link and an "as of last sign-in" note
- `README.md:~190-205` -- Action adds the roles claim; RBAC setup lists the permissions per role from today's `POLICY`
- `ARCHITECTURE-SPINE.md:205` -- AD-15

## Tasks & Acceptance

**Execution:**
- [x] `authentication.py` -- parse both claims -- token is the authorization source
- [x] `policy.py`, `authorize.py`, `actions.py` -- permissions replace `POLICY`; exclusions stay role-based
- [x] `provisioning.py`, `repository.py` -- token-built `Principal`; cache sync only on change
- [x] `repository.py`, `opportunities.py`, `user_search.py` -- drop the role filter for search and collaborators
- [x] `role_admin.py`, `admin_routes.py`, `identity/api/user_routes.py` (`/me`) -- read-only admin; `/me` adds `permissions`
- [x] `web/src/lib/api/schema.d.ts` -- `npm run gen:api` against a fresh local backend
- [x] web admin + `navigation.ts` -- read-only page, permission-based gates
- [x] `README.md`, `ARCHITECTURE-SPINE.md`, `roles.py` -- document the Auth0 setup and reversed AD-15
- [x] `backend/tests/auth_tokens.py` + `test_auth.py`, `test_authorize.py`, `test_role_admin.py`, `test_opportunities.py`, `test_provisioning.py` (role tests seed via token, not `identity_user_roles`); web tests -- tokens carry roles/permissions; cover the I/O matrix

**Acceptance Criteria:**
- Given a user with `identity.user.list` in Auth0 and no cached roles, when they sign in, then the read-only Users & roles page opens and shows their roles.
- Given user B last signed in with `[commercial]`, when an admin opens Users & roles, then B shows "Commercial" as of B's last sign-in, with no edit controls.
- Given a provisioned user with no roles, when an owner searches and adds them as a collaborator, then it succeeds.
- Given the backend suite run against `psa_test`, then it passes, and no authorization decision reads `identity_user_roles`.

## Implementation Notes

## Spec Change Log

- 2026-10-06: user asked to seed the Auth0 data. Added `backend/scripts/seed_auth0.py` + `tests/test_seed_auth0.py` and a README note; frozen Decisions and Never updated at the user's request.

## Review Triage Log

| # | Source | Finding | Verdict | Route | Evidence |
|---|---|---|---|---|---|
| 1 | VG, BH | Role→permission mapping duplicated in `tests/auth_tokens.py` (and web test copy), unchecked against `seed_auth0.ROLE_PERMISSIONS` | medium | patch | Editing the script's mapping leaves every authorization test green; derive the backend copy from the script |
| 2 | BH | Cut-over drops roles held only in `identity_user_roles` | medium | patch (README) | `provision_or_load` overwrites the cache from the token; users without Auth0 roles get the no-access page |
| 3 | BH, ECH | Last-administrator safeguard gone; no recovery documented | low | patch (README) | `LastAdministratorError` deleted; Auth0 allows removing the last admin; `seed_auth0 --assign` recovers |
| 4 | ECH | `replace_roles` can deadlock on concurrent different role sets | low | patch | Two transactions deleting/inserting each other's rows; one-line user row lock serialises them |
| 5 | ECH | Seed `--assign` email case; multiple accounts sharing an email all get roles | low | patch | `users-by-email` matched as typed; loop assigns to every match |
| 6 | BH | Vestigial `const users = initialUsers` | low | patch | Direct deletion |
| 7 | BH | Cache refresh rolled back when the request fails | low | reject | Every web page calls `/me`, which succeeds and refreshes the cache; fixing needs a separate transaction |
| 8 | BH, ECH | ETag unchanged when cached roles change | low | reject | No client sends `If-None-Match`; removing it changes public surface |
| 9 | BH | Unknown-role warning on every request | low | reject | Required by spec ("ignored and logged with the user id"); tenant only holds app roles |
| 10 | BH | Extra DB query per request | false | reject | `load_roles` already ran on every request before this change |
| 11 | BH | Search exposes every provisioned user | false | reject | Frozen decision: any provisioned user can be found and added |
| 12 | BH | Permissions untyped (`list[str]`) | low | reject | Unknown values filtered server-side; web uses named constants |
| 13 | BH, ECH | Seed script: no warning for extra permissions; single-page reads; `assert` under `-O` | low | reject | Roles hold ≤2 permissions; additive-only by design; dev tool |
| 14 | BH | Test helpers imported across modules; unused `engine` param | low | reject | Developer-only, no failing scenario |
| 15 | BH | Missing tests (cache privacy, roles-without-permissions-claim) | false | reject | Cache holds role names only; `test_a_role_without_permissions_grants_nothing_on_its_own` and owner-access test cover the missing claim |
| 16 | BH, ECH | Web polish (`auth0UsersUrl` region/port, sr-only spacing, doc line length) | low | reject | Lint passes; legacy US tenants have no region; ports not used for Auth0 domains |
| 17 | ECH | A relation-only permission granted to a role in Auth0 applies on every Opportunity and bypasses sales-rep exclusions | low | reject | Needs deliberate Auth0 misconfiguration; guard would reintroduce part of `POLICY`. Flagged to the user |
| 18 | ECH, VG | Access gate role-based while API accepts permission-only users | low | reject | Spec keeps `access-gate.tsx` role-based; permission-only users need direct Auth0 user permissions, which the setup doesn't use |
| 19 | ECH | Older still-valid token flips the cache back | low | reject | Display-only cache; self-corrects on the next request with the newer token |
| 20 | ECH | Missing roles claim wipes the cache | false | reject | The cache mirrors the token, which then carries no roles; authorization agrees |

## Design Notes

Post-Login Action addition (README):

```js
api.accessToken.setCustomClaim(`${namespace}roles`, event.authorization?.roles ?? []);
```

The Auth0 API needs "Enable RBAC" and "Add Permissions in the Access Token". Role-to-permission seed, from today's `POLICY`: `platform_administrator` → `identity.user.list`, `opportunities.opportunity.read`; `presales_engineer` → `identity.user.search`, `opportunities.opportunity.create`; `head_of_delivery` → `opportunities.opportunity.read`.

## Verification

**Commands:**
- `cd backend && uv run pytest -q` with both DB URLs on `127.0.0.1:5432/psa_test` -- expected: all pass
- `cd backend && uv run ruff check . && uv run mypy app` -- expected: clean
- `cd web && npm test && npm run lint` -- expected: all pass

**Manual checks:**
- In Auth0, give your user `presales_engineer` with its permissions. Sign out and back in, and confirm you can create an Opportunity and that the admin page shows your cached roles.
