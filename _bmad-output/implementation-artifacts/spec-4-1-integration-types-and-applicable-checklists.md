---
title: 'Story 4.1: Integration Types in scope and applicable Checklists'
type: 'feature'
created: '2026-10-23'
status: 'done'
baseline_commit: '293bae34ef49b41e6ddfd6937b331b77c881b9e1'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-4-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-redesign-gaps-tab.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Requirements can't be tagged with catalogue Integration Types, so nothing can tell which expert Checklists apply to an Opportunity. The Gaps tab also gives no sign when tags are missing or the Knowledge Base is thin.

**Approach:**
- Add a human-owned Integration Type tag set per Requirement, edited in the Requirement inspector with `If-Match`. Extraction never touches it.
- Add `knowledge.public.get_coverage`.
- Add a Gaps context read with three parts: the applicable Checklists, the count of untagged integration Requirements, and the uncovered scope. The Gaps tab renders it as a header strip and two banners.
- Style the new pieces with the new mockup's patterns (`new-mockups/Presales Agent Design Spec (standalone).html`). The mockup draws none of these pieces itself.

**Decisions:**
- **Base:** the branch is cut from `main`, not from open PR #70.
- **Coverage:** backend plus banner only. The banner links to Knowledge → Sources, filtered. The Coverage grid page stays with Story 3.5.

## Boundaries & Constraints

**Always:**
- **Storage:** tags live in a new table `intake_requirement_integration_types` (`requirement_id`, `entry_id`, `tagged_by`, `tagged_at`, PK on both ids). Migration `0037`, with `psa_app` grants.
- **Extraction:** extraction, reconcile and `propose_requirement_change` never read or write the tag table.
- **Saving:** `PUT /opportunities/{id}/requirements/{rid}/integration-types` with body `{integration_type_ids}` replaces the set.
  - Requires `If-Match` on the Requirement's `row_version`, and bumps it.
  - Authorised with the existing `Action.REQUIREMENT_EDIT`, so a sales rep gets 403.
  - Appends one `intake.requirement.integration_types_tagged` trace event with payload `{added, removed}` (entry ids), registered in `platform/trace/catalogue.py`.
  - An unchanged set returns 200 with no event and no bump.
- **Validation:**
  - New ids must be active `integration_type` catalogue entries. Otherwise the request fails with 422 `validation_error`.
  - An already-stored retired tag may stay but can't be re-added once removed. This mirrors Knowledge Source tags.
  - At most 50 ids.
- **Split and merge:** split children inherit the parent's tags, and a merge takes the union. A classification change keeps the tags.
- **Views:**
  - The `Requirement` view gains `integration_types: [{id, code, name, retired}]`.
  - `RequirementList` gains `untagged_integration_count`: the number of active Requirements classified `integration` that have no tags.
- **`knowledge.public.get_coverage(uow, *, products, integration_type_ids)`** returns per-product and per-type `ready: bool`.
  - Ready means at least one active Source that matches (product trimmed and case-insensitive, or by tag) and whose latest version's embed status is `ready`.
  - It does no authorisation check, like `find_applicable_checklists`.
- **Gaps context read:** `GET /opportunities/{id}/gaps/context`. It is readable by anyone who can read the Opportunity, sales rep included, and returns:
  - `applicable_checklists`: `[{checklist_id, version, name, domain}]` from `find_applicable_checklists`, called with the Opportunity's `products`, its `industry` and the union of tags on its active Requirements.
  - `untagged_integration_count`.
  - `uncovered`: `{products: [str], integration_types: [{id, name}]}`.
  - Cross-module calls go only through `public.py`. Update the import-linter contracts.
- **Gaps tab** (under the existing header row, above `DetectionStatus`). The two banners follow DESIGN.md's banner pattern: `rounded-[10px]`, `px-3.5 py-2.5`, 13px medium, an icon, the text, and a right-aligned semibold link.
  - **Checklists strip:** a meta label "Applicable Checklists", then one chip button per Checklist reading "{name} · v{version}". With none, it reads muted "No Checklists apply yet — tag integration Requirements or set products and industry." Selecting a chip opens the right pane with that version read-only (header "{name}" and "Version {n} · {domain}", then the items with their Mandatory or Optional pills). Esc closes it, and focus returns to the chip.
  - **Untagged banner** (gap/amber tint, `role="status"`, shown when the count is above 0): "{N} integration Requirement(s) have no Integration Type — Checklists may not apply", with the link **Show them** → `/opportunities/{id}/requirements?untagged=integration`. Use "has" when N = 1.
  - **Coverage banner** (primary/info tint, `role="status"`, shown when anything is uncovered): "No documentation for {parts} in scope — Gap detection may be incomplete". `{parts}` joins "{n} integration type(s)" and "{n} product(s)" with " and ", leaving out zero parts. The link **Open Knowledge Sources** → `/knowledge?integration_type={first uncovered type id}`, or else `?product={first uncovered product}`.
