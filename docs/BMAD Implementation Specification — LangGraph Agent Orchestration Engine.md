# LANGGRAPH AGENT ORCHESTRATION ENGINE
## BMAD Implementation Specification

**Project:** Agentic AI Presales Platform  
**Component:** Agent Orchestration Engine  
**Version:** 1.0  
**Status:** Proposed Implementation Specification  
**Architecture:** LangGraph + FastAPI + PostgreSQL  
**Durable Workflow Integration:** Temporal (planned for production-grade long-running workflows)

---

# 1. PROJECT OVERVIEW

## 1.1 Purpose

Build a stateful, multi-agent orchestration engine that coordinates AI agents throughout the presales lifecycle.

The engine must enable agents to:

- Understand incoming customer requirements.
- Retrieve internal and external evidence.
- Conduct independent assessments.
- Identify conflicts between agent recommendations.
- Negotiate alternatives using structured rounds.
- Reassess decisions when constraints change.
- Route work dynamically to relevant agents.
- Request human intervention when necessary.
- Generate validated, evidence-backed decisions.
- Preserve decision history and execution state.

The orchestration engine must support genuinely agentic behavior rather than relying on a fixed sequence of independent LLM calls.

## 1.2 Business Problem

Traditional presales workflows require people to manually coordinate multiple activities:

- Understanding customer requests.
- Researching company capabilities.
- Assessing technical feasibility.
- Estimating delivery timelines.
- Evaluating security requirements.
- Resolving conflicting recommendations.
- Preparing proposals.
- Reviewing assumptions and risks.

This creates delays, inconsistent decisions, duplicated work, and limited traceability.

The orchestration engine automates coordination while retaining human authority over high-impact decisions.

## 1.3 Product Vision

Create an AI-powered presales coordination system that transforms customer requests into validated, evidence-backed, human-approved proposals through controlled multi-agent collaboration.

## 1.4 Primary Business Outcomes

1. Reduce manual coordination across presales activities.
2. Improve consistency of technical and delivery assessments.
3. Identify conflicts and missing information earlier.
4. Reduce unnecessary repeated agent execution.
5. Improve proposal quality and evidence traceability.
6. Preserve human control over commercial and customer-facing commitments.

---

# 2. PRODUCT SCOPE

## 2.1 In Scope

The orchestration engine will provide:

1. Central Presales Orchestrator.
2. Agent capability registry integration.
3. Workflow planning and task decomposition.
4. Agent routing and delegation.
5. Shared workflow state management.
6. Parallel agent execution.
7. Structured agent communication.
8. Conflict detection.
9. Multi-agent negotiation.
10. Consensus and unresolved-disagreement management.
11. Critic and Red Team workflow integration.
12. Human approval and challenge workflows.
13. Dynamic replanning.
14. What-if scenario orchestration.
15. Failure handling and controlled retries.
16. Workflow persistence and recovery.
17. Decision trace generation.
18. Agent execution observability.
19. Integration with the Opportunity Digital Twin.
20. Integration with the Proposal Engine.

## 2.2 Out of Scope

The orchestration engine will not independently implement:

- The complete frontend application.
- The full RAG ingestion pipeline.
- The underlying knowledge graph.
- The complete CRM integration layer.
- The proposal document rendering engine.
- The pricing calculation engine.
- The enterprise identity provider.
- The complete evaluation platform.
- Autonomous contract negotiation.
- Unrestricted external communications.

These capabilities will be exposed through APIs, tools, or other platform services.

## 2.3 Core Design Principle

**LangGraph controls agent workflow execution. It does not replace business databases, security policy enforcement, deterministic calculations, or enterprise workflow durability.**

---

# 3. USERS AND ACTORS

## 3.1 Presales Manager

Responsibilities:

- Initiate or review opportunities.
- Inspect agent assessments.
- Review conflicts and recommendations.
- Challenge decisions.
- Approve or reject proposals.
- Request additional analysis.

## 3.2 Sales Representative

Responsibilities:

- Submit customer requests.
- Review opportunity information.
- Provide missing customer context.
- Review clarification questions.
- Track proposal progress.

## 3.3 Engineering Reviewer

Responsibilities:

- Review technical feasibility.
- Validate architecture assumptions.
- Challenge technical estimates.
- Approve technical recommendations when required.

## 3.4 Project Manager

Responsibilities:

- Review delivery estimates.
- Validate resource assumptions.
- Review milestones and dependencies.
- Challenge unrealistic delivery plans.

## 3.5 Security Reviewer

Responsibilities:

- Review security findings.
- Validate mandatory controls.
- Resolve security-related escalations.

## 3.6 Platform Administrator

Responsibilities:

- Register agents.
- Configure agent capabilities.
- Manage policies and workflow configurations.
- Monitor execution health.
- Manage model and prompt versions.

---

# 4. SYSTEM ARCHITECTURE

## 4.1 High-Level Architecture

```text
                 USER INTERFACE
               Next.js + React
                       |
                       v
                  FASTAPI
                 API LAYER
                       |
                       v
             PRESALES ORCHESTRATOR
                  LangGraph
                       |
          +------------+-------------+
          |            |             |
          v            v             v
      INTAKE        RESEARCH      REQUIREMENT
       AGENT          AGENT         AGENT
          |            |             |
          +------------+-------------+
                       |
                       v
               SPECIALIST AGENTS
                       |
          +------------+-------------+
          |            |             |
          v            v             v
      ENGINEERING      PM          SECURITY
          |            |             |
          +------------+-------------+
                       |
                       v
               CONFLICT DETECTOR
                       |
                       v
              NEGOTIATION ENGINE
                       |
                       v
                CONSENSUS CHECK
                       |
                       v
                CRITIC + RED TEAM
                       |
                       v
                HUMAN APPROVAL
                       |
                       v
               PROPOSAL ENGINE
```

