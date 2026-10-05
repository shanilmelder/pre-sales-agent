---
title: 'Story 8.8 (demo slice): export the Estimate, Assumptions Register and Clarification Questions'
type: 'feature'
created: '2026-10-05'
status: 'done'
baseline_commit: '7ea09672ff8aac5ecfd7426f78b832be738e9dac'
route: 'dispatch'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-8-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-8-7-carry-assumptions.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** The Estimate, its Assumptions Register and the Clarification Questions live only in the app. Today's proposal process runs on Office files, so nothing reaches the customer or the proposal without retyping (FR-36).

**Approach:** An **Export** control on the Estimate tab downloads the current draft Estimate Version as a file containing the Estimate, the Assumptions Register and the Clarification Questions, generated on request from the same read models the tabs use.

## Boundaries & Constraints

**Always:**
- **Depends on:** 8.1 (versions, lines, totals), 8.4 + 8.7 (Assumptions, carried rows), 4.3 (Gaps and their Clarification Questions).
- **Generation (decided: synchronous, demo slice):** the API builds the file in the request from `estimates.get_estimate` and `gaps.list_gaps` and returns it as an attachment. No job, no `platform.storage`, no signed URL. Numbers are exactly the server-calculated values already in the read model; the exporter never sums anything itself.
- **Formats (decided: .xlsx and .docx):** `format=xlsx` gives one workbook with three sheets (Estimate, Assumptions, Clarification Questions); `format=docx` gives one document with the same three sections as tables, for pasting into the proposal. Both carry the same content and header.
- **Version:** the current draft version (the one the tab shows). With no version, there is nothing to export (409 `estimate_not_found`-style problem; the button is hidden).
- **Content:**
  - **Header on every sheet or page:** Opportunity name, "Estimate v{n}", "Draft — not submitted", and the export time (UTC, ISO-like, e.g. 2026-10-05 14:32 UTC).
  - **Estimate:** lines grouped by section in grid order, each with title, basis, role mix (engineer / PM / QA %), effort, Contingency and total hours; section subtotals; the Unallocated contingency row when > 0; overall totals.
  - **Assumptions Register:** Conditions (exact wording) and Contingencies (wording, hours, linked line), each with its origin Gap title, "Accepted by {name}, {date}" or "Not accepted", and "Carried from v{n}" when carried.
  - **Clarification Questions:** each open or converted Gap that has a question: Gap title, impact, topic, question text, and the Gap's status (open / converted). No sent or answered dates (they don't exist yet).
- **File name:** `{opportunity-slug}-estimate-v{n}.{ext}`, ASCII only.
- **API:** `GET /opportunities/{id}/estimate/export?format=…`. New action `estimates.estimate.export` (owner and collaborators except sales representatives, like `ESTIMATE_DRAFT_START`). A reader without access gets the 404-equivalent; a sales representative gets 403. `EstimateView` gains `can_export`.
- **Web:** an **Export** control in `EstimateHeader` offering "Excel (.xlsx)" and "Word (.docx)", keyboard-operable,, hidden unless `can_export` and a version exists. It downloads through a Next.js route handler that adds the user's token and streams the backend response back with its `Content-Disposition`. On failure: "Export failed: <reason>" with Retry.
- **Trace:** `estimates.estimate_version.exported` with the version id, version number and format, actor the user. No content.
- **Privacy:** no Requirement, Gap, question, Assumption or line text in logs or trace.
- **Dependencies:** pinned, permissive licences, noted inline as `pypdf` is (`openpyxl` MIT, `python-docx` MIT).

