# Addendum — pre-sales-agent brief

Depth that belongs to downstream documents (PRD, architecture), kept here so the brief stays at 1–2 pages.

## Source specification

`docs/BMAD Implementation Specification — LangGraph Agent Orchestration Engine.md` (v1.0, status: proposed) is the main technical input. Sections that feed directly into later workflows:

| Spec section | Downstream home |
|---|---|
| §4 Architecture, §5 Technology decisions, §32 Final architectural decision | Architecture |
| §7 Agent registry, §9 Shared state, §10 Agent output contract | Architecture (agent contracts) |
| §11–§19 Workflow, planning, parallelism, conflicts, negotiation, human-in-the-loop (HITL), replanning, scenarios, critic/red team | PRD (functional requirements) |
| §21 Failure handling, §22 Security, §25 NFRs | PRD (NFRs) + Architecture |
| §23 API, §24 Database | Architecture |
| §26 Epics & stories, §27 DoD, §28 Testing, §29 Phases | Epics & stories / sprint planning |

## Technical direction stated in the source (not yet challenged)

- LangGraph orchestration; FastAPI; PostgreSQL; LangGraph checkpointer; Temporal later for durable long-running workflows.
- Pydantic contracts; OpenTelemetry + LangSmith; OIDC + RBAC/ABAC policy layer; REST + SSE/WebSockets.
- OpenAI / Anthropic as LLM providers.
- Principle: separate agent reasoning, orchestration, business state, security, human approval, audit.

## Landscape research digest (2026-10-01)

Most sources are vendor-authored. Treat the numbers as indicative only.

- **Commoditised:** RFP and questionnaire Q&A, content-library retrieval, grounded drafting with citations. Tools: Loopio, Responsive, Qvidian, Arphie, Inventive, AutogenAI, Tribble, Thalamus. Their "multi-agent" claims amount to separating drafting from QA.
- **Closest presales analogue:** Vivun Ava (AI sales engineer). Its +37% technical-win claim comes from a vendor-commissioned survey.
- **Apparent white space:** reconciling feasibility, delivery estimates and commercial terms across specialist agents, with a decision trace. We found no competitor here, though that does not prove none exists.
- **Pain benchmarks:** ~25 hours per RFP and 45% average win rate (Loopio 2025, self-reported). Sales engineers spend ~56% of time on direct sales work (Consensus 2025). No independent data on win-rate uplift.
- **Multi-agent risks:** the MAST taxonomy (arXiv 2503.13657) lists 14 failure modes and finds gains over single-agent baselines are often small. Anthropic's orchestrator-worker system used ~15x the tokens of a normal chat and helps most on parallel, independent subtasks. Evidence for negotiation and debate loops is thin.
- **Intralogistics:** vendor design and simulation tools (e.g. AutoStore Grid Designer) are the credible source of feasibility data. The platform should call them rather than have the LLM estimate. No intralogistics-specific AI presales agents found.

Implication (as researched): the white space is feasibility and delivery assessment with a decision trace, not RFP drafting. Later discovery narrowed the brief's positioning further. The core is surfacing unknowns and integration risk *before* estimating; reconciliation and negotiation between agents are secondary, and commercial scope is deferred. Benchmark any multi-agent design against a single-agent baseline.
