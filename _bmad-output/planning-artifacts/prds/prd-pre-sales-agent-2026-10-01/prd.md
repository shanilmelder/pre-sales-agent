---
title: "PRD: Agentic AI Presales Platform (pre-sales-agent)"
status: draft
created: 2026-10-01
updated: 2026-10-01
---

# PRD: Agentic AI Presales Platform

*Working title. Confirm.*

## 0. Document Purpose

This PRD defines the full Agentic AI Presales Platform for the product, architecture and delivery teams, and for the sponsor (Head of Delivery). It builds on two inputs and does not repeat them:

- **Product brief:** `../../briefs/brief-pre-sales-agent-2026-10-01/brief.md`. Covers the problem, the evidence and the case for building rather than buying.
- **Orchestration engine specification:** `docs/BMAD Implementation Specification — LangGraph Agent Orchestration Engine.md`. Covers technical direction, agent contracts, the API and the data model.

The PRD covers the **whole product**, divided into four **Releases** (§6). Every feature and FR is tagged with the Release that delivers it. Terms in §3 are used exactly as defined. Features in §4 contain globally numbered FRs. Inferred content is tagged `[ASSUMPTION]` inline and collected in §16. Technology choices are kept in `addendum.md`.

## 1. Vision

We win most of the enterprise software deals we pursue, then deliver them over budget. Delivery estimates usually come in 20–50% too low. The causes are requirements nobody surfaced and integrations nobody challenged. This platform exists so that **the deals we win are deals we can deliver**.

The platform is a workbench for the presales engineer. Customer input arrives by email, call or Teams meeting. The platform turns it into structured requirements, finds what is missing before anyone estimates, and drafts the questions to send to the customer. Specialist AI agents for engineering, project management, security and commercial assess the solution against our own product and integration knowledge. Critic and Red Team agents argue that it is harder than it looks. Every remaining unknown becomes an explicit assumption in the estimate, carried into the proposal as a condition or a priced contingency. Humans review, challenge and approve. Each step is recorded in a decision trace.

After delivery, the platform records actual effort against the estimate. Over time this builds the history the company lacks today, and the platform learns which requirements and integrations we consistently underestimate. Estimates get better with every closed project, not just faster.

## 2. Target User

### 2.1 Jobs To Be Done

- **Presales engineer (primary):** "When a new opportunity lands, help me find what I don't know yet, so I don't commit the company to an estimate that delivery can't hit." Functional: structure messy input, find gaps, build a defensible estimate. Emotional: confidence that nothing obvious was missed; cover when an assumption later fails.
- **Engineering, PM and security reviewers:** "Show me exactly what I'm being asked to vouch for, with the evidence, so I can review in minutes, not hours."
- **Sales representative:** "Tell me what to ask the customer and how the proposal is progressing, without making me a bottleneck."
- **Commercial lead:** "Make sure contingencies and conditions are priced and visible before the proposal goes out."
- **Head of Delivery (sponsor):** "When a project overruns, show me which assumption failed and who accepted it. Over time, show me that estimates are holding."
- **Platform administrator:** "Keep agents, knowledge sources and policies configured, observable and within cost."

### 2.2 Non-Users

- **Customers.** The platform is internal. Customers never log in. Clarification questions and proposals reach them through people.
- **Delivery teams during project execution.** They record actuals (FR-49), but the platform is not a project-management tool.

### 2.3 Key User Journeys

Personas are fictional.

- **UJ-1. Ravi turns a messy discovery call into an estimate he can defend.**
  Ravi, a presales engineer, receives a Teams transcript and two customer emails for a CRM migration with ERP integration. He creates an Opportunity in the workbench and uploads all three. Within minutes he sees 34 structured Requirements, 9 Gaps (for example, no data volumes and an unknown ERP version) and 7 drafted Clarification Questions. He edits two questions and sends them to the sales rep. When the answers come in, he adds them, and the Specialist Agents run. The Red Team flags the ERP integration: "Custom ERP fields: no evidence our connector supports them." **Climax:** Ravi sees an Estimate in which every Unknown is listed in the Assumptions Register as a Condition or a priced Contingency, with sources attached. **Resolution:** he submits the Estimate for review. **Edge case:** if the customer never answers a question, the Gap stays open and becomes a Contingency. It is never silently assumed away.

- **UJ-2. Lena challenges an integration effort she doesn't believe.**
  Lena, an engineering reviewer, gets a Review Request for Ravi's Estimate. She opens the integration assessment, sees the evidence the Engineering Agent used, and disagrees: the connector needs a version upgrade. She submits a Challenge with her reason. The platform reassesses only the affected Assessments, shows the delta (+3 weeks), and creates a new Estimate Version. **Climax:** her Challenge and the revised figure appear in the Decision Trace. **Resolution:** she approves the revised version.

- **UJ-3. Ravi resolves a conflict between agents.**
  The Engineering Agent says the integration takes 4 weeks; the PM Agent says 7, because of customer UAT cycles. The platform raises a Conflict showing both positions and their evidence. In Release 1, Ravi picks a position and records why. From Release 3, the platform first runs a bounded Negotiation and proposes a reconciled position with conditions, and Ravi accepts or overrides it. **Climax:** the resolution and the dissenting position are both kept in the Decision Trace.

- **UJ-4. Ravi tests whether a phased rollout de-risks the deal.** *(Release 3)*
  The customer's budget is fixed. Ravi creates a Scenario from the approved Baseline: phase 2 integrations deferred. Only the affected agents reassess. He compares the two Scenarios side by side and promotes the phased one after commercial approval. The Baseline is never modified in place.