## 4.2 Supporting Infrastructure

```text
LangGraph
    |
    +--> PostgreSQL
    |      - Opportunity references
    |      - Workflow metadata
    |      - Decision records
    |      - Agent execution records
    |
    +--> Checkpoint Storage
    |      - Workflow state
    |      - Resume information
    |
    +--> Agent Registry
    |      - Agent capabilities
    |      - Model configuration
    |      - Permissions
    |
    +--> Tool Gateway
    |      - RAG
    |      - Research
    |      - CRM
    |      - Documents
    |
    +--> Observability
    |      - OpenTelemetry
    |      - LangSmith
    |
    +--> Human Approval Service
           - Approval requests
           - Decisions
           - Challenge events
```

---

# 5. TECHNOLOGY DECISIONS

## 5.1 Primary Technology Stack

| Component | Technology | Responsibility |
|---|---|---|
| Backend | Python + FastAPI | API and orchestration service |
| Agent orchestration | LangGraph | Stateful agent workflow |
| LLM integration | LangChain model integrations or direct provider SDKs | Model access |
| LLM providers | OpenAI / Anthropic | Reasoning and content generation |
| Structured validation | Pydantic | Validate agent inputs and outputs |
| Main database | PostgreSQL | Business and workflow metadata |
| Workflow checkpointing | LangGraph checkpointer | Save and restore graph state |
| Durable workflows | Temporal, when required | Long-running workflow durability |
| Observability | OpenTelemetry + LangSmith | Tracing and debugging |
| Authentication | OIDC / enterprise identity provider | User identity |
| Authorization | RBAC/ABAC + policy engine | Access control |
| API communication | REST + WebSockets/SSE | Requests and workflow updates |
| Testing | pytest | Automated testing |

## 5.2 Why LangGraph

LangGraph is selected because the orchestration workflow requires:

- Stateful execution.
- Conditional branching.
- Parallel execution.
- Repeated negotiation rounds.
- Human interruption and resumption.
- Selective reassessment.
- Explicit workflow transitions.
- Persistent execution state.

The framework provides a graph-based abstraction for modeling these behaviors.

## 5.3 Alternatives

The architecture must avoid hard-coding business logic into framework-specific constructs wherever practical.

Potential alternatives include:

- OpenAI Agents SDK.
- CrewAI.
- Google ADK.
- Microsoft Semantic Kernel.

The agent contracts, business state models, and policy interfaces should remain independent of the orchestration framework.

---

# 6. ORCHESTRATION ENGINE RESPONSIBILITIES

The Presales Orchestrator is responsible for coordinating the opportunity lifecycle.

## 6.1 Core Responsibilities

1. Receive a workflow initiation request.
2. Load the opportunity state.
3. Validate workflow prerequisites.
4. Determine the required analysis tasks.
5. Build a dependency-aware execution plan.
6. Select eligible agents.
7. Execute independent tasks concurrently where appropriate.
8. Collect and validate agent outputs.
9. Identify conflicts and missing evidence.
10. Trigger negotiation when required.
11. Validate consensus.
12. Invoke Critic and Red Team agents.
13. Determine whether human approval is required.
14. Pause and resume execution as needed.
15. Generate the approved workflow result.
16. Persist the final decision state.
17. Publish workflow events.
18. Record execution metadata and decision trace.

## 6.2 Non-Responsibilities

The Orchestrator must not:

- Invent missing customer information.
- Override mandatory security policies.
- Independently approve commercial commitments.
- Send customer-facing communications without authorization.
- Treat agent consensus as proof of correctness.
- Silently overwrite approved decisions.
- Allow agents to execute unrestricted tools.

---

# 7. AGENT REGISTRY

## 7.1 Purpose

The Agent Registry defines which agents are available and what each agent is authorized to do.

## 7.2 Required Agent Metadata

Each agent registration must include:

```json
{
  "agent_id": "engineering_agent",
  "name": "Engineering Agent",
  "description": "Assesses technical feasibility",
  "capabilities": [
    "technical_feasibility",
    "architecture_assessment",
    "technical_risk_analysis"
  ],
  "input_schema_version": "1.0",
  "output_schema_version": "1.0",
  "model_provider": "configured_provider",
  "model_name": "configured_model",
  "prompt_version": "1.0",
  "tool_permissions": [
    "rag.read",
    "architecture.read"
  ],
  "status": "active"
}
```

The example model and prompt values are placeholders.

## 7.3 Registry Requirements

- Agents must have unique IDs.
- Disabled agents must not receive new tasks.
- Agent versions must be recorded.
- Tool permissions must be validated before execution.
- The orchestrator must select agents based on capabilities.
- Agent configuration changes must be auditable.
- Incompatible agent versions must be rejected.

---

# 8. AGENT ROSTER

## 8.1 Core Agents

| Agent | Responsibility |
|---|---|
| Intake Agent | Extract customer and opportunity information |
| Requirement Agent | Structure and classify requirements |
| Opportunity Agent | Analyze business objectives and opportunity context |
| Research Agent | Gather approved external evidence |
| RAG Agent | Retrieve internal company knowledge |
| Case Study Agent | Match previous projects |
| Engineering Agent | Assess technical feasibility |
| PM Agent | Estimate delivery plans and resources |
| Security Agent | Identify security and compliance requirements |
| Commercial Agent | Evaluate cost and commercial scenarios |
| Clarification Agent | Identify missing information and prepare questions |
| Proposal Agent | Generate proposal content |
| Critic Agent | Independently review outputs |
| Red Team Agent | Challenge assumptions and identify weaknesses |
| Evidence Agent | Validate source traceability |

## 8.2 Agent Execution Rules