- **Requirements tab:** `?untagged=integration` lists only the integration Requirements with no tags. A `role="status"` bar reads "Showing {N} integration Requirements with no Integration Type", with a **Show all** link back to the plain tab.
- **Knowledge → Sources:** `?integration_type=` and `?product=` seed its initial filters.
- **Requirement inspector:** a new "Integration Types" section after Evidence.
  - Editors get a checkbox fieldset (the `source-inspector.tsx` pattern). Each toggle saves at once with `If-Match`. A 412 shows the existing stale handling.
  - Retired stored tags show a "Retired" label.
  - Viewers without edit rights see a read-only list, or "None".
- Existing tokens and `ui/*` only. Light and dark both work. Copy uses glossary terms.

**Never:**
- Enqueuing `gaps.detect_gaps`, raising Checklist Gaps, or changing detection (Story 4.2).
- A Knowledge → Coverage page, route or grid (Story 3.5).
- Versioning tags inside `intake_requirement_versions`, or letting agents set tags.
- Changes to other tabs' layouts, the shell, the tokens or `ui/*` beyond what's listed here.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Tag | PSE, `[SAP]`, If-Match matches | 200 with tags; event `{added:[SAP],removed:[]}`; `row_version` +1 | N/A |
| Stale tag | If-Match is old (extraction bumped it) | No change | 412 → stale notice |
| Sales rep | PUT | View shows tags read-only | 403 `forbidden` |
| Retired / wrong kind | Adds a retired type or a Work Package | No change | 422 |
| Re-extraction | Tagged unlocked Requirement re-versioned | Tags unchanged | N/A |
| Split | R3 tagged `[SAP]` split in two | Both children `[SAP]` | N/A |
| No scope | No products, no industry, no tags | Strip "No Checklists apply yet…"; no banners | N/A |
| Untagged | 3 integration Reqs, 1 tagged | Banner "2 integration Requirements have no Integration Type…" | N/A |
| Uncovered | 2 types in scope, neither Ready | Banner "No documentation for 2 integration types in scope…" | N/A |
| Context read fails | API error | Gaps list still renders; strip and banners hidden | Logged, no customer text |

</frozen-after-approval>

## Code Map

Backend (`backend/app/`):
- `modules/intake/adapters/models.py:160` -- `RequirementRow`. Add `RequirementIntegrationTypeRow` next to it.
- `modules/intake/application/requirement_edits.py:121,138,165,216` -- `_authorized`, `_expected` and the `edit_requirement` pattern (UoW, If-Match, trace) to copy for `tag_requirement_integration_types`. Split and merge also live here: add tag inheritance.
- `modules/intake/application/requirements.py:86` -- `requirement_views`: batch-load the tags and resolve them via `knowledge.public.get_catalogue_entry`.
- `modules/intake/application/models.py:114,148` -- the `Requirement` and `RequirementList` views.
- `modules/intake/api/routes.py:408-462` -- `_IF_MATCH`, `_with_etag` and `_edit_responses`. Add the PUT route here.
- `modules/intake/application/public.py` -- export `integration_scope(uow, opportunity_id) -> (tag_ids, untagged_count)` for gaps.
- `modules/knowledge/application/{catalogue.py:365-383, checklists.py:619, sources.py:315}` -- `validate_catalogue_ref`, `get_catalogue_entry`, `find_applicable_checklists`, and the `list_sources` filters to model `get_coverage` on. Readiness comes from the `knowledge_source_embeds.status` (`adapters/models.py:167`) of the latest version. Export from `knowledge/application/public.py`.
- `modules/gaps/api/routes.py:62`, `modules/gaps/application/models.py:316` -- add the `/gaps/context` route and the `GapsContext` model.
- `modules/opportunities` public `get` / `readable_resource` -- `products` and `industry`.
- `platform/trace/catalogue.py:205` -- the payload `@register` pattern.
- `migrations/versions/20261021_0036_knowledge_checklists.py` -- the latest migration. New: `20261023_0037_intake_requirement_integration_types.py`.
- `pyproject.toml` `[tool.importlinter]` (intake :136, gaps :160) and `tests/test_architecture.py:91`.