- **UJ-5. Sam, Head of Delivery, finds out why a project overran.**
  A delivered project closed 35% over its Estimate. Sam opens the Opportunity, compares Actuals with the Estimate by line item, and sees that the overrun sits in an integration whose Assumption ("customer provides API access by Week 1") was marked as a Condition. Sam can also see who accepted it. **Climax:** the Calibration report shows this integration type is underestimated across four projects. From Release 4, when Ravi estimates this integration type, the platform suggests a higher figure with the history behind it, and he accepts or overrides it.

## 3. Glossary

- **Opportunity:** a potential deal being assessed. It has one or more Opportunity Sources and zero or more Estimates. It is the root object of the platform.
- **Opportunity Source:** raw customer input attached to an Opportunity: an email, call notes, a Teams transcript, an RFP document or a CRM record.
- **Requirement:** a single structured customer need extracted from Opportunity Sources. It is classified (functional, integration, data, security, non-functional, commercial) and linked to the source text it came from.
- **Knowledge Source:** an internal reference the agents may cite: product documentation, an integration specification, a Checklist or a past delivery record.
- **Checklist:** an expert-written list of questions or risks for a product, integration type or industry. Used in Gap detection.
- **Integration Type / Work Package:** catalogue entries (FR-65) used to classify Assessment lines, Estimate lines, Actuals and Checklists consistently.
- **Gap:** information needed to estimate reliably that is missing from the Opportunity. A Gap is open, answered, or converted to an Assumption.
- **Clarification Question:** a customer-facing question drafted to close a Gap.
- **Agent:** an AI component with a registered capability, permissions and version in the Agent Registry.
- **Specialist Agent:** an Agent that produces Assessments in one discipline: engineering, PM, security or commercial.
- **Assessment:** an Agent's structured output for a task. Contains Findings, Evidence references, Assumptions, Unknowns, Risks, a confidence level and a recommendation.
- **Finding:** a single claim within an Assessment, Critic Review or Red Team Review.
- **Evidence:** a citation that links a Finding to a Requirement, an Opportunity Source or a Knowledge Source.
- **Assumption:** a stated belief the Estimate depends on. Each is classified as a **Condition** (stated in the proposal as something the customer must provide or meet) or a **Contingency** (effort or cost added to cover the risk).
- **Unknown:** something an Agent could not determine. An Unknown must become a Gap, an Assumption or a Risk; it cannot be dropped.
- **Risk:** a possible event that would affect delivery, with likelihood and impact.
- **Assumptions Register:** the complete list of Assumptions for an Estimate Version.
- **Conflict:** incompatible positions between two or more Assessments, for example on timeline, effort, architecture or scope.
- **Negotiation:** a bounded, structured process in which Agents try to resolve a Conflict. *(Release 3)*
- **Critic Review / Red Team Review:** independent checks of the combined Assessments. The Critic checks coverage and consistency. The Red Team argues the solution is harder or riskier than stated.
- **Estimate:** the structured effort, timeline and cost forecast for delivering an Opportunity, broken into line items. Every change creates a new **Estimate Version**.
- **Baseline:** the approved Estimate Version for an Opportunity.
- **Scenario:** an alternative Estimate built from the Baseline with changed constraints. It never modifies the Baseline. *(Release 3)*
- **Review Request:** a request for a named human to review, approve or reject an Estimate Version or Assessment.
- **Challenge:** a human disagreement with a Finding or Assessment. It triggers targeted reassessment.
- **Decision Trace:** the auditable record of how an Estimate Version was produced: Requirements, Evidence, Assessments, Conflicts and their resolutions, Reviews, Challenges and approvals.
- **Proposal:** the customer-facing document generated from an approved Baseline. *(Release 2)*
- **Actuals:** recorded effort, duration and cost from delivery, by Estimate line item, with the cause of each variance.
- **Calibration:** adjustment of future Estimates based on the history of Estimates against Actuals. *(Release 4)*
- **Workflow Run:** one orchestrated execution of agents for an Opportunity, with its plan, task states and checkpoints.
- **Agent Registry:** the configuration store of Agents, their capabilities, permissions, model and prompt versions, and status.

## 4. Features

Each feature carries a Release tag: **[R1]–[R4]** (see §6).

### 4.1 Opportunity Workspace [R1]

**Description:** The presales engineer's home. It lists their Opportunities with status (intake, gaps open, assessing, in review, approved, delivered, closed) and opens a workspace per Opportunity showing Sources, Requirements, Gaps, Assessments, Conflicts, the Estimate and the Decision Trace. Realizes UJ-1 to UJ-5.

#### FR-1: Create and manage Opportunities
A presales engineer can create an Opportunity with customer name, products in scope, industry and target proposal date, and can assign collaborators.
- An Opportunity has a unique ID and an owner.
- Only the owner, collaborators and authorized roles can view it (see FR-58).

#### FR-2: Opportunity status and progress
Users with access can see the Opportunity's lifecycle status, open Gaps, open Conflicts, pending Review Requests and the current Estimate Version at a glance.
- Status changes in real time as Workflow Runs progress, without a page reload.

#### FR-3: Live workflow progress
A presales engineer can watch a running Workflow Run task by task (queued, running, completed, failed, waiting for human) and see partial results as they arrive.
- A failed task shows a visible failure state and reason. It never appears as successful.

#### FR-64: Sales representative participation
A sales representative collaborating on an Opportunity can add Opportunity Sources and customer context, view approved Clarification Questions, mark them as sent, record customer answers, and follow Opportunity status.
- A sales representative can't edit Assessments, Estimates or Assumptions.