- Each agent has a defined capability contract.
- Each agent receives only the information required for its task.
- Each agent must return structured output.
- Every output must identify its sources and assumptions.
- Agents must explicitly identify unknown information.
- Agent outputs must not directly modify protected business records.
- State changes must pass through authorized application services.

---

# 9. SHARED WORKFLOW STATE

## 9.1 Purpose

The workflow state stores the information required to coordinate agents during a single opportunity workflow.

It is not a replacement for the Opportunity Digital Twin.

The Digital Twin remains the authoritative business record.

## 9.2 State Structure

```python
from typing import Any, Literal
from typing_extensions import TypedDict


class PresalesState(TypedDict, total=False):
    workflow_id: str
    opportunity_id: str
    workflow_version: str

    workflow_status: Literal[
        "initialized",
        "running",
        "waiting_for_approval",
        "completed",
        "failed",
        "cancelled"
    ]

    execution_plan: list[dict[str, Any]]

    requirements: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    agent_results: dict[str, dict[str, Any]]

    conflicts: list[dict[str, Any]]
    negotiations: list[dict[str, Any]]
    decisions: list[dict[str, Any]]

    assumptions: list[dict[str, Any]]
    unknowns: list[dict[str, Any]]
    risks: list[dict[str, Any]]

    approval_requests: list[dict[str, Any]]
    approval_results: list[dict[str, Any]]

    critic_findings: list[dict[str, Any]]
    red_team_findings: list[dict[str, Any]]

    scenario_id: str | None
    baseline_version: str | None

    final_result: dict[str, Any] | None

    errors: list[dict[str, Any]]
    event_ids: list[str]
```

## 9.3 State Management Rules

1. Each workflow must have a unique identifier.
2. Each opportunity must have a unique identifier.
3. State updates must be validated.
4. State transitions must be auditable.
5. The workflow must not overwrite the approved baseline without authorization.
6. Checkpoint state must be associated with a workflow version.
7. Sensitive information must not be included unnecessarily in workflow state.
8. Agent outputs must be validated before entering shared state.

---

# 10. STANDARD AGENT OUTPUT CONTRACT

Every agent must return a standardized result.

## 10.1 Agent Result Schema

```json
{
  "agent_id": "engineering_agent",
  "agent_version": "1.0",
  "task_id": "task_123",
  "status": "completed",
  "objective": "Assess technical feasibility",
  "summary": "The proposed solution is feasible subject to API access.",
  "findings": [],
  "evidence": [],
  "assumptions": [],
  "unknowns": [],
  "risks": [],
  "recommendations": [],
  "constraints": [],
  "confidence": {
    "level": "medium",
    "basis": "Evidence completeness and technical validation"
  },
  "requires_human_review": false,
  "created_at": "ISO-8601 timestamp"
}
```

## 10.2 Required Validation

The application must validate:

- Agent identity.
- Task identity.
- Output schema.
- Status.
- Evidence references.
- Assumption references.
- Risk structure.
- Confidence format.
- Permission compliance.

Invalid outputs must be rejected or routed to controlled recovery.

---

# 11. WORKFLOW DESIGN

## 11.1 Primary Workflow

The primary workflow is:

```text
START
  |
  v
LOAD OPPORTUNITY
  |
  v
VALIDATE INPUT
  |
  v
BUILD EXECUTION PLAN
  |
  v
INTAKE / REQUIREMENTS
  |
  v
KNOWLEDGE RETRIEVAL
  |
  v
SPECIALIST ASSESSMENTS
  |
  v
CONFLICT DETECTION
  |
  +------ Conflicts? ------+
  |                        |
  Yes                      No
  |                        |
  v                        |
NEGOTIATION                |
  |                        |
  v                        |
CONSENSUS CHECK            |
  |                        |
  +-----------+------------+
              |
              v
         CRITIC REVIEW
              |
              v
          RED TEAM
              |
              v
      APPROVAL REQUIREMENT?
          /          \
        Yes           No
         |             |
         v             |
    HUMAN REVIEW       |
         |             |
         +------+------+
                |
                v
       FINAL VALIDATION
                |
                v
       PROPOSAL GENERATION
                |
                v
       SAVE WORKFLOW RESULT
                |
                v
               END
```

## 11.2 Conditional Branches

The workflow must support:

- Missing information → clarification workflow.
- Conflicting assessments → negotiation workflow.
- Critical findings → reassessment.
- Human challenge → targeted re-evaluation.
- Material requirement change → dynamic replanning.
- Tool failure → controlled retry or recovery.
- Unresolved disagreement → escalation.
- Unauthorized action → block and audit.

---

# 12. DYNAMIC TASK PLANNING

## 12.1 Purpose

Determine which agents need to run for a given opportunity.

## 12.2 Planning Inputs

- Customer requirements.
- Opportunity type.
- Industry.
- Technical complexity.
- Security constraints.
- Existing evidence.
- Available agents.
- Agent capabilities.
- Workflow policies.
- Human review requirements.

## 12.3 Planning Process

1. Analyze the current opportunity.
2. Identify required assessments.
3. Identify task dependencies.
4. Determine which tasks can execute in parallel.
5. Select eligible agents.
6. Validate agent permissions.
7. Build the execution plan.
8. Persist the plan.
9. Begin execution.

## 12.4 Example

```json
{
  "plan_id": "plan_001",
  "tasks": [
    {
      "task_id": "task_research",
      "agent_id": "research_agent",
      "depends_on": []
    },
    {
      "task_id": "task_engineering",
      "agent_id": "engineering_agent",
      "depends_on": [
        "task_requirements",
        "task_knowledge"
      ]
    },
    {
      "task_id": "task_pm",
      "agent_id": "pm_agent",
      "depends_on": [
        "task_requirements",
        "task_engineering"
      ]
    }
  ]
}
```

The plan is illustrative. Actual dependencies must be defined by the workflow configuration.

---

