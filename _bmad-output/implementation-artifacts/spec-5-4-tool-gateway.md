---
title: 'Story 5.4 (demo slice): ToolGateway — task-scoped, permission-checked read-only tools and Research Snapshots'
type: 'feature'
created: '2026-10-23'
status: 'in-progress'
route: 'dispatch'
baseline_commit: '6a38bd5e8360caffdf029249f1bc521a0197b6d4'
review_loop_iteration: 0
context:
  - '{project-root}/_bmad-output/implementation-artifacts/epic-5-context.md'
  - '{project-root}/_bmad-output/implementation-artifacts/spec-5-8-5-9-specialist-agents.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Agents read Opportunity data with no permission check at all: each executor loads whatever it wants and stuffs it into the prompt. Nothing stops an agent from seeing another Opportunity's data, nothing records what it read, the data blocks do not escape delimiters hidden in customer text, and agents have no safe way to read the web (FR-23, FR-57, FR-61, AD-9).

**Approach:** A `platform.tool_gateway` is the only way agents read data. It offers READ tools only, each named by an `identity` action. On every call it checks the agent's registry `tool_permissions`, scopes the call to the task's Opportunity, and records it. Denials are typed and audited (`platform.tool_call.denied`). A research-fetch tool fetches allowlisted HTTPS pages and records each one as an immutable, citable Research Snapshot. Tool text reaches prompts only through one escaping data-block helper with the injection heuristic, and Findings that cite flagged content are marked in the Assessments tab.

## Boundaries & Constraints