### 4.2 Intake and Requirement Extraction [R1]

**Description:** Turns messy customer input into structured Requirements, each traceable to its source text. Realizes UJ-1.

#### FR-4: Add Opportunity Sources
A presales engineer can add Opportunity Sources by paste or file upload (email `.eml`/`.msg`, text, `.docx`, `.pdf`, Teams transcript `.vtt`/`.docx`).
- Each source is stored unchanged and versioned. Large files are kept in object storage.
- Content from sources is treated as untrusted. Instructions embedded in it are never executed (see FR-61).

#### FR-5: Extract structured Requirements
The platform extracts Requirements from all Opportunity Sources, classifies each, and links it to the exact source passage.
- Every Requirement shows its source citation. Clicking it highlights the passage.
- Duplicate or overlapping Requirements across sources are merged, and the merge is recorded.
- On the reference Opportunity set (FR-60), extraction recall is ≥90% and every extracted Requirement has a valid source citation `[ASSUMPTION]`.

#### FR-6: Edit and confirm Requirements
A presales engineer can add, edit, split, merge, delete and confirm Requirements.
- Human edits are recorded in the Decision Trace and are never overwritten by later extraction runs.

#### FR-7: Incremental intake
When a new Opportunity Source is added, the platform extracts only the new or changed Requirements and flags which existing Assessments those changes affect (feeds FR-44 in R3; in R1 the engineer chooses what to rerun).

### 4.3 Knowledge Base [R1]

**Description:** The internal knowledge the agents cite: product documentation, integration specifications and expert-written Checklists. There is no archive of past proposals, so at launch the Knowledge Base is the platform's main source of evidence. `[ASSUMPTION: product and integration documentation exists in usable form, e.g. SharePoint, Confluence or PDF.]`

#### FR-8: Ingest Knowledge Sources
A platform administrator can register Knowledge Sources (file upload in R1; SharePoint/Confluence connectors in R2) and tag them by product, integration type and version.
- Ingested content is searchable by agents, and every retrieved passage is citable as Evidence.
- Each Knowledge Source has an owner and a last-reviewed date. Sources not reviewed in 12 months are flagged as stale `[ASSUMPTION]`.

#### FR-9: Author Checklists
Designated experts can create and version Checklists of questions and known risks per product, integration type or industry.
- Checklist items can be marked mandatory. Mandatory items always produce a Gap when unanswered.

#### FR-10: Knowledge coverage visibility
A platform administrator can see which products and integration types lack documentation or Checklists. This shows where risk detection is weak.

#### FR-65: Integration Type and Work Package catalogue
A platform administrator can maintain a catalogue of Integration Types (e.g. ERP connector, SSO, data migration) and Work Packages (e.g. configuration, testing, training), with definitions.
- Checklists, Assessment line items, Estimate lines and Actuals all use the catalogue, so variance reporting (FR-50) and Calibration (FR-51) group consistently.
- Changes to the catalogue are versioned. Retired entries remain valid on historical Estimates.

### 4.4 Gap Detection and Clarification [R1]

**Description:** The core of the product. Before anyone estimates, the platform finds what is missing and drafts questions to close it. Realizes UJ-1.

#### FR-11: Detect Gaps
The platform compares Requirements against the Knowledge Base and applicable Checklists, and raises a Gap for each piece of missing information needed to estimate.
- Each Gap states why it matters (which estimate area it affects) and cites the Checklist item or Knowledge Source that triggered it.
- Gaps are ranked by estimated impact on the Estimate.
- Every unanswered mandatory Checklist item produces a Gap (deterministic, 100%).
- On the reference Opportunity set (FR-60), Gap detection finds ≥80% of the Gaps experts identified, and ≤20% of raised Gaps are judged irrelevant by the presales engineer `[ASSUMPTION]`.

#### FR-12: Draft Clarification Questions
The platform drafts a customer-ready Clarification Question for each Gap, grouped by topic and written in plain language.
- The presales engineer can edit, merge, drop or approve questions.
- Approved questions can be exported (copied, or as a `.docx`/email draft) for the sales rep to send.
- Each Clarification Question has a status (drafted, approved, sent, answered, unanswered) with the date of each change. Sent and answered dates are recorded when a user marks them.

#### FR-13: Record answers and close Gaps
A presales engineer can record customer answers against Gaps (manually or by adding a new Opportunity Source).
- Answered Gaps update the related Requirements.

#### FR-14: Unknowns cannot vanish
When an Estimate is produced, every open Gap and every Unknown must be resolved as answered, or converted to an Assumption (Condition or Contingency) or a Risk.
- The platform blocks Estimate submission while any Gap or Unknown is unresolved.

### 4.5 Workflow Orchestration [R1]

**Description:** Coordinates agents per Opportunity: plans the needed tasks, runs independent tasks in parallel, persists state, and pauses for humans. Realizes UJ-1 and UJ-3. Technical direction (LangGraph, checkpointing, durable workflows) is in `addendum.md`.

#### FR-15: Dependency-aware planning
The platform builds a Workflow Run plan from the Opportunity's Requirements, products and integration types, selecting eligible Agents by capability.
- Task dependencies are explicit. Independent tasks run concurrently.
- Plans are versioned and visible to the Opportunity's users.
- Disabled or unavailable Agents are excluded, and any tasks they would have covered are escalated to the presales engineer.

#### FR-16: Durable execution
Workflow Runs persist their state at each step and resume after an application restart or failure without losing completed work.
- Duplicate start requests for the same Opportunity return the existing run (idempotent).