# 13. PARALLEL AGENT EXECUTION

## 13.1 Requirements

The orchestrator must execute independent tasks concurrently when safe.

Examples:

- Research and internal knowledge retrieval.
- Case-study matching and opportunity analysis.
- Engineering and security assessments when their inputs are available.

## 13.2 Execution Rules

- Independent tasks may run in parallel.
- Dependent tasks must wait for prerequisites.
- Each task must have a timeout.
- Failed tasks must not silently appear successful.
- Results must be associated with their originating task.
- The workflow must preserve partial results.
- Parallel execution must respect model and tool rate limits.

## 13.3 Acceptance Criteria

- Independent tasks execute concurrently.
- Dependent tasks execute only after prerequisites are satisfied.
- A failed task produces a visible failure state.
- Partial results remain available after an individual task fails.

---

# 14. CONFLICT DETECTION

## 14.1 Purpose

Identify incompatible agent recommendations before a decision is finalized.

## 14.2 Conflict Types

1. Timeline conflict.
2. Resource conflict.
3. Architecture conflict.
4. Security conflict.
5. Budget conflict.
6. Scope conflict.
7. Evidence conflict.
8. Requirement conflict.
9. Assumption conflict.

## 14.3 Detection Approach

Use a combination of:

- Deterministic rules.
- Structured field comparison.
- Dependency validation.
- LLM-assisted semantic comparison.

Deterministic rules must be used for mandatory constraints whenever possible.

## 14.4 Example

```json
{
  "conflict_id": "conflict_001",
  "type": "timeline_conflict",
  "agents": [
    "engineering_agent",
    "pm_agent"
  ],
  "positions": [
    {
      "agent_id": "engineering_agent",
      "position": "10 weeks"
    },
    {
      "agent_id": "pm_agent",
      "position": "14 weeks"
    }
  ],
  "severity": "high",
  "status": "open"
}
```

---

# 15. MULTI-AGENT NEGOTIATION ENGINE

## 15.1 Purpose

Resolve conflicts through structured, bounded negotiation.

## 15.2 Negotiation Protocol

### Round 1 — Independent Positions

Each agent submits its recommendation, evidence, constraints, and assumptions.

### Round 2 — Conflict Detection

The system identifies incompatible positions.

### Round 3 — Challenge

Agents evaluate the assumptions behind conflicting recommendations.

### Round 4 — Alternatives

Agents propose alternative scenarios.

### Round 5 — Trade-Off Analysis

The system compares feasibility, cost, timeline, risk, and dependencies.

### Round 6 — Consensus Evaluation

The system determines whether a sufficiently supported decision can be produced.

### Round 7 — Critic Review

An independent Critic evaluates the proposed consensus.

### Round 8 — Escalation

Unresolved conflicts are sent to a human reviewer.

## 15.3 Negotiation Limits

The system must enforce:

- Configurable maximum rounds.
- Configurable execution timeout.
- Maximum model-call budget.
- Maximum token budget.
- Maximum tool-call budget.
- Escalation when no acceptable consensus is reached.

## 15.4 Consensus Output

```json
{
  "decision_id": "decision_001",
  "status": "proposed",
  "recommended_timeline_weeks": 12,
  "conditions": [
    "API access available by Week 1",
    "Existing accelerator is reusable",
    "Mandatory security testing is retained"
  ],
  "risks": [
    "Customer UAT duration remains uncertain"
  ],
  "supporting_agents": [
    "engineering_agent"
  ],
  "dissenting_agents": [
    "pm_agent"
  ],
  "requires_human_approval": true
}
```

## 15.5 Acceptance Criteria

- Negotiation starts only when a relevant conflict is detected.
- Each negotiation round has a defined objective.
- Agent outputs follow a structured schema.
- Mandatory constraints cannot be overridden by consensus.
- The maximum number of rounds is enforced.
- Unresolved disagreements trigger escalation.
- The decision trace preserves supporting and dissenting positions.

---

# 16. HUMAN-IN-THE-LOOP WORKFLOW

## 16.1 Supported Actions

The human reviewer must be able to:

- Approve.
- Reject.
- Challenge.
- Request additional evidence.
- Request an alternative.
- Modify a constraint.
- Escalate to an expert.
- Request reassessment.

## 16.2 Workflow Behavior

When a workflow requires human review:

1. Create an approval request.
2. Persist the current workflow state.
3. Mark the workflow as waiting for approval.
4. Notify the authorized reviewer.
5. Receive the review decision.
6. Validate reviewer authorization.
7. Record the decision and reason.
8. Resume or terminate the workflow according to the decision.

## 16.3 Human Challenge

A challenge must:

1. Preserve the previous decision.
2. Identify affected assumptions and tasks.
3. Reassess affected agents.
4. Trigger negotiation if required.
5. Run validation again.
6. Produce a new decision version.
7. Record the challenge and resolution.

---

# 17. DYNAMIC REPLANNING

## 17.1 Trigger Conditions

Replanning may be triggered by:

- New customer information.
- Changed requirements.
- Changed budget.
- Changed timeline.
- Changed technical constraints.
- Failed agents.
- New security requirements.
- Human challenge.
- Newly discovered evidence.

## 17.2 Replanning Process

```text
NEW INFORMATION
       |
       v
CHANGE DETECTION
       |
       v
IDENTIFY AFFECTED TASKS
       |
       v
BUILD REVISED PLAN
       |
       v
VALIDATE DEPENDENCIES
       |
       v
EXECUTE AFFECTED TASKS
       |
       v
REASSESS DECISIONS
       |
       v
REVALIDATE OUTPUT
```

## 17.3 Acceptance Criteria

- Material changes trigger reassessment.
- Unaffected tasks are not rerun unnecessarily.
- Previous plans remain accessible.
- The new plan is versioned.
- Material changes requiring approval are blocked until approved.