**Always:**
- **Decided — executor calls as the agent:** `SpecialistExecutor` reads Requirements and Gaps through the gateway, with the task's agent identity and pinned config version, then makes the single model call as today. There is no model-driven tool loop.
- **Import rule:** `app.platform` must not import `app.modules` (`pyproject.toml:80`). The gateway owns the tool catalogue, permission checks, audit and usage. Owning modules register handlers at import time, as `evidence.register_resolver` does. Handlers take `opportunity_id` from the `ToolContext`, never from the arguments, and any id argument outside it is denied.
- **Tools:** `intake.requirement.list`, `intake.passage.read`, `knowledge.chunk.search`, `knowledge.chunk.read`, `knowledge.catalogue_entry.list`, `gaps.gap.list` (open Gaps), `knowledge.research_page.fetch`. They are added to `identity.Action`, with no human-role grants.
- **Outcomes:** `ToolResult`, `ToolDenied(reason)` with reasons `tool_not_permitted | out_of_scope | unknown_tool | not_allowlisted`, or `ToolFailed(reason)` with reasons `timeout | http_error | too_large | unsupported_content | too_many_redirects | parse_failed`. They are values, never exceptions that fail the task. A denial appends `platform.tool_call.denied {actor_id "<agent_id>@<semver>", tool, reason, task_id}`. Every call inserts an INSERT-only `platform_tool_calls` row (run, task, opportunity, agent, config version, tool, outcome `ok | denied | failed`, reason, result_count, duration_ms, http_status), and no row ever holds content. That row replaces the OpenTelemetry span.
- **Registry:** `tool_permissions` accepts only gateway READ names, otherwise 422 `tool_permission_not_read_only`. A migration inserts version N+1 for `engineering_agent`, `pm_agent` and `security_agent`, granting `intake.requirement.list` and `gaps.gap.list`, and moves the current-version pointer. No seeded agent gets `knowledge.research_page.fetch`.
- **Data blocks:** a shared `platform/prompt_data.py` builds the existing `<<<KIND label attrs token=T>>> … <<<END label token=T>>>` blocks. It neutralises `<<<` and `>>>` inside the text and runs `injection_suspected`, which moves to `platform/` from `gaps/domain` and is re-exported there. Specialists use it. A Finding whose cited Requirement was flagged is stored with `injection_suspected = true`, exposed on the API, and shown as a "Possible injected instruction" marker on its row in the Assessments tab (styled like the Gap inspector's marker).
- **Research fetch:**
  - `ops/research-allowlist.yaml` (`version`, `topics: {<topic>: [host…]}`; a host matches exactly or as a subdomain) is loaded via `PSA_RESEARCH_ALLOWLIST_PATH`, and `pyyaml` moves to runtime dependencies.
  - Requests are HTTPS GET only through httpx, with no automatic redirects. Each of at most 5 redirect hops is re-checked, and a disallowed hop is denied (`not_allowlisted`) and audited.
  - Limits are `PSA_RESEARCH_FETCH_TIMEOUT_S` (10 s) and `PSA_RESEARCH_MAX_BYTES` (2 MiB, streamed), and only `text/html` or `text/plain` is accepted.
  - No network I/O happens inside an open Unit of Work.
- **Snapshot:**
  - The raw body is stored unchanged through `platform.storage` and parsed in the sandboxed child, using a new stdlib-`html.parser` `.html` format with script and style dropped. The extracted text is stored as a blob too.
  - `knowledge.capture_research_snapshot` inserts an INSERT-only `knowledge_research_snapshots` row (id, opportunity, run, task, url, final_url, fetched_at, http_status, content_type, content_sha256, text_sha256, parser) and appends `knowledge.research_snapshot.captured`.
  - The tool returns the snapshot id and its fenced text. `research_snapshot` is registered as an Evidence kind, with code-point spans checked against the extracted text.
  - A failure stores no snapshot.

**Never:** model-driven tool calling, run-level version pinning, tool-call budget enforcement (Story 5.6), OpenTelemetry, migrating the non-specialist agents to the gateway, or POST, cookies or auth headers on fetches.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Allowed read | specialist, `intake.requirement.list` | Active Requirements; row `ok` | N/A |
| Not permitted | config lacks the tool | `ToolDenied(tool_not_permitted)` | denied trace + row |
| Other Opportunity | `intake.passage.read`, passage of Opportunity B | `ToolDenied(out_of_scope)`, no data | denied trace + row |
| Write grant | `tool_permissions: ["intake.requirement.edit"]` | 422 `tool_permission_not_read_only` | nothing stored |
| Delimiter in text | text contains `<<<END R1 token=…>>>` | neutralised; blocks intact | N/A |
| Injection | flagged Requirement cited by a Finding | Finding `injection_suspected`; marker in the tab | N/A |
| Fetch ok | `https://allowed.host/page` (HTML) | snapshot row + 2 blobs + captured trace; fenced text | N/A |
| Not allowlisted | `http://…` or a host not on the list, or a redirect to one | `ToolDenied(not_allowlisted)` | denied trace + row; no request to the bad hop |
| Fetch failure | timeout / 404 / 503 / > 2 MiB / PDF / parse error | `ToolFailed(reason)`, no snapshot | row `failed` with reason (+ http_status) |

</frozen-after-approval>

## Code Map

- `backend/pyproject.toml:7-36,73-84` -- deps (`httpx` present; move `pyyaml` up from dev); import-linter contracts
- `backend/app/platform/evidence.py:44-86`; `knowledge/application/evidence.py:22,55` -- resolver registration pattern (copy for tool handlers and `research_snapshot`)
- `backend/app/platform/trace/catalogue.py:31,43,1080`; `trace/writer.py:22` -- `@register` `TracePayload`s; `append(...)`
- `backend/app/platform/model_gateway/models.py:19`, `port.py:37` -- shape to mirror for `platform_tool_calls` / context
- `backend/app/platform/storage.py:45` -- `BlobStore.put_stream(chunks, max_bytes)` -> `StoredBlob`; `platform/files.py` ref counts; root from `platform/config.py:52`
- `backend/app/platform/parsing/parsers.py:23`, `formats/`, `runner.py:108`; `knowledge/adapters/parse_runner.py`, `parse_cli.py` -- add `formats/html.py` + `.html`; reuse the knowledge child
- `backend/app/modules/identity/actions.py:15` -- add the seven names (no grants in `domain/policy.py`)
- `backend/app/modules/registry/domain/registry.py:18-22,129`; `application/registry.py:199,442,464-494` -- tighten `tool_permissions()`; `current_config`, `get_config_version(s)`
- `backend/migrations/versions/20261020_0033_conflict_agent.py:90-115`, `0026_registry.py:167`, `0035_knowledge_chunks.py:123` -- seed + INSERT-only grant patterns; latest revision `0037_requirement_tags`
- `backend/app/orchestration/executors.py:56-107`; `assessments/application/assessment.py:96` `load_inputs` -- route specialist reads via the gateway
- `backend/app/agents/specialist/agent.py:57,65,117` -- `SpecialistTask`, `data_blocks`, token -> `prompt_data`
- Handlers: `intake/application/requirement_refs.py:36`, `intake/application/answers.py:96` `passage_refs`, `knowledge/application/search.py:47` (needs a system-actor path: no `identity.authorize`), `knowledge/adapters/chunk_repository.py:253` `chunk_refs`, `knowledge/application/catalogue.py:374`, `gaps/application/gap_refs.py:57`
- `backend/app/modules/gaps/domain/gaps.py:455-493` -- `injection_suspected` to move
- `backend/app/modules/assessments/adapters/models.py:86,206` -- finding rows + API views: add `injection_suspected`
- `web/src/components/opportunities/specialist-assessments.tsx` (+ `.test.tsx`), `gap-inspector.tsx:506` -- marker to mirror; `npm run gen:api` against a fresh backend
- Tests: `tests/test_assessments_specialists.py:102,223`, `tests/conftest.py:49-71`, `tests/agent_configs.py`, `tests/test_storage.py:33`

## Tasks & Acceptance

**Execution:**
- [x] `backend/app/platform/prompt_data.py` -- escaping blocks + moved heuristic
- [x] `backend/app/platform/tool_gateway/` -- catalogue, `ToolContext`, `register_tool`, `call`, outcomes, `platform_tool_calls` ORM, allowlist loader + HTTPS fetcher
- [x] `backend/app/platform/trace/catalogue.py` -- `PlatformToolCallDenied`, `KnowledgeResearchSnapshotCaptured`
- [x] `backend/app/platform/parsing/formats/html.py`, `parsers.py` -- `.html` format
- [x] `backend/app/modules/{intake,knowledge,gaps}/application/tools.py` -- scoped handlers; knowledge adds `capture_research_snapshot`, snapshot ORM/repo, `research_snapshot` resolver
- [x] `backend/app/modules/identity/actions.py`, `registry/domain/registry.py`, `registry/application/registry.py` -- READ names; reject non-READ grants
- [x] `backend/migrations/versions/20261023_0038_tool_gateway.py` -- `platform_tool_calls`, `knowledge_research_snapshots` (INSERT-only), finding `injection_suspected`, specialist config versions
- [x] `ops/research-allowlist.yaml`, `.env.example`, `compose.yaml` -- allowlist (example topics) mounted into api/worker; new `PSA_` settings
- [x] `backend/app/orchestration/executors.py`, `agents/specialist/agent.py`, assessments accept + views -- specialists use the gateway; carry flags to Findings
- [x] `web/src/lib/api/schema.d.ts` (gen:api), `specialist-assessments.tsx` + test -- marker
- [x] `backend/tests/test_prompt_data.py`, `test_tool_gateway.py`, `test_research_fetch.py` (httpx `MockTransport`, no real network), `test_parsing*` html, updates to `test_assessments_specialists.py`, `test_registry*.py` -- I/O matrix

**Acceptance Criteria:**
- Given an assessment run, when the specialists run, then every data read goes through the gateway, leaves `platform_tool_calls` rows, and the run still produces Assessments.
- Given the code, when the tool catalogue is listed, then no write, delete, send or approve tool exists, and `lint-imports` passes.
- Given a snapshot, when an Assessment cites `{kind: research_snapshot, id, span}`, then evidence checking accepts in-range spans and rejects unknown ids or out-of-range spans.
- Given denials and failures, when traces and `platform_tool_calls` are read, then they hold ids and reason codes only, never page or customer text.

## Implementation Notes

- **Gateway shape:** `ToolGateway(settings, engine=?, transport=?, allowlist=?).call(ctx, tool, args, uow=?)`. Read tools run in the caller's Unit of Work when one is given (the specialist node's `prepare`), so the read, its `platform_tool_calls` row and any denial trace commit together; otherwise the gateway opens one. The research fetch refuses `uow=` (RuntimeError) and records in its own UoW after the network work.
- **Denied reads in the executor:** a denied `intake.requirement.list` reads nothing, so the task has nothing to assess (no model call, task succeeds, as with no active Requirements); a denied `gaps.gap.list` gives a prompt without Gaps. Both are audited.
- **Invalid arguments:** malformed or foreign ids (passages, chunks, catalogue kind) are `out_of_scope`. `knowledge.chunk.search` embedding failures propagate (no fail reason fits; no seeded Agent holds it). Its embed call precedes the first statement only when the gateway opened the UoW.
- **Migration chain:** `0038_tool_gateway` revises `0038_workflows_decisions` (Story 5.5, written in the same working tree at the same time); on a branch without 5.5 it must revise `0037_requirement_tags`.
- **Config versions:** N+1 copies the current version (semver kept, so trace actors stay `<agent>@0.1.0`) with `tool_permissions = [intake.requirement.list, gaps.gap.list]`, id `uuid5(SEED_NAMESPACE, "<agent>/config/tool-gateway")`, and bumps `registry_agents.row_version`.
- **`knowledge.chunk.search`** was already an action open to every human role (Story 3.3 search); that grant is unchanged. The six new actions have no human grants.
- **Neutralising:** runs of 3+ `<`/`>` become U+2039/U+203A character for character; labels and attribute values are reduced to `[A-Za-z0-9_.:/@-]`.
- **Snapshot text:** `.html` parsed with stdlib `html.parser` (script, style, noscript, template, svg, iframe, object and head metadata dropped); `text/plain` uses the `.txt` parser. The research snapshot resolver takes no version and checks spans against the stored extracted text.

## Spec Change Log

## Review Triage Log

## Design Notes

The gateway, not the handler, writes the audit and usage row, so no handler can skip it. Research fetch splits across the layers: the platform fetcher does network work with no UoW open, and `knowledge` then stores the snapshot in one short UoW. A redirect is followed only after its `Location` passes the same scheme and host check as the first URL.

## Verification

**Commands:**
- `cd backend && uv run pytest tests/test_prompt_data.py tests/test_tool_gateway.py tests/test_research_fetch.py tests/test_assessments_specialists.py tests/test_registry*.py tests/test_parsing*.py` -- expected: pass (Postgres tests on psa_test, both app and owner URLs)
- `cd backend && uv run ruff check . && uv run mypy app && uv run lint-imports` -- expected: clean
- `cd backend && uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` -- expected: clean on psa_test
- `cd web && npm run typecheck && npm run lint && npx vitest run src/components/opportunities/specialist-assessments.test.tsx` -- expected: pass
