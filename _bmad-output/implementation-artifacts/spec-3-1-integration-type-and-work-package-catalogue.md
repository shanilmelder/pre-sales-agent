---
title: 'Story 3.1: Integration Type and Work Package catalogue'
type: 'feature'
created: '2026-10-06'
status: 'done'
baseline_commit: 'a2a7431c4acb3252525467791b085d534f7105b2'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Checklists, Assessment lines, Estimate lines and Actuals have no shared classification, so the same work is named differently in each place (FR-65).

**Approach:** A new `knowledge` module owns a versioned catalogue of Integration Types and Work Packages. Administrators maintain it on Admin → Catalogue; every other module refers to entries by ID through `knowledge/application/public.py`.

## Boundaries & Constraints

**Always:**
- **Tables (AD-2):** `knowledge_catalogue_entries` (UUIDv7 `id`, `kind` `integration_type | work_package`, `code`, `status` `active | retired`, `retired_reason`, `row_version`, `created_at`) and immutable `knowledge_catalogue_entry_versions` (`entry_id`, `version`, `name`, `definition`, `changed_by`, `changed_at`; unique `(entry_id, version)`). `psa_app` gets SELECT, INSERT, UPDATE on entries and SELECT, INSERT only on versions. `code` never changes after creation.
- **Public API:** `list_catalogue(kind, include_retired)`, `get_catalogue_entry(id, version?)` (current version when omitted; retired entries still resolve, flagged retired), `validate_catalogue_ref(id)` (true only for an active entry). Other modules never read the tables.
- **Create:** admin only; code, name, definition required (trimmed; code 1–40, name 1–120, definition 1–2,000). Version 1. A code or name equal (case-insensitive) to an active entry of the same kind → 409 `catalogue_duplicate`, message "An active Integration Type with this name already exists" (or "Work Package").
- **Edit:** name and/or definition, `If-Match` required (428 if missing, 412 if stale); a changed value saves a new version and bumps `row_version`, an unchanged one is a 200 no-op; the same duplicate rule applies. Earlier versions stay readable.
- **Retire / reactivate:** admin only; retire needs a reason (1–500 characters) and works on any active entry. Retired entries can't pass `validate_catalogue_ref` but every existing reference still resolves, shown with a "Retired" label. Reactivating re-runs the duplicate check. Both use `If-Match`.
- **Who:** writes use new identity actions for the platform administrator only (403 otherwise); reads (list, get, versions) are open to any user with a role.
- **Trace (opportunity_id null):** `knowledge.catalogue_entry.created`, `.updated` (old and new version numbers), `.retired`, `.reactivated`. Ids and numbers only, never name or definition text. Labels added to `web/src/lib/trace.ts`.
- **Web:** Admin gets a Catalogue section next to Users. Two groups (Integration Types, Work Packages) of 32px rows with code, name, current version and status pill; `j`/`k` and Enter open the inspector; `c` opens the create form. Inspector edits name and definition inline (Enter or blur saves, Esc reverts), shows version history, Retire (with reason) and Reactivate. A 412 shows "Changed by {name} since you opened it." with Reload. Empty state: "No catalogue entries yet. Press c to add an Integration Type or Work Package." Axe checks as for Users.