---

# 18. WHAT-IF SCENARIO ORCHESTRATION

## 18.1 Purpose

Allow users to evaluate alternative constraints without changing the approved opportunity baseline.

## 18.2 Supported Variables

- Timeline.
- Budget.
- Resource availability.
- Scope.
- Technology choices.
- Delivery phases.
- Integration assumptions.

## 18.3 Scenario Lifecycle

```text
APPROVED BASELINE
       |
       v
CREATE SCENARIO
       |
       v
MODIFY CONSTRAINTS
       |
       v
REASSESS AFFECTED AGENTS
       |
       v
RENEGOTIATE
       |
       v
VALIDATE
       |
       v
COMPARE SCENARIOS
       |
       v
HUMAN DECISION
```

## 18.4 Acceptance Criteria

- Scenario execution does not modify the baseline.
- Each scenario has a unique identifier.
- Scenario assumptions are stored.
- Scenario results are comparable.
- Only authorized users can promote a scenario.
- Promotion creates a new opportunity version.

---

# 19. CRITIC AND RED TEAM INTEGRATION

## 19.1 Critic Agent

The Critic must evaluate:

- Requirement coverage.
- Evidence quality.
- Unsupported claims.
- Timeline consistency.
- Architecture consistency.
- Dependency completeness.
- Risk coverage.
- Contradictions.

## 19.2 Red Team Agent

The Red Team must evaluate:

- Unrealistic delivery assumptions.
- Missing integrations.
- Unsupported company capabilities.
- Incomplete requirements.
- Security weaknesses.
- Contradictory evidence.
- Hidden dependencies.

## 19.3 Blocking Rules

Critical findings must prevent workflow completion until one of the following occurs:

1. The issue is resolved.
2. The relevant evidence is supplied.
3. An authorized human explicitly overrides the finding where policy permits.
4. The workflow is terminated.

Mandatory security and authorization policies cannot be overridden through ordinary Critic or Red Team workflows.

---

# 20. DECISION TRACE

## 20.1 Purpose

Provide a transparent, auditable record of how the system arrived at a decision.

## 20.2 Trace Components

- Customer requirement.
- Source evidence.
- Agent assessments.
- Conflicts.
- Negotiation rounds.
- Alternatives.
- Critic findings.
- Red Team findings.
- Risk assessment.
- Human approvals.
- Final decision.
- Decision version.

## 20.3 Trace Example

```text
Customer Requirement
        |
        v
Evidence Retrieved
        |
        v
Engineering Assessment
        |
        v
PM Assessment
        |
        v
Timeline Conflict
        |
        v
Negotiation
        |
        v
Alternative Scenarios
        |
        v
Critic Review
        |
        v
Human Approval
        |
        v
Final Decision
```

The trace must expose decision-relevant evidence and events, not private model chain-of-thought.

---

# 21. FAILURE HANDLING

## 21.1 Failure Categories

- Model API failure.
- Tool API failure.
- Invalid agent output.
- Workflow timeout.
- Database failure.
- Permission denial.
- Conflicting state updates.
- Agent deadlock.
- Negotiation limit exceeded.
- Human approval timeout.

## 21.2 Recovery Strategy

| Failure | Required Behavior |
|---|---|
| Transient model failure | Retry according to configured policy |
| Invalid output | Validate, retry within limits, then escalate |
| Research API failure | Try an approved alternative if available |
| Agent timeout | Mark task as timed out and apply recovery policy |
| Database failure | Stop unsafe state changes and recover safely |
| Unauthorized tool call | Block and audit |
| Negotiation deadlock | Stop and escalate |
| Approval timeout | Keep workflow waiting or escalate according to policy |
| Duplicate request | Return existing workflow result when idempotency permits |

## 21.3 Acceptance Criteria

- Failures are visible.
- Retries are bounded.
- Duplicate side effects are prevented.
- Partial results are preserved.
- Unrecoverable failures produce a clear workflow status.
- Sensitive information is excluded from ordinary error logs.

---

# 22. SECURITY REQUIREMENTS

## 22.1 Agent Permissions

Each agent must have:

- A unique identity.
- A defined role.
- Explicit tool permissions.
- Data access restrictions.
- Model configuration.
- Version metadata.

## 22.2 Tool Permission Categories

- READ.
- WRITE.
- DELETE.
- SEND.
- APPROVE.

## 22.3 Mandatory Controls

- Validate tool permissions before execution.
- Enforce human approval for high-impact actions.
- Treat external content as untrusted.
- Protect secrets.
- Enforce tenant isolation where applicable.
- Audit sensitive operations.
- Prevent agents from bypassing authorization.
- Restrict direct access to protected business records.

## 22.4 Prohibited Actions

Agents must not independently:

- Approve their own high-impact decisions.
- Send external communications without authorization.
- Modify contractual commitments.
- Override security policies.
- Access data outside their authorized scope.

---

# 23. API DESIGN

## 23.1 API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/opportunities/{id}/workflows` | Start an orchestration workflow |
| GET | `/api/v1/workflows/{id}` | Retrieve workflow status |
| GET | `/api/v1/workflows/{id}/trace` | Retrieve decision trace |
| GET | `/api/v1/workflows/{id}/tasks` | Retrieve task status |
| POST | `/api/v1/workflows/{id}/resume` | Resume a paused workflow |
| POST | `/api/v1/workflows/{id}/cancel` | Cancel a workflow |
| POST | `/api/v1/workflows/{id}/challenge` | Submit a human challenge |
| POST | `/api/v1/workflows/{id}/scenarios` | Create a what-if scenario |
| GET | `/api/v1/workflows/{id}/scenarios` | List scenarios |
| POST | `/api/v1/approvals/{id}/decision` | Submit an approval decision |
| GET | `/api/v1/agents` | List available agents |
| GET | `/api/v1/agents/{id}` | Retrieve agent metadata |

