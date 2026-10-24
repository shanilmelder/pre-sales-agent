---
title: 'Story 7.3: Admin Agents view with config history (remainder)'
type: 'feature'
created: '2026-10-24'
status: 'done'
baseline_commit: 'a3e9347ead4d6a7879aa958c3200a862b003350d'
route: 'dispatch'
review_loop_iteration: 1
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-7-context.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Admin → Agents (built in the admin redesign) is a read-only table. Administrators still cannot see an Agent's config history, compare versions, create or restore a config version, or enable/disable an Agent without calling the API by hand. The API stores no reason for a new version and returns no author name.

**Approach:** Keep the mockup's table (Agent | Version | Model | Status | Tool permissions, footnote) and make its rows selectable (`j`/`k`, Enter) to open an Agent inspector in the right pane, as the Users and Catalogue tabs do. The inspector shows the current config, the history (newest first: version, semver, author, date, reason, changed fields), a two-version diff, an edit form that creates a new version with a required reason, "Restore this version", and Enable/Disable behind a confirm dialog. The backend gains a stored reason, `restored_from_version`, the author's name, and a read of the deployed options the form may pick from.

## Boundaries & Constraints

**Always:**
- Writes keep AD-3 (authorize → validate → `If-Match` on the Agent → write → trace, one UoW). The `registry.agent_config.version_created` trace payload gains `reason` and `restored_from_version` (null unless a restore).
- Config versions stay insert-only; a restore inserts version n+1 copying the chosen version's fields, with the new reason and `restored_from_version` set. The earlier row is unchanged.
- Reason: required, trimmed, 1-500 characters (422 `validation_error` otherwise). Seeded and pre-existing rows have a null reason and show "—".
- The form offers only what `check_deployed` accepts: the deployed manifest's model profiles, this Agent's prompt / input / output schema versions, and ToolGateway `READ_TOOLS`. Budgets are edited as a JSON object (monospace textarea, at most 20 keys).
- Diff: the changed fields between two picked versions, each on `bg-diff-tint` with `aria-hidden` `−`/`+` markers and `sr-only` "Before"/"After"; permissions are shown as granted (`+`) and removed (`−`). Never green or red.
- 412 shows the admin concurrent-edit message ("Changed by another administrator since you opened it.") with Reload, and nothing is overwritten; 409/422 show the API's `detail`.
- Admin-only: non-admins keep the existing "No access" page and hidden nav; API writes stay 403.
- Every status is an icon plus a label; axe finds no WCAG 2.1 AA violations in the table, inspector, form, diff and dialog.

**Decisions:**
1. The disable dialog uses fixed copy with no count: "Disabled Agents get no new tasks. A run that reaches this Agent waits for a person to continue without it; running tasks finish." The enable dialog says: "Enabled Agents get new tasks from the next run." (Wording corrected by the user in review on 2026-10-24 to match Story 5.5.)
2. The "Not evaluated" badge and save confirmation are deferred to Story 7.8.
3. An `eval_only` Agent has no Enable/Disable action: the inspector shows its "Eval only" pill and the note "Used by evaluations only; never planned into runs." (user, review 2026-10-24)

**Never:**
- No change to the table's columns, the footnote or other admin tabs (follow the new mockup).
- No model-profile locking or digests (7.2), no tool-permission administration beyond picking READ tools (7.4), no registering new Agents from the UI.
- No reason on enable/disable (the AC only requires the trace).
- No new UI primitives in `components/ui/*`; reuse `Dialog`, `InlineAlert`, `Pill`, `Textarea`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Open inspector | `j`/`j`/Enter on the table | 2nd row selected (`aria-current`), inspector opens, heading focused; Escape/close returns focus to the row | N/A |
| History | Agent with v1 (seed) and v2 | v2 first: semver, author name, date, reason, "Changed: model profile, prompt version"; v1 reason "—", author "System" | N/A |
| Compare | Pick v1 and v3 | Only differing fields, `−` v1 value / `+` v3 value; permissions as granted/removed | Same version picked twice → "Pick two different versions." |
| Save new version | Edited prompt v2 + reason | 201, row and inspector show v(n+1), history reloads, new runs use it | Empty reason → button disabled, inline error |
| Stale | Another admin saved first | Concurrent-edit message + Reload; form keeps the input | 412 |
| Not deployed | Restore of a version whose prompt is gone | API `detail` shown inline; nothing stored | 422 |
| Restore | "Restore this version" on v1 | Form prefilled from v1 with next patch semver; save needs a reason; new row has `restored_from_version: 1`, history shows "Restored from v1" | as Save |
| Disable | Active Agent → Disable → Confirm | Dialog states the effect (Decision 1); status pill "Disabled"; trace written | 412 as Stale |
| Enable | Disabled Agent → Enable → Confirm | Pill "Enabled" | 412 as Stale |
| Non-admin | No platform-admin role | "No access" page; write endpoints 403 | 403 |