**Never:** No export job, storage, signed URLs or download expiry; no Risks (none exist); no catalogue tags or durations (lines don't have them); no export of superseded versions; no sent/answered tracking for questions. These stay in full Story 8.8 / 4.6 `[post-demo]`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy | Draft v2 with 6 lines in 3 sections, 4 Assumptions (1 carried, 1 not accepted), 3 Gaps with questions | File with header, all lines, subtotals and totals equal to the read model, the 4 Assumptions with their labels, the 3 questions; one trace event | N/A |
| Unallocated | Version with Unallocated contingency 12 h | The row appears and the totals match the read model | N/A |
| No version | Opportunity with no Estimate yet | 409 problem; button hidden | No file |
| Who | Sales rep / non-member / owner | 403 / 404 / 200 | No file on 403/404 |
| Docx | Same version, `format=docx` | Document with the header and the three sections as tables; same values as the xlsx | N/A |
| Bad format | `format=pdf` | 422 | No file |
| Privacy | Any export | No content text in logs or trace | N/A |
| Web failure | Backend returns 5xx | "Export failed: <reason>" with Retry; nothing downloaded | N/A |

</frozen-after-approval>

## Code Map

- `backend/app/modules/estimates/application/estimates.py:349` `get_estimate` and `application/models.py` (`EstimateView` ~:180, `EstimateVersion` ~:150, `EstimateSection` :79, `EstimateLine` :63, `Totals` :40, `AssumptionGroups` ~:124, `Assumption` :103) -- the only data source for the Estimate and Register. Add `can_export` to `EstimateView`.
- `backend/app/modules/gaps/application/public.py:8` `list_gaps` (`gaps.py:152`) -- `Gap.question` (`models.py:39`: text, topic, status); questions are `drafted|superseded` only.
- New `backend/app/modules/estimates/application/export.py` (orchestration, auth, trace) plus a pure renderer module per format (no DB) so it is unit-testable; route in `estimates/api/routes.py` returning a `Response` with the media type and `Content-Disposition`. No binary endpoint exists yet: this is the first.
- Authorization: `opportunities.readable_resource` (`opportunities/application/opportunities.py:137`) for the 404, then `identity.authorize` with the new action. `identity/actions.py:28-29`, `domain/policy.py:99` (`RELATION_EXCLUDED_ROLES`), `OWNER_GRANTS`/`MEMBER_GRANTS` ~:111; update `tests/test_authorize.py`.
- `backend/app/platform/trace/catalogue.py` -- add `EstimatesEstimateVersionExported` like `EstimatesAssumptionAccepted` (:297).
- `backend/pyproject.toml:8-20` -- add the pinned deps with licence comments; `uv lock`.
- Web:
  - `web/src/components/opportunities/estimate-grid.tsx:303` `EstimateHeader` (button in the row ~:327-345, next to `VersionPill`); flags flow from `EstimateSection` (:393) as `canStart`/`canAccept` do.
  - New route handler at `web/src/app/api/opportunities/[id]/estimate-export/route.ts` (not under `opportunities/[id]/`, where a static `estimate` folder would shadow the `[tab]` route). Use `auth0.getAccessToken()` as `web/src/lib/api/server.ts:20` does; `web/src/proxy.ts:18-40` already guards sessions. Only other route handler: `app/healthz/route.ts`.
  - Regenerate `schema.d.ts` from a local uvicorn, not the Docker `api`.
- Log-privacy test pattern: `tests/test_estimates_assumptions.py:339-344`.
- No migration is needed.

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/modules/estimates/**` (export orchestration, renderer(s), route, `can_export`), identity action, catalogue, deps
- [x] `backend/tests/test_estimates_export*.py` -- every matrix row: open the generated file with the same library and assert cells/paragraphs against the read model
- [x] Web: `schema.d.ts`, route handler, Export control and failure state in `EstimateHeader`, tests with axe

**Acceptance Criteria:**
- Given the demo Opportunity with a draft Estimate, when the presales engineer presses Export, then a file downloads that opens in Office and shows the Estimate with the same totals as the tab, the Assumptions Register, and the Clarification Questions, each marked "Estimate v{n} · Draft — not submitted".
- Given CI, when it runs, then the backend and web checks pass with no live model.

## Implementation Notes

- **Layout:** `application/export_content.py` (pure) turns `EstimateVersion` + `list_gaps` items into a format-neutral `ExportDocument` (header + three tables); `adapters/export_xlsx.py` and `adapters/export_docx.py` only lay it out, so both files carry the same cells. `application/export.py` authorizes, reads, renders (in a thread) and traces. Numbers are copied from the read model; nothing sums.
- **Header:** three lines on every sheet (top rows) and in the docx page header: Opportunity title, "Estimate v{n} · Draft — not submitted", "Exported YYYY-MM-DD HH:MM UTC".
- **Questions:** Gaps from `list_gaps` (open, then converted) whose question is `drafted`; empty tables show one "None" row.
- **Errors:** new `EstimateNotFoundError` (409 `estimate_not_found`); a missing or unknown `format` is FastAPI's 422 `validation_error`. A head of delivery (reader, not member) gets 403 like a sales representative.
- **Deps:** `openpyxl==3.1.5`, `python-docx==1.2.0` (MIT; pulls `lxml`, BSD) and dev `types-openpyxl` (Apache-2.0) for mypy strict.
- **Web:** `EstimateExport` (disclosure button + group of two format buttons; arrows, Escape, Tab) fetches the route handler, saves the blob under the `Content-Disposition` name; a non-file response (e.g. a sign-in redirect) counts as a failure. `schema.d.ts` regenerated from a dumped `app.openapi()`.

## Spec Change Log

## Review Triage Log

| # | Layer | Finding | Verdict | Route | Evidence |
|---|-------|---------|---------|-------|----------|
| 1 | blind+edge | Text starting with `=`/`+`/`-`/`@` becomes an Excel formula (injection) | medium | patch | openpyxl treats leading `=` as a formula; titles and wording are model- or user-sourced and go to customers. Fixed. |
| 2 | blind+edge | XML-illegal control characters make either renderer raise → 500 | medium | patch | openpyxl `IllegalCharacterError` / lxml `ValueError`; PDF-extracted text can carry them. Fixed. |
| 3 | blind | "Draft — not submitted" hard-coded, ignores status | false | reject | The intent exports only the current draft; no other status exists. |
| 4 | blind | Questions oracle weaker than the code's filter | low | patch | The fixture has no superseded question, so the filter is never exercised. Fixed. |
| 5 | blind | Enum compared by string value | low | reject | Developer-only style; mypy-visible enums exist but no divergence is reachable today. |
| 6 | blind | Uncovered/dropped counts and role-hour totals not exported | false | reject | The frozen content list defines what the file holds. |
| 7 | blind | Section shown in both the group row and each item row | low | reject | Cosmetic. |
| 8 | blind | Word table header row doesn't repeat across pages | low | patch | Direct correction (`w:tblHeader`); a multi-page Estimate loses its headings. Fixed. |
| 9 | blind | docx header `runs[0]` fails on an empty title | false | reject | Opportunity titles are required and non-empty. |
| 10 | blind | 409 named `estimate_not_found` | false | reject | The frozen intent specifies this 409. |
| 11 | blind | No non-sales collaborator 200 case | low | patch | `MEMBER_GRANTS` change untested through the API. Fixed. |
| 12 | blind+edge | Focus drops to body after export; ArrowUp from no option picks the wrong one | low | patch | Focus set while the trigger is still disabled; `at === -1` arithmetic. Fixed. |
| 13 | blind | Repeated reads/authorization; possible mixed snapshot | low | reject | Correct as written; a re-draft mid-request is unlikely and harmless for a demo download. |
| 14 | blind | Route error mapping tested only for 403 | low | patch | Folded with rows 16–17. Fixed. |
| 15 | verify | No test of the `EstimateSection` → `EstimateHeader` Export wiring | medium | patch | Pre-verified: every section/page test has `can_export: false` or no version. Fixed. |
| 16 | verify | 502 and 404 failure reasons untested | low | patch | Pre-verified: the `it.each` covers 500/403/409 only. Fixed. |
| 17 | edge | 2xx with no body returns a problem with status 200 | low | patch | One-line direct correction (use 502). Fixed. |
| 18 | edge | A naive `now` shifts the export time | false | reject | `now` is only injected by tests; production uses `datetime.now(UTC)`. |
| 19 | edge | Export during proposals omits Assumptions still being proposed | low | reject | The file reflects the current state, as the tab does; the intent sets no rule for this. |

## Verification

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run alembic check && PSA_DATABASE_URL=<psa_app @127.0.0.1> PSA_MIGRATIONS_DATABASE_URL=<owner @127.0.0.1> uv run pytest` -- expected: all pass, none skipped
- `cd web && npm run lint && npm run typecheck && npm test && npm run build` -- expected: all pass

**Manual checks:**
- Open both downloaded files in Excel and Word: three sections present, totals equal the Estimate tab.