All endpoints must enforce authentication, authorization, input validation, and audit requirements.

## 23.2 Workflow Initiation Request

```json
{
  "opportunity_id": "opp_123",
  "workflow_type": "presales_assessment",
  "mode": "standard",
  "requested_by": "user_123",
  "options": {
    "enable_negotiation": true,
    "enable_critic": true,
    "enable_red_team": true
  }
}
```

## 23.3 Workflow Response

```json
{
  "workflow_id": "wf_123",
  "opportunity_id": "opp_123",
  "status": "running",
  "created_at": "ISO-8601 timestamp"
}
```

---

# 24. DATABASE DESIGN

## 24.1 Core Tables

| Table | Purpose |
|---|---|
| `opportunities` | Opportunity references |
| `workflow_runs` | Workflow execution records |
| `workflow_plans` | Execution plans and versions |
| `workflow_tasks` | Task definitions and statuses |
| `agent_registry` | Agent capabilities and versions |
| `agent_executions` | Agent execution records |
| `agent_results` | Structured agent outputs |
| `conflicts` | Detected conflicts |
| `negotiation_rounds` | Negotiation history |
| `decisions` | Decision records |
| `decision_evidence` | Evidence relationships |
| `assumptions` | Assumption register |
| `risks` | Risk register |
| `approval_requests` | Human approval requests |
| `approval_decisions` | Human decisions |
| `scenarios` | What-if scenario metadata |
| `workflow_events` | Workflow events |
| `audit_events` | Security and audit records |

## 24.2 Database Rules

- Use unique identifiers.
- Store timestamps in UTC.
- Preserve version history.
- Apply appropriate foreign-key constraints.
- Use transactions for critical state changes.
- Prevent unauthorized cross-tenant access.
- Keep large documents in object storage rather than relational tables.

---

# 25. NON-FUNCTIONAL REQUIREMENTS

The following are proposed initial targets and must be validated through testing.

## 25.1 Performance

- API acknowledgement for workflow initiation: P95 under 2 seconds, excluding external dependency delays.
- Workflow status retrieval: P95 under 500 ms under expected load.
- Independent tasks should execute concurrently when safe.
- Agent execution time must be measured separately from API response time.

## 25.2 Reliability

- Workflow state must survive application restarts when checkpointing is enabled.
- Retries must be bounded.
- Duplicate external side effects must be prevented.
- Partial workflow results must remain available after recoverable failures.

## 25.3 Scalability

- Support multiple opportunities executing concurrently.
- Apply configurable limits to agent concurrency.
- Enforce provider-specific rate limits.
- Support horizontal scaling of stateless API services.

## 25.4 Security

- Authentication is mandatory.
- Authorization is enforced for every sensitive operation.
- Sensitive data must be protected in transit and at rest.
- High-impact actions require policy validation and approval where configured.

## 25.5 Observability

- Every workflow has a unique correlation ID.
- Every agent execution is traceable.
- Failures and retries are recorded.
- Model usage and tool calls are measurable.

---

# 26. EPICS AND USER STORIES

## EPIC 01 — Orchestration Foundation

### US-001 — Initialize Orchestration Workflow

**Priority:** P0

**User Story**

As a Presales Manager, I want to initiate an orchestration workflow for an opportunity so that the AI agents can begin assessing it.

**Acceptance Criteria**

- Given a valid opportunity, when an authorized user starts a workflow, a unique workflow ID is created.
- The workflow loads the correct opportunity version.
- The workflow state is initialized.
- The workflow status is visible.
- Duplicate requests are handled idempotently.

**Definition of Done**

- API implemented.
- Workflow graph implemented.
- State persistence configured.
- Unit and integration tests pass.
- Audit event is recorded.

---

### US-002 — Build Execution Plan

**Priority:** P0

**User Story**

As a Presales Manager, I want the orchestrator to build a dependency-aware execution plan so that required assessments are completed in the correct order.

**Acceptance Criteria**

- The planner identifies required tasks.
- Task dependencies are explicit.
- Independent tasks can run in parallel.
- Unavailable agents are excluded or escalated.
- The plan is versioned.
- The plan is visible to authorized users.

**Definition of Done**

- Planner implemented.
- Dependency validation implemented.
- Plan versioning implemented.
- Unit and integration tests pass.

---

### US-003 — Agent Registry Integration

**Priority:** P0

**User Story**

As a Platform Administrator, I want to register and manage agent capabilities so that the orchestrator can select eligible agents.

**Acceptance Criteria**

- Agents have unique identifiers.
- Capabilities and permissions are stored.
- Disabled agents cannot receive new tasks.
- Agent versions are recorded.
- Incompatible agent outputs are rejected.

**Definition of Done**

- Registry API implemented.
- Permission validation implemented.
- Registry tests pass.
- Audit events recorded.

---

## EPIC 02 — Agent Execution

### US-004 — Execute Specialist Agents

**Priority:** P0

**User Story**

As a Presales Manager, I want specialist agents to execute their assigned assessments so that the opportunity can be evaluated from multiple perspectives.

**Acceptance Criteria**

- Agents receive validated inputs.
- Agent outputs follow the standard schema.
- Task status is recorded.
- Failures are visible.
- Independent tasks execute concurrently where appropriate.

**Definition of Done**

- Agent execution service implemented.
- Structured output validation implemented.
- Parallel execution tests pass.
- Failure handling tested.

---

### US-005 — Validate Agent Results

**Priority:** P0

**User Story**

As a Presales Manager, I want agent outputs validated so that invalid or incomplete assessments do not silently enter the decision process.

**Acceptance Criteria**

- Outputs are validated against schemas.
- Missing required fields are detected.
- Invalid evidence references are rejected.
- Invalid results trigger recovery or escalation.
- Valid results are stored with version metadata.