</frozen-after-approval>

## Code Map

- `backend/app/modules/registry/adapters/models.py:52` `ConfigVersionRow` -- add nullable `reason text`, `restored_from_version int`. `adapters/repository.py` `insert_version` / version mapping -- carry both.
- `backend/migrations/versions/` -- new `20261024_0043_registry_config_reason.py`, revision `0043_registry_config_reason`, down `0042_blocking_findings` (check head). Grants unchanged (INSERT already granted).
- `backend/app/modules/registry/domain/registry.py` -- `ConfigVersion` gains both fields; add a `reason()` rule (`_bounded`, max 500). `READ_TOOLS` from `app.platform.tool_gateway.catalogue`.
- `backend/app/modules/registry/application/models.py` -- `AgentConfigVersion` += `reason`, `restored_from_version`, `created_by_name` (null for seeded); new `NewAgentConfigVersion(NewAgentConfig)` with `reason: StrictStr`, `restored_from_version: int | None`; new `AgentConfigOptions` (profiles, prompt_versions, input/output schema versions, tool_permissions).
- `backend/app/modules/registry/application/registry.py:330` `create_config_version` -- take `NewAgentConfigVersion`; a `restored_from_version` must name an existing version of this Agent (422). `read_versions` resolves names via `identity.user_names` (identity public; allowed). New `read_config_options(uow, actor, agent_id)` from `deployed.load()` (admin only). `register_agent` unchanged.
- `backend/app/agents/manifest.py` -- add accessors listing prompt versions / schema versions per agent and profile names if missing.
- `backend/app/modules/registry/api/routes.py` -- POST config-versions body → `NewAgentConfigVersion`; new `GET /{agent_id}/config-options` (`get_agent_config_options`). `application/public.py` exports.
- `backend/app/platform/trace/catalogue.py:1202` -- payload fields.
- `backend/tests/test_registry.py` -- extend.
- `web/src/components/admin/users-admin.tsx` (+ test) -- template for `agents-admin.tsx` (selection, right pane, focus return, refresh). `catalogue-table.tsx:54-94` -- j/k + roving tabindex + `aria-current` to copy into `agents-table.tsx` (rows become buttons; columns unchanged).
- `web/src/components/admin/catalogue-inspector.tsx:77-91,300-313` -- reload history on `row_version` change, heading focus; `app/admin/catalogue/actions.ts` -- action result union, `If-Match: "${rowVersion}"`, 412 → stale; copy as `app/admin/agents/actions.ts`.
- `web/src/components/opportunities/requirement-diff.tsx` + `components/admin/evals-view.tsx:~235` (`DIFF_GRID`, `data-changed`) -- diff markup to copy for `agent-config-diff.tsx`.
- `web/src/components/opportunities/conflict-inspector.tsx:133-175` `ReasonField` -- reuse pattern (count, `aria-invalid`).
- `web/src/components/ui/dialog.tsx`, `ui/inline-alert.tsx` -- confirm dialog and 412.
- `web/src/lib/admin.ts:36-57` -- add agent copy/labels and a pure `changedFields(a, b)` helper; `lib/catalogue.ts:32` stale wording.
- `web/test/axe.ts` -- `axeViolations`.

## Tasks & Acceptance

**Execution:**
- [x] `backend/migrations/versions/20261024_0043_registry_config_reason.py`, registry adapters/domain -- columns, mapping, reason rule.
- [x] registry application/api/public + `manifest.py` + trace catalogue -- reason, restore, author names, config-options read.
- [x] `backend/tests/test_registry.py` -- reason required/trimmed/too long, restore copies and records `restored_from_version`, unknown restore version 422, names resolved (seed null), options endpoint (admin 200, non-admin 403), trace payload, migration up/down.
- [x] `web`: `npm run gen:api`; `app/admin/agents/actions.ts` (+ test); `components/admin/agents-admin.tsx`, `agents-table.tsx` (selectable), `agent-inspector.tsx`, `agent-config-form.tsx`, `agent-config-diff.tsx`, `agent-status-dialog.tsx`; `lib/admin.ts`; `app/admin/agents/page.tsx` -- wire it.
- [x] web tests -- one case per I/O matrix row, plus axe on the inspector, form, diff and dialog.

**Acceptance Criteria:**
- Given a saved new version, when the Agent list reloads, then the row's Version and Model show the new current config, and Assessments already started keep their pinned config version.
- Given the inspector, when it renders, then it shows agent ID, name, status, current version, semver, model profile, prompt version, schema versions, tool permissions and budgets.

## Implementation Notes

- The migration adds two checks besides the columns: `reason` 1-500 characters when set, and `restored_from_version` between 1 and `version - 1`.
- Author names are resolved for the list, the single Agent and the history (`created_by_name`); a missing user shows "Unknown user", a seeded version "System".
- Output schema options only list versions written for the deployed contract version, so the form never offers one `check_deployed` would refuse. A restored version whose value is no longer deployed is still shown in its picker so the API's 422 sentence reaches the admin.
- The "Restore this version" buttons carry `aria-label="Restore this version (vN)"` to stay distinct for screen readers.
- `CardTable` on Agents is no longer `scrollable` (rows are focusable now), as on Catalogue.

