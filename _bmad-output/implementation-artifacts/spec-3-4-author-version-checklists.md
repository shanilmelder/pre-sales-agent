---
title: 'Story 3.4: Author and version Checklists'
type: 'feature'
created: '2026-10-21'
status: 'done'
baseline_commit: 'ec7f8a891da926eadceb3a180639e77ad1ff766a'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-3-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Domain experts have nowhere to record the questions and known risks every deal must cover, so Gap detection (Epic 4) cannot ask what experts know must be asked, and mandatory security controls aren't captured as policy.

**Approach:** The `knowledge` module gains versioned Checklists: a mutable header that holds one draft (saved with `If-Match` on every blur), immutable published versions with items that keep stable item IDs, plus Publish, Retire with a reason, and `knowledge.public.find_applicable_checklists`. The web app gets a Knowledge → Checklists sub-tab with a list, an inspector, an item editor and version history.

## Boundaries & Constraints

**Always:**
- Tables are `knowledge_checklists`, `knowledge_checklist_scope_tags`, `knowledge_checklist_versions` and `knowledge_checklist_items`. Version and item rows are insert-only (psa_app gets SELECT, INSERT and no UPDATE/DELETE).
- Writers are `engineering_reviewer`, `pm_reviewer`, `security_reviewer` and `platform_administrator`. Any of them may edit any Checklist. Every role with a role can read, and other roles get 403 on writes.
- Every write requires `If-Match`. Missing → 428. A stale `row_version` → 412 with the concurrent-edit message, and nothing is overwritten.
- Trace events `knowledge.checklist.published` (version, item count, mandatory count) and `knowledge.checklist.retired` use `opportunity_id = null` and carry ids and counts only, never text or the reason.
- Scope tags and an item's affected area must be active catalogue entries. Choosing a retired one is a 422, but existing references keep resolving and show "Retired". The affected area may be an Integration Type or a Work Package. Scope accepts Integration Types only.
- Mandatory is always shown as an icon plus a "Mandatory" label, never colour alone. Actions a user can't take are hidden.

**Decisions:**
1. The draft lives on the header as one JSON document: name, domain, products, industry, Integration Type ids, and items in order. Each blur saves the whole draft with `PUT …/draft` and `If-Match`. Publish copies it into a new version, its item rows and the header's published scope columns and tags. So the published version and its scope stay in use until Publish.
2. A new item gets a UUIDv7 when it is added. An item carried over from the latest published version keeps its ID, and deleted items are simply absent from the next version.
3. A Checklist has a required `name` (max 200), used in the list.
4. Products and industry are free text, trimmed and de-duplicated case-insensitively, matching how Opportunities store them.
5. Retiring is final in this story (no reactivate), and a never-published draft can be retired. Retire discards the draft.
6. The route is `/knowledge/checklists`, and Sources moves behind a sub-tab link.

**Never:**
- No Gap detection changes (Epic 4 consumes this) and no coverage view (3.5).
- No reactivate, discard-draft or delete endpoints.
- No per-author locking beyond `row_version`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Create | Writer presses `c`, gives a name and domain | 201: header plus a draft with no version, `row_version` 1 | 403 for a non-writer, 422 for a bad name or domain |
| Save draft | `PUT draft` with the current `If-Match` | Draft replaced, `row_version` + 1 | 412 if stale, 428 if `If-Match` is missing, 422 for a retired or unknown tag |
| Publish | Draft has ≥1 scope tag and ≥1 item | New version N+1, items inserted, draft cleared, trace event | 422 "needs a scope tag and an item" |
| Edit published | `POST …/draft` on a Checklist with no draft | Draft seeded from the latest version with the same item IDs | 409 if a draft already exists |
| Retire | Reason (1–500 chars) | Status retired, draft cleared, trace event, versions still readable | 409 if already retired |
| Find applicable | products / industry / Integration Type ids | Latest published version of each active Checklist matching any of them (names trimmed and case-insensitive), with domain, item IDs and version | Retired or never-published Checklists are excluded |

</frozen-after-approval>

## Code Map