**Definition of Done**

- Validation service implemented.
- Error handling implemented.
- Unit and integration tests pass.

---

## EPIC 03 — Conflict Detection and Negotiation

### US-006 — Detect Agent Conflicts

**Priority:** P0

**User Story**

As a Presales Manager, I want the system to detect conflicting agent recommendations so that important disagreements are resolved before proposal generation.

**Acceptance Criteria**

- Timeline conflicts are detected.
- Resource conflicts are detected.
- Mandatory constraint violations are identified.
- Conflicts are linked to source assessments.
- Conflict severity is recorded.

**Definition of Done**

- Conflict detection service implemented.
- Deterministic validation rules implemented.
- Conflict test suite passes.

---

### US-007 — Execute Negotiation Rounds

**Priority:** P0

**User Story**

As a Presales Manager, I want agents to negotiate conflicting recommendations so that they can propose evidence-backed alternatives.

**Acceptance Criteria**

- Negotiation starts only when appropriate.
- Each round has a defined objective.
- Agents provide structured positions.
- Alternatives are generated.
- Maximum rounds are enforced.
- Unresolved conflicts are escalated.

**Definition of Done**

- Negotiation graph implemented.
- Structured output validation implemented.
- Deadlock and timeout tests pass.
- Negotiation history is recorded.

---

### US-008 — Generate Consensus Proposal

**Priority:** P0

**User Story**

As a Presales Manager, I want the system to produce a consensus proposal with conditions and unresolved disagreements so that I can review the recommended decision.

**Acceptance Criteria**

- The proposal includes supporting evidence.
- Conditions and assumptions are explicit.
- Dissenting positions are preserved.
- Mandatory constraints are enforced.
- Human approval is requested when required.

**Definition of Done**

- Consensus logic implemented.
- Policy checks integrated.
- Decision history recorded.
- Consensus test suite passes.

---

## EPIC 04 — Human Governance

### US-009 — Request Human Approval

**Priority:** P0

**User Story**

As a Presales Manager, I want to approve or reject high-impact decisions so that AI recommendations remain under human control.

**Acceptance Criteria**

- Approval requests are created when policy requires them.
- Authorized reviewers are identified.
- The workflow pauses while waiting.
- Decisions are recorded.
- The workflow resumes or terminates based on the decision.

**Definition of Done**

- Approval service implemented.
- Authorization checks implemented.
- Pause/resume tests pass.
- Approval audit records are available.

---

### US-010 — Challenge an AI Decision

**Priority:** P0

**User Story**

As a Presales Manager, I want to challenge an AI decision so that the system reassesses the relevant evidence and recommendations.

**Acceptance Criteria**

- A challenge identifies the target decision.
- The previous decision is preserved.
- Affected agents are identified.
- Reassessment is executed.
- A new decision version is created.
- The challenge is auditable.

**Definition of Done**

- Challenge API implemented.
- Dependency-aware reassessment implemented.
- Versioning tests pass.
- Audit trace is available.

---

## EPIC 05 — Dynamic Replanning and Scenarios

### US-011 — Replan After Constraint Changes

**Priority:** P0

**User Story**

As a Presales Manager, I want the system to replan when requirements change so that affected assessments remain current.

**Acceptance Criteria**

- Material changes are detected.
- Affected tasks are identified.
- Unaffected tasks are preserved.
- A new plan version is created.
- Required approvals are enforced.

**Definition of Done**

- Change detection implemented.
- Replanning graph implemented.
- Replanning tests pass.

---

### US-012 — Create What-If Scenarios

**Priority:** P1

**User Story**

As a Presales Manager, I want to simulate alternative timelines and resource constraints so that I can compare possible delivery approaches.

**Acceptance Criteria**

- Scenarios are isolated from the baseline.
- Scenario constraints are stored.
- Relevant agents reassess the scenario.
- Scenario results can be compared.
- Promotion requires authorization.

**Definition of Done**

- Scenario workflow implemented.
- Baseline protection tested.
- Scenario comparison UI integrated.

---

## EPIC 06 — Validation and Evidence

### US-013 — Execute Critic Review

**Priority:** P0

**User Story**

As a Presales Manager, I want the Critic Agent to independently review the proposed solution so that important errors are identified before approval.

**Acceptance Criteria**

- Requirements are checked.
- Unsupported claims are flagged.
- Inconsistent timelines are flagged.
- Critical findings block completion.
- Findings can be resolved and revalidated.

**Definition of Done**

- Critic integration implemented.
- Blocking rules tested.
- Review history recorded.

---

### US-014 — Generate Decision Trace

**Priority:** P0

**User Story**

As a Presales Manager, I want to inspect the evidence and decisions behind a recommendation so that I can understand and audit the result.

**Acceptance Criteria**

- Agent assessments are linked to the decision.
- Conflicts and negotiation rounds are recorded.
- Evidence references are preserved.
- Human approvals are recorded.
- Previous decision versions remain accessible.

**Definition of Done**

- Decision trace data model implemented.
- Trace API implemented.
- Trace completeness tests pass.

---

## EPIC 07 — Reliability and Observability

### US-015 — Recover Failed Workflows

**Priority:** P0

**User Story**

As a Platform Administrator, I want workflows to recover safely from transient failures so that opportunities are not lost when a service becomes unavailable.

**Acceptance Criteria**

- Transient failures trigger bounded retries.
- Failed tasks are visible.
- Duplicate side effects are prevented.
- Partial results are preserved.
- Unrecoverable failures are escalated.

**Definition of Done**

- Retry policies configured.
- Idempotency controls implemented.
- Failure injection tests pass.

---

### US-016 — Monitor Agent Execution

**Priority:** P0

**User Story**

As a Platform Administrator, I want to monitor agent execution so that I can diagnose failures, latency, and cost.