#### FR-17: Human pause and resume
A Workflow Run can pause to wait for human input (Gap answers, Conflict resolution, Review Requests) for as long as needed and resume where it stopped.

#### FR-18: Bounded execution
Every task has a timeout. Every Workflow Run has configurable limits on model calls, tokens and tool calls.
- When a limit is reached, the run stops safely and notifies the presales engineer and administrator. Partial results are preserved.

#### FR-19: Failure handling
Transient model or tool failures are retried within a configured policy. Invalid Agent output is rejected and retried within limits, then escalated.
- Failures are visible on the task (FR-3) and recorded.
- A task that exceeds its timeout is marked timed out and handled by the configured recovery policy.
- If a Research source fails, the Research Agent tries another approved source where one exists.
- If the database is unavailable, the platform stops making state changes and resumes safely from the last checkpoint.
- Concurrent edits to the same Estimate Version or Requirement are detected. The second save is rejected with a prompt to reload, never applied silently over the first.

#### FR-63: Cancel and pin Workflow Runs
A presales engineer can cancel a running Workflow Run. Completed results are kept and the cancellation is recorded.
- Every Workflow Run records the versions of the Opportunity Sources, Requirements and Agent configuration it started from, so its results can be reproduced and compared.

### 4.6 Specialist Assessment [R1; Commercial R2]

**Description:** Specialist Agents assess the solution from their discipline, against Requirements and Knowledge Sources, and return structured Assessments. Realizes UJ-1.

#### FR-20: Engineering assessment [R1]
The Engineering Agent assesses technical feasibility, solution architecture and per-integration effort and complexity, citing Evidence.

#### FR-21: PM assessment [R1]
The PM Agent assesses delivery approach, phases, timeline, resourcing and customer-side dependencies (such as UAT, data and access).

#### FR-22: Security assessment [R1]
The Security Agent identifies security and compliance requirements, mandatory controls and their delivery effort.