Web (`web/src/`):
- `components/opportunities/requirement-inspector.tsx:463-696` -- add the section after Evidence. The picker pattern is `components/knowledge/source-inspector.tsx:435-475`.
- `app/opportunities/actions.ts:1055` -- the `editRequirement` pattern for the new `tagRequirementIntegrationTypes`.
- `components/opportunities/requirements-list.tsx` (`RequirementsSection`, status pattern at :1364) and `app/opportunities/[id]/requirements.tsx` -- the `untagged` param, and loading the active types (`app/knowledge/page.tsx:15` pattern).
- `app/opportunities/[id]/gaps.tsx`, `app/opportunities/data.ts` -- load the context in parallel with `listGaps`, then pass it to `GapsSection`.
- `components/opportunities/gaps-list.tsx:1281-1339,1416` -- the header, and the `RightPaneContent` inspector slot (the Checklist view shares that slot).
- New `components/opportunities/gaps-context.tsx` -- the strip and both banners.
- `components/knowledge/checklist-inspector.tsx:596-600,700-730` -- extract `ChecklistReadOnly` into `components/knowledge/checklist-read-only.tsx`, which the Knowledge inspector also reuses. It reads from `GET /knowledge/checklists/{id}/versions/{v}` via a server action.
- `app/knowledge/page.tsx`, `components/knowledge/sources-tab.tsx:54` -- the initial filters from the URL.
- `lib/api/schema.d.ts` -- regenerate with `npm run gen:api` against a fresh backend.

## Tasks & Acceptance

**Execution:**
- [x] Migration + `RequirementIntegrationTypeRow` -- the tag table.
- [x] `intake` command, route, payload, split/merge inheritance, view fields, `integration_scope` -- AC1.
- [x] `knowledge.get_coverage` + export -- AC4 data.
- [x] `gaps` context model + route + import-linter -- AC2-4 data.
- [x] Backend tests -- the matrix rows for tag, stale, sales rep, retired, re-extraction and split, plus coverage readiness and the context composition: `test_intake_requirement_tags.py`, `test_knowledge_coverage.py`, `test_gaps_context.py`.
- [x] `gen:api`, then the web action + inspector section + tests.
- [x] `checklist-read-only.tsx` extraction (the Knowledge inspector still passes its tests).
- [x] `gaps-context.tsx`, wired into the Gaps tab + tests for the strip, both banners, pluralisation, the failed read and the read-only Checklist pane.
- [x] The Requirements `?untagged=integration` filter and the Sources URL filters + tests.

**Acceptance Criteria:**
- Given a PSE on the Gaps tab at 1440px, when the context loads, then the strip and banners sit under the header in the mockup's banner style, in light and dark.
- Given backend `pytest` + `lint-imports`, and web `lint`, `typecheck`, `test` and `build`, when run, then all pass.

## Implementation Notes

## Spec Change Log

## Review Triage Log

| Finding | Verdict | Route | Evidence |
|---|---|---|---|
| Retired type reported as uncovered; Sources select shows "All" over zero rows | medium | patch | `get_catalogue_entry` resolves retired entries; the picker lists only active types. |
| 422 checked before If-Match (stale + retired id → 422, not 412) | low | patch | `_check_addable` runs before `_expected`; the fix is a reorder. |
| `?untagged=` hides the row just tagged while its inspector is open | medium | patch | `shownItems` re-filters on `replace`. |
| `startEdit` leaves the Checklist view state set | low | patch | `open()` clears it; `startEdit` doesn't. |
| No page tests for `?untagged=integration` or KnowledgePage params | low | patch | Pre-verified by the verification-gap layer. |
| No test of the REVOKE UPDATE on the tag table | low | defer | Pre-verified, filed as defer. |
| Second migration 0037 on the Story 4.2 branch; Story 3.5 branch adds its own `get_coverage` | medium | defer | Cross-branch; whichever merges second re-chains or adopts the other's API. |
| `schema.d.ts` missing; deleted-entry mismatches | false | rejected | The schema was left out of the review diff on purpose; catalogue entries are never deleted. |
| N+1 lookups, coverage scan, no split/merge tag event, duplicate loader, stale context, no action tests, `tagged_at` order, catalogue read failure | low | rejected | No named harm in everyday use, or the fix adds complexity. |

## Verification

**Commands:**
- `cd backend && uv run alembic upgrade head && uv run pytest && uv run lint-imports` -- expected: all pass. **Never run pytest against the dev `psa` DB** (migration tests drop tables). Grep the two URLs out of the repo-root `.env` (never `source` it), swap host/db to `127.0.0.1:5432/psa_test`, and set BOTH `PSA_DATABASE_URL` (psa_app) and `PSA_MIGRATIONS_DATABASE_URL` (owner `psa`). Run the new and touched test files first; the full suite takes ~16 min. A 409 in `test_knowledge_catalogue.py::test_create_is_version_one_with_one_event` comes from leftover rows, not a regression.
- `gen:api`: the Docker `api` on :8000 serves a stale image. Regenerate against a fresh local uvicorn on this worktree's backend, or against a dumped `app.openapi()`.
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass.

**Manual checks:**
- Screenshot the Gaps tab (strip and both banners), the Requirement inspector section and the read-only Checklist pane, in light and dark.
