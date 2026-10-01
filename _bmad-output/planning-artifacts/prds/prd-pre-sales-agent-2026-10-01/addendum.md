# Addendum: Agentic AI Presales Platform PRD

Technical and supporting material that belongs to architecture or solution design rather than to the PRD itself.

## Technical direction (from the orchestration engine spec; for bmad-architecture to confirm)

- **Orchestration:** LangGraph for stateful agent workflows (branching, parallel tasks, negotiation loops, human interrupts). Temporal is considered when long-running workflows need stronger durability guarantees.
- **Backend:** Python and FastAPI. Pydantic for agent contracts and schema validation.
- **Data:** PostgreSQL for business and decision data; LangGraph checkpointer for workflow state; object storage for documents.
- **Frontend:** Next.js and React. REST plus SSE or WebSockets for live workflow progress (FR-3).
- **Models:** OpenAI and/or Anthropic, via LangChain integrations or direct SDKs.
- **Observability:** OpenTelemetry and LangSmith.
- **Security:** OIDC SSO; RBAC/ABAC with a separate policy enforcement layer.
- **Principle:** keep agent reasoning, workflow orchestration, business state, security and authorization, human approval, and audit/observability separate. Agent contracts and state models stay independent of the orchestration framework, so they can move to an alternative (OpenAI Agents SDK, Google ADK, Semantic Kernel, CrewAI).

## Spec sections reused by downstream workflows

| Spec section | Use |
|---|---|
| §7 Agent registry metadata, §10 Agent result schema | Architecture: agent contracts (FR-25, FR-56) |
| §9 PresalesState | Architecture: workflow state model (extend with Gap, Assumption Condition/Contingency, Estimate Version, Actuals) |
| §14 Conflict types and example, §15 Negotiation protocol (8 rounds) and limits | Architecture: FR-30, FR-32 |
| §21 Failure recovery table | Architecture: FR-18, FR-19 |
| §23 API endpoints | Architecture: starting API surface. Add Gaps, Clarification Questions, Estimates, Actuals, Knowledge Sources |
| §24 Core tables | Architecture: starting data model. Add `gaps`, `clarification_questions`, `estimates`, `estimate_versions`, `estimate_lines`, `actuals`, `knowledge_sources`, `checklists` |
| §26 Epics US-001–US-016 | Epics and stories: reuse acceptance criteria where they map to FRs |
| §28 Testing strategy, incl. prompt-injection failure test | Epics and stories: test requirements |

## Changes from the original spec, and why

- **Scope widened from engine to platform.** The PRD now covers the knowledge base, intake, estimate, proposal generation, CRM integration and UI that the spec marked out of scope.
- **Gap detection and estimates added as core features (4.4, 4.9).** They were not in the spec. Discovery showed that estimates fall 20–50% short because of unknown requirements and underestimated integrations, not because of disagreement between functions. The PM's more conservative view already usually wins.
- **Negotiation moved to R3.** In R1, Conflicts are shown to the presales engineer for a decision.
- **Actuals and Calibration added (4.14).** There is no historical data, so the platform has to create it.
- **Opportunity Agent, Case Study Agent and Evidence Agent from the spec roster are not named.** Opportunity context is part of intake. Case Study matching becomes past-project evidence in R4 (FR-52), because no past project data exists yet. Evidence validation is a platform rule (FR-25), not an agent.
- **Clarification Agent** is realized as FR-11 and FR-12. **Proposal Agent** is realized as FR-47.