## Spec Change Log

- 2026-10-24 review: frozen Decision 1 wording corrected (queued tasks pause the run since Story 5.5, they are not skipped) and Decision 3 added (`eval_only` has no status action), both answered by the user. The user chose to patch in place rather than revert. KEEP: the whole reviewed implementation; only the copy constant and the inspector's status action change, alongside the review patches.

## Review Triage Log

| Finding | Verdict | Evidence / route |
|---|---|---|
| Disable dialog says queued tasks are "skipped"; since Story 5.5 the run waits for a person who continues without the Agent (blind) | medium | `test_registry.py` "disabled Agents in runs" header: run goes `waiting_for_human`. Copy came from frozen Decision 1 → intent_gap; user corrected Decision 1 and chose patch in place. |
| `eval_only` Agent offered "Enable"; one click puts the eval baseline into real runs (blind, edge) | medium | `agent-inspector.tsx` `enabled = status === "active"`; dialog posts `active`. Spec covered active/disabled only → intent_gap; user added Decision 3, patch in place. |
| A restore can hold fields that differ from the version it names (blind, edge) | medium | `create_config_version` only checks the number exists; the form lets the admin edit restored fields. Frozen block: a restore copies the chosen version's fields → patch: lock restored fields in the form and 422 server-side when they differ. |
| After a 412 and Reload with the form open, a save reverts the other admin's change under the new row version (blind, edge) | high | Form state is set once at mount from the old config; `agent.row_version` is the reloaded one. → patch: re-prefill the form from the reloaded current config (keep the reason). |
| History load failure leaves "Loading…" forever (blind, edge) | medium | `agent-inspector.tsx` effect ignores non-ok results and swallows errors. → patch: error text with Retry. |
| `k`/ArrowUp row navigation untested (verification-gap) | medium | Pre-verified; only `j` is pressed. → patch: add test. |
| "Unknown user" author fallback untested (verification-gap) | low | Pre-verified. → patch: one assertion. |
| `install_eval_config` does not copy `reason`/`restored_from_version` into the eval DB (verification-gap other) | low | `registry.py:745` call omitted them → patch copies `reason` only; `restored_from_version` stays null in the eval DB, which numbers versions independently (copying it could fail the `restored_from_version < version` check). |
| Restore clicked while a dirty form is open loses typed input (edge) | low | Real but rare; fix needs a dirty-check confirm. Rejected. |
| `isdigit()` on non-ASCII manifest keys → 500 (edge) | false | `manifest.json` is generated by our own code with ASCII integer keys; unreachable. |
| Required `reason` on the trace payload breaks reading older events (blind) | false | Payload models only validate on write (`trace/writer.py`); stored events are never re-parsed through the catalogue. |
| Reason DB check, restore-of-current, semver uniqueness untested (blind) | low | Restore-of-current creates a valid copy by design; semver is not unique by design; reason check mirrors the app rule. Rejected. |
| Matrix web gaps: forbidden/not-found messages, options load failure, axe on restore form (blind) | low | Each path is a plain message branch; core matrix rows are covered. Rejected. |
| OpenAPI: config-options documents an unrelated 422 text; `reason` max length not in schema (blind) | low | Cosmetic contract text. Rejected. |
| Tracking files disagree (sprint-status in-progress vs spec in-review; epic context) (blind) | false | Step 5 moves sprint status; epic context is a compiled read-only summary. |

## Design Notes

- Table columns follow the new mockup, not the AC's column list; agent ID, prompt version and the rest are in the inspector. The mockup draws no inspector, so it copies the Users/Catalogue right-pane inspector and card styles.
- "Capabilities" in the AC = tool permissions (the only capability field the registry has).
- Model profiles: every deployed manifest profile until 7.2 adds locking.
- Restore prefills the edit form (semver = next patch of the current semver) rather than posting blindly, so the admin sees what will change and gives a reason.

## Verification

Work only in the git worktree `D:/Projects/Office/pre-sales-agent-73` (its own `.env`; test DB `psa_test73` already exists); never edit, stash or commit in `D:/Projects/Office/pre-sales-agent`. No commits or pushes.

**Commands:**
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests/test_registry.py` -- pass, against `psa_test73` at `127.0.0.1` (app and owner URLs), never the dev `psa` DB.
- `cd backend && uv run alembic upgrade head && uv run alembic downgrade 0042_blocking_findings && uv run alembic upgrade head && uv run alembic check` (against `psa_test73`) -- clean.
- `cd web && npm run gen:api` against a freshly started local uvicorn, then `npm run lint && npm run typecheck && npm test` -- pass, no schema drift.