- `backend/app/modules/knowledge/adapters/models.py` -- copy `CatalogueEntryRow` :32 (status/reason CHECKs :40,:42), `SourceTagRow` :101 (scope tags), `SourceVersionRow` :114. Add `ChecklistRow` (name, domain CHECK, products/industry, draft JSONB nullable, status, retired_reason, `RowVersioned`), `ChecklistScopeTagRow`, `ChecklistVersionRow` (PK checklist_id+version, published_by, published_at, name, domain, scope snapshot JSONB), `ChecklistItemRow` (PK checklist_id+version+item_id, ordinal, kind, text, why_it_matters, affected_entry_id nullable FK, impact CHECK High|Medium|Low, mandatory).
- `backend/migrations/versions/20261021_0036_knowledge_checklists.py` -- rev `0036_knowledge_checklists`, down `0035_knowledge_chunks`. Grants as in `20261013_0025_knowledge_sources.py:120-127`: header S/I/U, tags S/I/D, versions and items S/I only.
- `backend/app/modules/knowledge/adapters/checklist_repository.py` (new) -- `bump` with `WHERE row_version = expected RETURNING` (pattern `repository.py:178`, `source_repository.py:303`), `next_version`, scope-tag set (`set_tags` :247), `entry_kinds` (`source_repository.py:208`) to check each entry's kind.
- `backend/app/modules/knowledge/domain/checklists.py` (new) -- pure rules: enums, name/product/industry normalisation (reuse `opportunities` `rules.normalize_products` behaviour without importing that module), publishable check, retire reason (reuse `rules.retire_reason`).
- `backend/app/modules/knowledge/application/checklists.py` + `checklist_models.py` (new) -- service mirroring `catalogue.py` (`_expected` :88, `_stale` :82, `edit_entry` :222, `retire_entry` :281). Validate tags via `validate_catalogue_ref` (:383). Views list retired tags as in `sources.py:231-240`. Trace via `trace.append` (`catalogue.py:207`).
- `backend/app/modules/knowledge/api/checklist_routes.py` (new) -- `/api/v1/knowledge/checklists`: list, get, versions, `GET versions/{n}`, create, `POST draft`, `PUT draft`, publish, retire. `_IF_MATCH`/`_with_etag`/`_WRITE` as in `routes.py:45-64`. Mount where `source_routes` is mounted.
- `backend/app/modules/knowledge/application/public.py` -- export the Checklist commands, views and `find_applicable_checklists(uow, *, products, industry, integration_type_ids)`.
- `backend/app/modules/identity/actions.py:35-46` -- `KNOWLEDGE_CHECKLIST_CREATE/EDIT/PUBLISH/RETIRE`. `backend/scripts/seed_auth0.py:35,70` -- grant them to the 3 reviewer roles and admin (the first reviewer grants). Update `tests/test_seed_auth0.py`, README Auth0 section :259-279 and `web/src/test/permissions.ts:5`.
- `backend/app/platform/trace/catalogue.py` (knowledge section :695) -- 2 `@register` payloads. Labels in `web/src/lib/trace.ts:63-66,99`.
- `web/src/app/knowledge/page.tsx` -- sub-tab nav (:42-49) becomes links. Add `app/knowledge/checklists/page.tsx` and `actions.ts` (copy `outcome()` :72-93 and the `If-Match` header :243 from `app/knowledge/actions.ts`).
- `web/src/lib/checklists.ts` (new) -- types, labels, `canAuthor(permissions)`. Impact labels reuse `IMPACTS` (`lib/gaps.ts:55`).
- `web/src/components/knowledge/checklists-{tab,table,inspector,item-editor}.tsx` + `mandatory-label.tsx` (new):
  - tab and table copy `sources-tab.tsx:41` and `sources-table.tsx:120` (j/k, Enter, `c`)
  - labels copy `RetiredLabel` `sources-table.tsx:79`
  - fields use `InlineField` (`opportunities/inline-field.tsx:66`)
  - the stale notice copies `source-inspector.tsx:110-154`, version history `admin/catalogue-inspector.tsx:300`, the retire input `source-inspector.tsx:579-611` + `ReasonInput`
  - tag pickers are checkbox fieldsets (`source-inspector.tsx:435-475`)
  - `npm run gen:api`

## Tasks & Acceptance

**Execution:**
- [x] models, migration 0036, `checklist_repository.py` -- tables, constraints, grants
- [x] `domain/checklists.py` + domain tests -- pure rules
- [x] identity actions, Auth0 seed and its test, README, trace payloads -- permissions and events
- [x] `application/checklists.py`, `checklist_models.py`, `public.py`, `api/checklist_routes.py` -- commands, views, `find_applicable_checklists`
- [x] `backend/tests/test_knowledge_checklists.py` -- every row of the matrix, 403 per role, 412/428, stable item IDs across versions, psa_app cannot update or delete versions or items, matching (case and trim, retired excluded)
- [x] web lib, pages, actions, components, `gen:api`, trace labels, permissions seed -- Checklists sub-tab
- [x] web tests for the table, inspector, item editor and actions -- Mandatory label, read-only role, stale notice, publish disabled until valid, axe clean

**Acceptance Criteria:**
- Given a published v1 whose draft has been edited, when `find_applicable_checklists` runs, then it returns v1's items until the draft is published, and then v2 with the carried items' IDs unchanged.
- Given a reader role on Knowledge → Checklists, then no create, edit, publish or retire controls render, and the direct API calls return 403.
- Given the inspector, then version history lists each version with its publisher and date, and selecting one shows that version read-only.

## Implementation Notes