**Acceptance Criteria**

- Each workflow has a correlation ID.
- Agent executions are traceable.
- Model and tool usage are recorded.
- Errors and retries are visible.
- Performance metrics are available.

**Definition of Done**

- OpenTelemetry integrated.
- LangSmith integrated where applicable.
- Monitoring dashboard available.
- Trace correlation tests pass.

---

# 27. DEFINITION OF DONE — PLATFORM-WIDE

A feature is considered complete only when:

1. Its acceptance criteria are satisfied.
2. Unit tests pass.
3. Integration tests pass.
4. Relevant security tests pass.
5. Failure scenarios are tested.
6. Audit requirements are implemented.
7. Observability is available.
8. API documentation is updated.
9. User-facing behavior is documented.
10. Required approvals and permissions are enforced.
11. No unresolved critical defects remain.
12. The feature is deployed to the designated environment.

---

# 28. TESTING STRATEGY

## 28.1 Unit Tests

Test:

- State transformations.
- Routing logic.
- Conflict detection.
- Schema validation.
- Policy decisions.
- Dependency calculations.

## 28.2 Integration Tests

Test:

- Agent execution.
- Database persistence.
- Checkpoint recovery.
- Approval workflow.
- Tool gateway integration.
- Negotiation flow.
- Decision trace generation.

## 28.3 End-to-End Tests

Test a complete opportunity lifecycle:

```text
RFP
 ↓
Intake
 ↓
Requirements
 ↓
Research + RAG
 ↓
Engineering + PM + Security
 ↓
Conflict Detection
 ↓
Negotiation
 ↓
Critic
 ↓
Human Approval
 ↓
Proposal
```

## 28.4 Failure Tests

Test:

- Model timeout.
- Invalid agent output.
- Tool API failure.
- Database interruption.
- Duplicate workflow request.
- Negotiation deadlock.
- Human approval delay.
- Unauthorized tool call.
- Prompt injection in an external document.

---

# 29. IMPLEMENTATION PHASES

## Phase 1 — Orchestration Foundation

Deliver:

- FastAPI service.
- LangGraph workflow.
- Shared state model.
- Agent registry.
- Agent execution interface.
- PostgreSQL persistence.
- Basic observability.

## Phase 2 — Specialist Agent Coordination

Deliver:

- Intake Agent.
- Requirement Agent.
- Research Agent.
- Engineering Agent.
- PM Agent.
- Security Agent.
- Parallel execution.

## Phase 3 — Negotiation and Decision Intelligence

Deliver:

- Conflict detection.
- Negotiation rounds.
- Consensus proposal.
- Critic integration.
- Decision trace.

## Phase 4 — Human Governance

Deliver:

- Approval workflow.
- Human challenge loop.
- Workflow interruption and resumption.
- Approval audit history.

## Phase 5 — Dynamic Replanning

Deliver:

- Change detection.
- Dependency-aware reassessment.
- What-if scenarios.
- Scenario comparison.

## Phase 6 — Production Hardening

Deliver:

- Advanced failure recovery.
- Security testing.
- Observability dashboards.
- Performance testing.
- Durable workflow integration where required.

---

# 30. BMAD IMPLEMENTATION GUIDANCE

Use this specification as the source document for the BMAD planning and implementation process.

## Recommended BMAD sequence

### Step 1 — Product Brief

Define:

- Business problem.
- Product vision.
- Target users.
- Core value proposition.
- MVP scope.
- Success metrics.

### Step 2 — PRD

Define:

- Functional requirements.
- Non-functional requirements.
- User stories.
- Acceptance criteria.
- Workflow behavior.
- Security requirements.

### Step 3 — Architecture

Define:

- LangGraph architecture.
- Agent contracts.
- State schema.
- Persistence strategy.
- Database schema.
- API design.
- Security model.
- Observability.

### Step 4 — Epics and Stories

Break the implementation into independently deliverable epics and stories.

Each story must include:

- User story.
- Description.
- Dependencies.
- Acceptance criteria.
- Definition of done.
- Test requirements.

### Step 5 — Implementation

Implement incrementally:

1. Workflow foundation.
2. Agent contracts.
3. Specialist agents.
4. Negotiation.
5. Human governance.
6. Reliability.
7. Production hardening.

---

# 31. MVP ACCEPTANCE CRITERIA

The orchestration engine MVP is accepted when:

- A workflow can be initiated for a valid opportunity.
- The orchestrator can create and execute a dependency-aware plan.
- Multiple specialist agents can execute in parallel.
- Agent outputs are validated and stored.
- Conflicting assessments can be detected.
- Agents can negotiate through bounded rounds.
- Consensus includes evidence, assumptions, and conditions.
- Unresolved conflicts are escalated.
- Critic findings can block completion.
- Human approval can pause and resume a workflow.
- Human challenges trigger targeted reassessment.
- Workflow state survives supported interruptions.
- Unauthorized actions are blocked.
- Decision history is auditable.
- Observability is available.
- Automated tests cover critical workflows and failure paths.

---

# 32. FINAL ARCHITECTURAL DECISION

**Recommended implementation:**

- LangGraph for agent workflow orchestration.
- FastAPI for the backend API.
- PostgreSQL for structured business and decision data.
- LangGraph checkpointing for workflow state persistence.
- Temporal when durable, long-running business workflows require stronger execution guarantees.
- Pydantic for agent contracts and schema validation.
- OpenTelemetry + LangSmith for observability.
- A separate policy enforcement layer for authorization and approvals.

**Core architectural principle:**

The system must separate:

1. Agent reasoning.
2. Workflow orchestration.
3. Business state.
4. Security and authorization.
5. Human approval.
6. Audit and observability.

This separation allows the platform to evolve its agents and models without compromising business controls or workflow reliability.