#### FR-23: Research assessment [R1]
The Research Agent gathers approved external evidence (for example, public API documentation of a customer's third-party system) from an allow-listed set of sources.

#### FR-24: Commercial assessment [R2]
The Commercial Agent evaluates licence and services pricing, prices Contingencies, and flags margin risk. Pricing calculations call the company's pricing rules deterministically; the LLM never calculates prices `[ASSUMPTION: pricing rules can be provided as a service or table]`.

#### FR-25: Standard Assessment contract
Every Assessment includes Findings, Evidence references, Assumptions, Unknowns, Risks, a recommendation, a confidence level with basis, and a needs-human-review flag.
- Assessments that fail schema validation, contain a Finding that neither cites Evidence nor is explicitly marked as an Unknown or Assumption, or reference Evidence that doesn't exist are rejected (see FR-19).
- On the reference set, ≥95% of cited Evidence actually supports the Finding it is attached to, as judged by expert review `[ASSUMPTION]`.

#### FR-26: Integration-level granularity
Engineering, PM and security Assessments break effort down per integration and per major work package, so that later Estimate lines, Actuals and Calibration line up.

### 4.7 Critic and Red Team Challenge [R1]

**Description:** Independent agents that try to break the combined Assessments before a human sees them. Realizes UJ-1.

#### FR-27: Critic Review
The Critic Agent checks Requirement coverage, unsupported claims, contradictions, timeline consistency and dependency completeness across Assessments.

#### FR-28: Red Team Review
The Red Team Agent argues that integrations are harder, Requirements are incomplete, or capabilities are overstated, and proposes the hidden dependencies it suspects.

#### FR-29: Blocking findings
Critical Critic or Red Team Findings block Estimate submission until one of these happens: the Finding is resolved, Evidence is supplied, an authorized human overrides it with a reason (where policy permits), or the Opportunity is closed.
- Overrides are recorded in the Decision Trace with the person and reason.
- Mandatory security and authorization policies can never be overridden this way.

### 4.8 Conflict Detection and Resolution [R1; Negotiation R3]

**Description:** Finds incompatible positions between Assessments and gets them resolved, with the dissenting position kept. Realizes UJ-3.

#### FR-30: Detect Conflicts [R1]
The platform detects timeline, effort, resource, architecture, security, scope, assumption and evidence Conflicts between Assessments. It uses deterministic comparison for structured fields and LLM-assisted comparison for free text.
- Each Conflict links to the positions involved, their Evidence and a severity.
- Mandatory constraints (security policy, Checklist mandatory items) are checked by deterministic rules, never by LLM judgement alone.

#### FR-31: Human Conflict resolution [R1]
A presales engineer can resolve a Conflict by choosing a position, entering a different one, or escalating to a named reviewer, and must record a reason.

#### FR-32: Bounded Negotiation [R3]
For configured Conflict types, the platform first runs a Negotiation: Agents restate positions and Evidence, challenge each other's Assumptions, propose alternatives, and the platform evaluates the trade-offs (effort, timeline, risk, cost).
- The maximum number of rounds, time and token budget are configurable and enforced.
- The output is a proposed resolution with conditions, supporting and dissenting Agents, and the Evidence. A human accepts, modifies or rejects it.
- Consensus never overrides a mandatory constraint and is never treated as proof of correctness.
- Unresolved Negotiations escalate to a human (FR-31).

### 4.9 Estimate and Assumptions Register [R1]

**Description:** Replaces today's ad hoc estimates with one standard, structured Estimate. Realizes UJ-1, UJ-2, UJ-5.

#### FR-33: Standard Estimate structure
The platform produces an Estimate with line items by work package and integration, each showing effort, role mix, duration, Contingency and the Assessments it came from.
- All Estimate arithmetic (line totals, role-mix effort, Contingency sums, overall totals) is calculated deterministically by the platform, never by an LLM.
- Every Estimate line is tagged with an Integration Type or Work Package from the catalogue (FR-65).
- Every Estimate uses the same configurable template. `[ASSUMPTION: no company estimate template exists; one is defined during R1 with the Head of Delivery.]`

#### FR-34: Assumptions Register
Each Estimate Version has an Assumptions Register. Every Assumption is classified as a Condition or a Contingency and linked to the Gap, Unknown or Finding it came from.
- Every Contingency has a cost or effort amount. Every Condition has proposal-ready wording.
- Every Assumption records who accepted it and when. An Estimate Version cannot be submitted while any Assumption lacks an accepting person.

#### FR-35: Edit and version Estimates
A presales engineer can adjust line items and Assumptions with a reason. Every change creates a new Estimate Version. Earlier versions remain viewable and comparable.

#### FR-36: Export Estimate [R1]
A presales engineer can export the Estimate, Assumptions Register and Clarification Questions as `.xlsx` and `.docx` for use in today's proposal process.

### 4.10 Human Review, Approval and Challenge [R1 basic; R2 full]

**Description:** Keeps humans in charge of every commitment. Realizes UJ-2.

#### FR-37: Review Requests [R1]
A presales engineer can send a Review Request for an Estimate Version or specific Assessments to named engineering, PM or security reviewers.
- Reviewers see exactly what they are asked to review, with the Evidence, in one view.
- A reviewer can approve, reject, Challenge (FR-38), request more Evidence, request an alternative, or escalate to another reviewer. Each action needs a reason, except approval.
- The platform checks that the reviewer is authorized for the review type before recording the decision.
- The author of an Estimate Version can't approve their own Review Request.
- Pending Review Requests send a reminder after a configurable number of days.

#### FR-38: Challenge [R1]
A reviewer or presales engineer can Challenge a Finding or Assessment with a reason. In R1, the platform suggests which Assessments the Challenge affects, the presales engineer confirms which to rerun, and the platform shows the delta and creates a new Estimate Version. From R3, affected Assessments are identified and rerun automatically (FR-44).
- The previous version and the Challenge are preserved in the Decision Trace.
- Before the new version can be submitted, Conflict detection (FR-30) and the Critic and Red Team Reviews (FR-27, FR-28) run again on the changed Assessments.

#### FR-62: Set Baseline [R1]
A presales engineer can set an Estimate Version as the Baseline once every Review Request sent for it is approved and no blocking Finding (FR-29) or unresolved Gap or Unknown (FR-14) remains.
- Setting the Baseline is recorded in the Decision Trace with the approvers.
- A Baseline can only be replaced by setting a newer approved Estimate Version. No Workflow Run, Scenario or Agent overwrites an approved Baseline.
- From R2, the approval policies in FR-39 also apply.

#### FR-39: Approval policies [R2]
A platform administrator can configure approval policies, for example: Estimates above a value threshold need Head of Delivery approval, security Findings need security reviewer approval, and Contingencies need commercial approval.
- In addition to FR-62, a Baseline cannot be set until all policy-required approvals are given.
- Approvers cannot approve their own Estimate.

#### FR-40: Notifications [R2]
Reviewers and owners are notified of Review Requests, Challenges, approvals and blocked runs in the platform and in Microsoft Teams or email `[ASSUMPTION: Teams is the company's collaboration tool]`.
- Overdue Review Requests escalate according to policy.

### 4.11 Decision Trace [R1]

**Description:** The auditable answer to "how did we arrive at this number?". Realizes UJ-2, UJ-3, UJ-5.

#### FR-41: Record the Decision Trace
For each Estimate Version, the platform records the Requirements, Evidence, Assessments, Critic and Red Team Findings, Conflicts and their resolutions, Negotiations, Challenges, Reviews, overrides and approvals, with actor and timestamp.
- The trace contains decision-relevant events and Evidence, not raw model chain-of-thought.
- Trace records cannot be edited or deleted by users.

#### FR-42: Explore the Decision Trace
Any user with access can navigate from any Estimate line or Assumption to the Findings, Evidence and human decisions behind it, and compare two Estimate Versions.

### 4.12 Dynamic Replanning and Scenarios [R3]

**Description:** Keeps Estimates current when things change, and lets users test alternatives safely. Realizes UJ-4.

#### FR-43: Change detection
When Requirements, Gap answers, constraints or Knowledge Sources change materially, the platform identifies the affected Assessments and Estimate lines.

#### FR-44: Targeted reassessment
The platform builds a revised plan that reruns only the affected tasks, revalidates, and produces a new Estimate Version.
- Unaffected Assessments are reused, not rerun.
- Changes to a Baseline require approval under FR-39 before they take effect.

#### FR-45: Create Scenarios
A presales engineer can create a Scenario from the Baseline by changing constraints (timeline, budget, scope, phasing, resourcing, technology or integration assumptions). Only the affected Agents reassess.
- Scenarios never modify the Baseline.

#### FR-46: Compare and promote Scenarios
Users can compare Scenarios side by side (effort, timeline, cost, Risks, Assumptions). An authorized approver can promote a Scenario, which creates a new Baseline version.

### 4.13 Proposal Generation [R2]

**Description:** Produces the customer-facing Proposal from the approved Baseline, so that Conditions and Contingencies reach the customer as written.

#### FR-47: Generate Proposal
A presales engineer can generate a Proposal draft from the Baseline using the company Proposal template `[ASSUMPTION: a standard template exists or will be provided]`. It includes scope, delivery approach, timeline, the Conditions (verbatim), and pricing including Contingencies as configured.
- Every claim about company capability in the Proposal must trace to a Knowledge Source. Untraceable claims are flagged.

#### FR-48: Proposal approval and release
A Proposal can only be released as final after required approvals (FR-39). The platform never sends a Proposal or any customer communication by itself.

### 4.14 Actuals and Calibration [Capture R1; Calibration R4]

**Description:** Closes the loop between estimate and delivery. Builds the history the company lacks. Realizes UJ-5.

#### FR-49: Record Actuals [R1]
When a project closes (and optionally at milestones), a delivery manager can record Actuals per Estimate line, with a variance cause (unknown requirement, integration complexity, customer delay, scope change, estimation error, other).
- Actuals can be entered manually or imported from a file `[ASSUMPTION: no timesheet/PSA integration in R1]`.

#### FR-50: Estimate-vs-actual reporting [R1]
The Head of Delivery can view variance by Opportunity, product, integration type, work package and variance cause, and can drill down to the failed Assumptions in the Decision Trace.

#### FR-51: Calibration [R4]
Once enough closed projects exist for an integration type or work package `[ASSUMPTION: at least 5]`, the platform suggests adjustments to future Estimates based on historical variance and shows the reasoning and data behind each suggestion.
- Calibration suggestions are visible and can be overridden. They never apply silently.
- Calibration is reported separately so its effect on accuracy can be measured.

#### FR-52: Past-project evidence [R4]
Specialist Agents can cite closed Opportunities (Estimate, Actuals and variance causes) as Evidence for similar Requirements and integrations.

### 4.15 Integrations [R2]

**Description:** Connects the platform to where opportunities and knowledge already live, replacing manual paste and upload where useful.

#### FR-53: CRM integration
The platform can create or link an Opportunity from a HubSpot deal record (with its associated company and contacts) and write back status and the approved Estimate summary to configured HubSpot deal properties.
- Write-back is limited to configured fields and is audited.

#### FR-54: Email and Teams intake
A presales engineer can attach Outlook emails and Teams meeting transcripts directly to an Opportunity, via Microsoft 365 integration `[ASSUMPTION]`.

#### FR-55: Knowledge connectors
A platform administrator can connect SharePoint and Confluence spaces as Knowledge Sources with scheduled re-sync.

### 4.16 Agent Registry and Administration [R1]

**Description:** Controls which Agents exist and what they may do. Realizes the platform administrator JTBD.

#### FR-56: Register and version Agents
A platform administrator can register Agents with capabilities, input/output schema versions, model and prompt versions, tool permissions and status.
- Agent IDs are unique. Disabled Agents receive no new tasks. Configuration changes are audited.
- Every Assessment records the Agent, model and prompt versions that produced it.

#### FR-57: Tool permissions
Each Agent has explicit tool permissions (read, write, delete, send, approve). Permissions are checked before every tool call.
- Unauthorized tool calls are blocked and audited.
- No Agent has send or approve permission.

#### FR-58: Users, roles and access
Users sign in with company SSO `[ASSUMPTION: Microsoft Entra ID]`. Roles: presales engineer, sales rep, reviewer (engineering, PM, security), commercial, delivery manager, Head of Delivery, platform administrator.
- Opportunity access is limited to owner, collaborators and roles granted by policy.

#### FR-59: Observability and cost
A platform administrator can see per-Workflow-Run and per-Agent traces, latency, failures, retries, token use and model cost, linked by correlation ID.
- Cost per Opportunity is reported (input to SM-C2).

#### FR-60: Evaluation harness
A platform administrator can run Agents against a set of reference Opportunities with known good answers to detect quality regressions before changing a model, prompt or Agent version.
- Includes a comparison against a single-agent baseline, to test whether the multi-agent design earns its cost (see brief, Risks).
- A release candidate ships only if it meets the quality bars in FR-5, FR-11 and FR-25 on the reference set and does not regress any of them by more than 5 points.
- **Decision rule:** if the single-agent baseline comes within 5 points of the multi-agent design on Gap detection and integration-risk Findings at materially lower cost, the simpler design is adopted for that step `[ASSUMPTION]`.
- The reference set starts with at least 10 Opportunities, reconstructed from past deals where possible, annotated by senior presales and delivery experts with the Gaps and risks they would expect to find `[ASSUMPTION]`.

### 4.17 Safety guardrails [R1]

#### FR-61: Untrusted content handling
Content from Opportunity Sources, Research results and Knowledge Sources is treated as data, never as instructions. Prompt-injection attempts are detected where possible and never grant Agents extra actions.

## 5. Non-Goals

- **Not a CRM, PSA or project-management tool.** The platform links to these and does not replace them.
- **No autonomous customer communication.** The platform never sends emails, questions or Proposals to customers. People do.
- **No autonomous commitments.** Agents never approve Estimates, Proposals, prices or contractual terms.
- **Not an RFP questionnaire-answering tool.** Security questionnaires and RFP Q&A libraries are well served by commercial tools and can be integrated later if needed.
- **No contract negotiation or contract drafting.**
- **Not a customer portal.** Customers never access the platform.
- **No pricing engine.** Commercial assessment calls existing pricing rules. The platform does not own pricing logic.

## 6. Release Plan

The full product is specified above. It is built and released in four Releases so that the Head of Delivery sees estimate quality improve early. Epics and sprint planning follow this order.

| Release | Goal | Features |
|---|---|---|
| **R1: Estimation core** | A presales engineer takes a real Opportunity from raw input to a reviewed, assumption-backed Estimate, and delivery records Actuals. | 4.1, 4.2, 4.3 (upload), 4.4, 4.5, 4.6 (engineering, PM, security, research), 4.7, 4.8 (detection and human resolution), 4.9, 4.10 (Review Requests, Challenge), 4.11, 4.14 (capture and reporting), 4.16, 4.17 |
| **R2: Governance and integration** | Approvals by policy, Proposals generated from Baselines, and the platform connected to CRM, Microsoft 365 and knowledge spaces. | 4.6 (commercial), 4.10 (approval policies, notifications), 4.13, 4.15 |
| **R3: Advanced orchestration** | Estimates stay current as things change; alternatives can be tested; Agents negotiate Conflicts before humans step in. | 4.8 (Negotiation), 4.12 |
| **R4: Learning** | Estimates improve from history. | 4.14 (Calibration, past-project evidence) |

R4 depends on data, not just code: it starts when enough closed projects with Actuals exist (FR-51). `[NOTE FOR PM]` With implementation projects lasting months, expect R4 to be 9–18 months after R1 goes live, whatever the build speed.

## 7. Success Metrics

**Primary**
- **SM-1: Estimate accuracy.** Variance between the Baseline and Actuals on delivered projects estimated in the platform. Target: within ±15% `[ASSUMPTION]`. Today: 20–50% under (source unconfirmed; see Q1). Validates FR-11–FR-14, FR-20–FR-29, FR-33–FR-34, FR-51.

**Secondary**
- **SM-2: Adoption.** Share of new Opportunities (>20/month) estimated in the platform. Target: ≥80% within 3 months of R1 `[ASSUMPTION]`. Validates 4.1–4.9.
- **SM-3: Unknowns surfaced early.** Share of Opportunities where Clarification Questions were sent before the Estimate was submitted. Target: ≥70% `[ASSUMPTION]`. Validates FR-11–FR-12.
- **SM-4: Variance from unsurfaced requirements.** Share of delivery variance whose cause is "unknown requirement" or "integration complexity" (FR-49). Target: falling quarter on quarter. Validates 4.4, 4.7.
- **SM-5: Traceability.** Share of overrunning projects where the failed Assumption can be identified from the Decision Trace. Target: ≥90%. Validates 4.11, FR-49–FR-50.
- **SM-7: Retrospective replay (pilot leading indicator).** Past deals with known overrun causes are run through the platform. Share of known overrun causes the platform surfaces as a Gap, Risk or Red Team Finding. Target: ≥60% `[ASSUMPTION]`. Gives evidence during the pilot, before any delivered project closes. Validates 4.4, 4.7.
- **SM-6: Review effort.** Median reviewer time per Review Request. Target: under 30 minutes `[ASSUMPTION]`. Validates FR-37.

**Counter-metrics (do not optimize)**
- **SM-C1: Win rate.** Must not fall materially as estimates become more realistic. If it drops, investigate whether the issue is pricing or the estimates themselves. Counterbalances SM-1.
- **SM-C2: Cost per Opportunity.** Model and tool cost per Opportunity must stay within the budget agreed with the sponsor. Adding Agents or Negotiation rounds to chase accuracy has a price. Counterbalances SM-1, FR-32.
- **SM-C3: Time to Estimate.** Time from Opportunity creation to Estimate submission must be no worse than today. Thoroughness that slows proposals will be bypassed. Counterbalances SM-3.
- **SM-C4: Contingency inflation.** Total Contingency as a share of the Estimate. Hitting SM-1 by padding every Estimate isn't success. Counterbalances SM-1.

## 8. Cross-Cutting NFRs

- **NFR-1: Performance.** Workflow start is acknowledged in under 2 s (P95). Status reads take under 500 ms (P95). Requirement extraction for a typical Opportunity (≤50 pages of sources) completes in under 5 minutes `[ASSUMPTION]`. Agent execution time is measured separately from API time.
- **NFR-2: Reliability.** Workflow state survives restarts (FR-16). Retries are bounded. No duplicate external side effects (CRM write-back, notifications). Partial results survive recoverable failures.
- **NFR-3: Scalability.** Supports at least 50 concurrent Workflow Runs `[ASSUMPTION: 2× peak of >20 Opportunities/month with reruns]`. Agent concurrency is limited by configuration and provider rate limits are enforced. API services scale horizontally.
- **NFR-4: Security.** SSO authentication is mandatory, and authorization is checked on every sensitive operation. Data is encrypted in transit and at rest. Secrets are held in a managed vault. Sensitive operations are audited.
- **NFR-5: Observability.** Every Workflow Run has a correlation ID. Every Agent execution, tool call, retry and failure is traceable (FR-59).
- **NFR-6: Auditability.** Decision Trace and audit records are append-only and retained for at least the contract lifetime plus 7 years `[ASSUMPTION]`.
- **NFR-7: Accessibility.** The web UI meets WCAG 2.1 AA.
- **NFR-8: Platform.** Desktop web application on current Chrome and Edge. Mobile is not a target.

## 9. Constraints and Guardrails

- **Safety and correctness:** material Findings without Evidence are rejected (FR-25). Mandatory constraints are deterministic (FR-30). Humans own every Estimate and approval. Agent consensus is not proof.
- **Privacy:** Agents receive only the data their task needs. Customer personal data in Opportunity Sources is minimised in prompts and logs, and kept out of ordinary error logs.
- **Cost:** per-run budgets (FR-18) and cost reporting (FR-59), within SM-C2.
- **Model providers:** OpenAI and/or Anthropic, subject to company approval for customer data (Q5). Agent contracts stay independent of provider and orchestration framework.

## 10. Data Governance

- **Classification:** customer Opportunity Sources and Estimates are confidential commercial data.
- **Residency:** data stays in the company's approved cloud region `[ASSUMPTION: EU]`. LLM provider data processing must have a no-training, zero- or limited-retention agreement.
- **Retention:** Opportunity Sources, Estimates, the Decision Trace and Actuals are retained per NFR-6. Lost Opportunities are retained for 3 years `[ASSUMPTION]`, then archived or deleted.
- **Access:** role- and Opportunity-scoped (FR-58). Exports are audited.

## 11. Integration and Dependencies

| Dependency | Release | Purpose |
|---|---|---|
| Company SSO (e.g. Entra ID) | R1 | Authentication, roles |
| LLM providers (OpenAI / Anthropic) | R1 | Agent reasoning |
| Object storage | R1 | Opportunity Sources, Knowledge Source files |
| Pricing rules/service | R2 | Commercial assessment (FR-24) |
| HubSpot CRM | R2 | Deal link and write-back (FR-53) |
| Microsoft 365 (Outlook, Teams, SharePoint) | R2 | Intake, notifications, Knowledge connectors |
| Confluence | R2 | Knowledge connector |
| Timesheet/PSA system | Later | Automated Actuals import (not yet scheduled) |

## 12. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| No baseline. The 20–50% figure may be anecdotal, so improvement can't be proven. | Reconstruct 10 or more past deals from signed SOWs and timesheets before R1 go-live; otherwise use the first quarter of R1 as baseline (Q1). |
| Thin Knowledge Base weakens Gap detection. | FR-10 coverage view. Checklist-writing time agreed with engineering leads as part of R1. |
| Confident but wrong agents. | Evidence requirement (FR-25), Critic/Red Team (4.7), human ownership, evaluation harness (FR-60). |
| Multi-agent cost and reliability. | Run budgets (FR-18), SM-C2, single-agent baseline comparison (FR-60). |
| Engineers bypass the workbench. | SM-C3. Exports that fit today's process (FR-36). Presales engineers involved in R1 design. |
| Delivery doesn't record Actuals, so the learning loop never starts. | FR-49 kept simple. Head of Delivery makes Actuals entry part of project closure. |
| Customer data sent to LLMs without approval. | Data-handling approval before R1 pilot (Q5). Provider agreements per §10. |
| Long time to value for R4. | R1 targets accuracy through Gap detection and challenge alone; R4 is an enhancement. |

## 13. Rollout and Change Management

- **Pilot:** R1 with 2–3 presales engineers on live Opportunities, run in parallel with today's process for 4–6 weeks `[ASSUMPTION]`.
- **Estimate template:** agreed with the Head of Delivery before R1 build completes (FR-33).
- **Training:** short workflow training for presales engineers and reviewers. Actuals-entry guidance for delivery managers.
- **Process change:** the Head of Delivery mandates the platform for all new Opportunities after the pilot, and Actuals entry at project close.

## 14. Stakeholders and Approvals

- **Head of Delivery:** sponsor. Approves this PRD, success targets and the Estimate template.
- **Presales lead:** primary-user representative. Approves workflow and UX.
- **Engineering, PM and security leads:** approve their Agents' assessment scope and Checklists.
- **Commercial lead:** approves Contingency pricing rules (R2).
- **IT security / data protection:** approves LLM data handling before the R1 pilot.

## 15. Open Questions

1. Where does the 20–50% figure come from? Do signed SOWs and delivery timesheets exist to build a baseline?
2. Which product documentation and integration specifications exist, where are they kept, and how current are they?
3. Which HubSpot deal properties and pipeline stages should be read and written back, and should HubSpot pipeline stage changes trigger platform actions?
4. Is there a company Proposal template and an existing pricing rule set or service?
5. Does company policy permit sending customer requirement data to OpenAI and/or Anthropic? In which region?
6. What is today's typical cycle time from first contact to proposal (baseline for SM-C3)?
7. Who records Actuals at project close, and from which system?
8. What cost-per-Opportunity budget is acceptable to the sponsor (SM-C2)?

## 16. Assumptions Index

- §4.3, FR-8: Product and integration documentation exists in usable form. Sources not reviewed in 12 months are flagged as stale.
- FR-5, FR-11, FR-25: Quality bars (≥90% extraction recall, ≥80% Gap recall with ≤20% irrelevant, ≥95% Evidence support).
- FR-24: Pricing rules can be provided as a service or table.
- FR-33: No company estimate template exists; one is defined in R1.
- FR-40: Microsoft Teams is the company's collaboration tool.
- FR-47: A company Proposal template exists or will be provided.
- FR-49: No timesheet/PSA integration in R1.
- FR-51: Calibration needs at least 5 closed projects per integration type or work package.
- FR-54: Microsoft 365 integration for email and Teams intake.
- FR-58: SSO is Microsoft Entra ID.
- FR-60: 5-point single-agent decision rule. Reference set of at least 10 expert-annotated Opportunities.
- SM-1: Target ±15% estimate accuracy.
- SM-2: Target ≥80% adoption within 3 months of R1.
- SM-3: Target ≥70% of Opportunities with questions sent before Estimate.
- SM-6: Target under 30 minutes median review time.
- SM-7: Target ≥60% of known overrun causes surfaced in retrospective replay.
- NFR-1: Extraction under 5 minutes for ≤50 pages.
- NFR-3: At least 50 concurrent Workflow Runs.
- NFR-6: Retention for contract lifetime plus 7 years.
- §10: Data residency in the EU. Lost Opportunities retained 3 years.
- §13: Pilot with 2–3 engineers for 4–6 weeks.