- "Scope tag" for Publish means any scope entry: a product, the industry or an Integration Type, so industry-only Checklists (which Story 3.5 lists separately) can be published. The 422 reads "A Checklist needs a scope tag and an item before it can be published."
- Saving a draft checks shape and length only (an item just added has blank text). Publish also needs every item's text and "why it matters" (422 "Every item needs its text and why it matters before publishing."). The Checklist view carries `draft.publishable` and `draft.publish_problem`, which drive the disabled Publish button.
- Impact values are lowercase `high | medium | low`, the same as the Gap `Impact` that Epic 4 will copy them into. Labels reuse `IMPACTS`.
- A draft item `id` must be null (new: the server assigns a UUIDv7 on save) or an id from the current draft or any published version of the same Checklist (422 otherwise), so an item removed and re-added keeps its id.
- A retired Integration Type or affected area that the stored draft already references can be saved again (existing references keep resolving). Choosing a new retired one is a 422.
- New 409 codes: `knowledge_checklist_retired`, `checklist_draft_exists`, `checklist_no_draft` (saving or publishing with no draft).
- `knowledge.checklist.retired` carries `version` (null when never published) and `discarded_draft`. Neither event carries text or the reason. No event is written on create or draft save; the spec names only these two events.
- `find_applicable_checklists` filters the active, published headers in Python (casefold on trimmed names). The header's published scope columns and tags change only on Publish.
- `industry` is a single optional string, as on Opportunities.

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Evidence / route |
|---|---|---|
| A change made while a blur-save is in flight (Mandatory, Kind, Add item, Publish) is silently dropped | medium | `run()` returns early when `locked`, and the controls are disabled while pending (`checklist-inspector.tsx` `run`, `checklist-item-editor.tsx` `commit`). Blur then click hits this. Patch: queue the latest change and replay it on the saved Checklist. |
| Version history refetches the whole Checklist on every blur-save | low | Effect keyed on `rowVersion`; versions change only on Publish. Patch: key on `current_version`. |
| Version history stuck on "Loading…" when the load fails | low | Effect sets versions only on `ok`. Patch: show a failure message. |
| `checklists.py` docstring says every write is traced | low | Only Publish and Retire are traced, per spec. Patch the docstring. |
| Republish with a changed Integration Type scope untested (`set_tags` delete, `open_draft` carry-over) | medium | Verification-gap, pre-verified. Patch: republish test. Also cover `PUT draft`/publish on a retired Checklist → 409. |
| Inspector move, remove, add and Integration Type toggle never exercised | medium | Verification-gap, pre-verified. Patch: inspector tests. |
| No way to discard a draft | false | Frozen intent: "No reactivate, discard-draft or delete endpoints." |
| Drafts and all items returned to every role; list payload heavy | low | Readers may read Checklists; drafts aren't confidential by intent. Fix adds role branches. Rejected. |
| Pydantic `max_length` looser than the domain rules; UI `maxLength` doubled | low | Deliberate headroom: the domain rule returns the sentence to show; the 422 is still raised. Rejected. |
| Publish doesn't re-check that tags and areas are still active | low | "Existing references keep resolving" (Always); a retired entry can't be chosen for new Opportunities. Rejected. |
| `open_draft` raises "draft exists" for a never-published Checklist | false | Unreachable: a never-published active Checklist always has a draft (the retired check runs first). |
| Per-id `validate_catalogue_ref` loop; `find_applicable` filters in Python | low | ≤50 tags and ≤200 items per save; few Checklists. Fix is a restructure. Rejected. |
| No index on scope tag `entry_id` / item `affected_entry_id` | low | No reverse lookup exists yet (Story 3.5 can add one). Rejected. |
| `parseProducts` lower-cases, the API case-folds | low | Differs only for rare characters; the API normalises anyway. Rejected. |
| `loadChecklistVersion` maps 403 to a generic error | low | Every role can read versions; 403 means no role at all. Rejected. |
| ITEMS_MAX/TAGS_MAX/duplicate-id 422s untested at the API | low | Domain tests cover the rules. Rejected. |
| Out-of-order responses when viewing two versions quickly | low | Needs two clicks within one request; fix adds a sequence guard. Rejected. |
| Restoring an earlier item by id with a now-retired area is a 422 | low | Only reachable through the API (the UI re-adds as a new item). Rejected. |
| `find_applicable_checklists(products="x")` splits a string | low | Typed `Iterable[str]`; mypy catches the call. Rejected. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest` -- all pass. Use `PSA_DATABASE_URL` on `127.0.0.1:5432/psa_test` (NEVER the dev `psa` DB). Run `alembic upgrade head` there first via `PSA_MIGRATIONS_DATABASE_URL`.
- `npm run gen:api` -- against a fresh local uvicorn or a dumped `app.openapi()`, not the Docker `api`.
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- all pass.