**Never:** No tagging UI, no Checklist or Knowledge Source work, no seed data, no use of catalogue IDs by other modules yet (Stories 3.4 and later), no hard delete.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create | Admin, new code and name | 201, version 1, one `created` event | N/A |
| Duplicate | Name matches an active entry of the same kind | Nothing saved | 409 with the "already exists" message |
| Same name, other kind | Name exists only under the other kind | Created | N/A |
| Edit | Current `If-Match`, new definition | Version 2, `row_version` +1, `updated` event (1 → 2) | N/A |
| Stale edit | Old `If-Match` | Nothing overwritten | 412; none → 428 |
| Retire | Active entry, reason | `retired`, event; `validate_catalogue_ref` false; `get_catalogue_entry` still resolves | Empty reason → 422 |
| Reactivate | Retired entry whose name is now used by an active one | Stays retired | 409 duplicate |
| Non-admin write | Any other role | Nothing changed | 403 |
| Read | Any role, `include_retired` false | Active entries only | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/gaps/` -- structure to copy (`adapters/{models,repository}.py`, `application/{public,...}.py`, `domain`, `api/routes.py`); `RowVersioned` from `app/platform/concurrency.py`, `new_id()` from `app/platform/ids.py`.
- `backend/app/modules/gaps/application/questions.py` and `intake/application/requirement_edits.py` -- command shape: `authorize` → rules → `row_version` check → write → `trace.append`.
- `backend/app/modules/gaps/api/routes.py` -- route helpers (`_responses`, `If-Match` header, `etag`); register the new router in `backend/app/main_api.py` after `assessments_router`.
- `backend/migrations/versions/20261005_0018_assessments_cancel.py` -- latest; new `0019_knowledge_catalogue` revises it (template for grants: `0013_estimates_assumptions.py`). Add the models import in `backend/migrations/env.py`.
- `backend/app/modules/identity/actions.py`, `identity/domain/policy.py` (admin-only like `USER_LIST`); update `tests/test_authorize.py`.
- `backend/app/platform/trace/catalogue.py` -- add four payloads; `tests/test_trace_catalogue.py` checks them.
- `backend/pyproject.toml` -- add a `knowledge` import-linter contract (identity public API only).
- Web: `web/src/app/admin/users/{page.tsx,actions.ts}` and `components/admin/{users-admin,users-table,user-inspector}.tsx` as the pattern (keyboard nav in `users-table.tsx`); `components/opportunities/inline-field.tsx` for inline edit; `lib/trace.ts` labels; regenerate `web/src/lib/api` with `npm run gen:api`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261006_0019_knowledge_catalogue.py` -- two tables, constraints, grants -- schema
- [x] `backend/app/modules/knowledge/{domain,adapters,application,api}` -- rules (pure, unit-tested), models, repository, commands, public API, routes -- module
- [x] identity `actions.py` + `policy.py`, trace `catalogue.py`, `main_api.py`, `migrations/env.py`, `pyproject.toml` -- wiring
- [x] `backend/tests/test_knowledge_*.py` -- the I/O matrix, 403, 412/428, retired resolution, architecture and trace catalogue tests
- [x] `web/src/app/admin/catalogue`, `components/admin/catalogue-*.tsx`, `lib/catalogue.ts`, admin sub-navigation, `lib/trace.ts`, regenerated client -- UI and vitest tests incl. axe

**Acceptance Criteria:**
- Given an admin on Admin → Catalogue, when they create, edit and retire an entry from the keyboard, then each step shows in the list, the inspector and its version history.
- Given a retired entry referenced elsewhere, when `get_catalogue_entry` is called, then it returns the name with `retired` true.
- Given any role, when it lists the catalogue, then it gets 200; given a non-admin write, then 403.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| 409 text says "name" when the code clashed (blind, edge) | medium | patch | `duplicate_message` had no field; fixed with `duplicate_field`, test asserts "code" and "name" texts |
| `version` query unbounded, int4 overflow (blind, edge) | medium | patch | Only `ge=1`; added `le=2_147_483_647`, test for 0 and 99999999999 |
| NUL character in fields gives DB error (edge) | medium | patch | Postgres text rejects NUL; `_bounded` now raises the 422 |
| Rename to own name in another case untested (gap) | medium | patch | Test added; `ignore=entry_id` is what allows it |
| Repeated retire/reactivate, stale unchanged edit, oversize If-Match untested (gap) | medium | patch | Test added asserting events, `row_version` and 412 |
| Create form 403 not announced (blind) | low | patch | One-line `announce` added |
| Docstring says every write takes the per-kind lock, retire doesn't (edge) | low | patch | Retiring only shrinks the active set so no lock is needed; docstring corrected |
| No DB unique-index backstop / no concurrency test for the duplicate rule (blind, gap) | medium (unverified) | defer | Lock is the only guard today; a partial unique index on active (kind, lower(code)) and (kind, lower(name)) would settle it |
| 412 "Changed by" names last editor after another admin retired/reactivated (blind, edge, implementer) | low | reject | Needs the actor stored for status changes (schema plus API); rare with few administrators; noted for the user |
| Retire reason / who / when lost after reactivate (blind) | low | reject | Spec stores the reason on the entry and keeps text out of the trace by design |
| Near-duplicate names by inner whitespace or Unicode form (blind) | low | reject | Fix adds normalisation rules beyond the spec's "duplicates" |
| Reads use a role check, not an Action (blind) | low | reject | Spec: reads open to every user with a role; no policy row needed |
| Other modules could import knowledge internals (blind) | false | reject | `test_architecture.py` scans every module for other modules' domain/adapters imports |
| Renaming a retired entry to an active name gives 409; retired entries editable (edge, blind) | low | reject | Spec silent; rejecting is the conservative reading and reactivation re-checks anyway |
| List has no paging (blind); limits duplicated in web (blind); inner join hides versionless rows (blind) | low | reject | Not in the story; entries always get version 1 in the same transaction |
| Invalid Date crash, create cancelled in flight, pane toggle, selection after refresh, `c` on non-admin page, 403/404 after 412 (edge, web) | low | reject | Unlikely paths with a small admin group; fixes add state and branches |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy app && uv run lint-imports` -- expected: clean
- `cd backend && uv run alembic upgrade head && uv run alembic check && uv run pytest` -- expected: pass, no model/migration drift
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: pass
