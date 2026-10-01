---
title: "Product Brief: Agentic AI Presales Platform (pre-sales-agent)"
status: review
created: 2026-10-01
updated: 2026-10-01
---

# Product Brief: Agentic AI Presales Platform

**In one line:** a workbench that helps presales engineers find unknown requirements and integration risk *before* committing to a delivery estimate, so that the deals we win are deals we can deliver.

## The Problem

We sell enterprise software as licences plus implementation. We win most of the deals we pursue. Then we find out what they really cost: **delivery estimates usually come in 20–50% too low**.

The cause is in how proposals are put together. Opportunities arrive by email, phone call or Teams meeting and pass by hand between sales, presales, engineering, project management, security and commercial. Key customer information is often missing, so people fill gaps with assumptions that never get written down. Each function assesses the deal separately. When engineering and project management disagree, the more conservative project-management view usually wins, and estimates are *still* too low. The disagreement is not the problem: both sides are estimating from the same incomplete picture. The two failures that hurt most are:

- **Unknown requirements**: scope that existed at proposal time but that nobody surfaced.
- **Integrations harder than assumed**: complexity that was estimated optimistically and never challenged.

There is no standard estimation method. Each presales engineer builds the estimate in their own way, and no archive of past proposals, estimates or actuals exists. Nobody can tell which kinds of integration we consistently underestimate.

The consequences:

- **Margin erosion and overruns** on deals we have already won and committed to. This is the expensive part.
- **Long proposal cycles** caused by rework and chasing the customer for missing information. With more than 20 opportunities a month, this effort is constant. `[OPEN: typical cycle time]`
- **No traceability.** When an estimate proves wrong, nobody can reconstruct which assumption failed or who accepted the risk.

The **Head of Delivery** sponsors this initiative because their teams absorb the overruns. Success is measured by whether delivery estimates hold, not by how fast proposals go out.

## The Solution

A **workbench for the presales engineer** that finds unknowns and integration risk before an estimate goes to the customer, and turns what remains into explicit, priced assumptions.

For every opportunity, the platform:

1. **Extracts requirements** from emails, call notes and Teams transcripts into a structured requirement list.
2. **Finds what's missing** by checking requirements against product documentation, integration specifications and expert-written checklists, then drafts clarification questions for the customer *before* anyone estimates.
3. **Challenges integration risk.** Specialist agents for engineering, project management (PM) and security assess each integration against evidence. A Red Team agent argues it is harder than it looks.
4. **Produces a standard, structured estimate** in place of today's ad hoc one. Every remaining unknown becomes an explicit assumption that appears in the proposal as a condition or a priced contingency.
5. **Records the decision trace**: which evidence, assumptions and reviewer decisions produced the estimate.
6. **Captures estimate against actual** once delivery finishes. This builds the history we lack today and, over time, lets the platform learn which integrations we consistently underestimate.

Agents run inside an orchestrated workflow, with LangGraph as the proposed engine (see addendum). When agent assessments conflict, the platform shows the conflict to the presales engineer with each side's evidence. Bounded agent negotiation is a later enhancement, not the core, because the evidence so far is that disagreement between functions does not cause underestimation.

## Who It Serves

- **Presales engineer (primary user):** works the opportunity in the workbench and owns the estimate.
- **Engineering, PM and security reviewers:** brought in by the presales engineer to check or challenge specific assessments.
- **Sales representative:** supplies customer context and passes clarification questions to the customer.
- **Head of Delivery (sponsor):** relies on estimates that hold. Reviews the decision trace and estimate-vs-actual results when a delivery overruns.

## Why Build, Not Buy

Commercial presales and RFP tools (Loopio, Responsive, Arphie, Inventive, Vivun and others) automate questionnaire answers and proposal drafting. That part of the market is crowded. None of the tools found in our research assesses implementation feasibility, challenges integration risk, or produces a delivery estimate with explicit assumptions. That is where our losses happen. If we later want RFP drafting, we can integrate a commercial tool for it rather than build it ourselves.

## MVP Scope

Goal of the first release: a presales engineer can take a real opportunity from raw customer input to a structured, assumption-backed estimate inside the workbench.

**In:**
- Intake of emails, call notes and Teams transcripts by paste or upload, producing structured requirements.
- Gap detection against product documentation, integration specifications and checklists, producing customer clarification questions.
- Engineering, PM and security agent assessments of each integration, plus a Red Team challenge.
- A standard estimate template with an assumptions register. Each assumption is marked as a proposal condition or a priced contingency.
- Agent conflicts shown to the presales engineer with evidence; the engineer decides.
- A decision trace for every estimate.
- Actual effort recorded against the estimate when the project closes.

**Out (later):** CRM integration, multi-round agent negotiation, what-if scenarios and dynamic replanning, proposal document generation, the multi-role approval workflow, a commercial/pricing agent, learning from historical estimate-vs-actual data (no data exists yet).

`[ASSUMPTION]` The MVP output is the estimate, the assumptions register and the clarification questions. The presales engineer carries these into the proposal; the MVP does not generate the proposal document.

## Success Metrics

| Metric | Target | Notes |
|---|---|---|
| Estimate variance on delivered MVP projects | Within ±15% of actual `[ASSUMPTION]` | Today: 20–50% under (source unconfirmed). This is the Head of Delivery's headline measure. Results lag by one delivery cycle. |
| Adoption | ≥80% of new opportunities (>20/month) estimated in the workbench within 3 months `[ASSUMPTION]` | Leading indicator. Without adoption, no estimate-vs-actual data accumulates. |
| Unknowns surfaced before estimate | Clarification questions sent before the estimate on most opportunities | Tests the main idea: find the unknowns first. |
| Scope added mid-delivery from unsurfaced requirements | Falling trend | Requires delivery to tag the cause of each change request. |
| Time to estimate | No worse than today | Guards against the workbench adding overhead. |

## Risks and Unknowns

- **No baseline.** There are no past proposals or actuals, and the 20–50% figure may be anecdotal. Without a baseline, improvement cannot be proven. *Mitigation:* reconstruct 10 or more past deals from signed SOWs and delivery timesheets if they exist; otherwise accept the first quarter of data as the baseline.
- **No historical learning at launch.** Risk detection relies on documentation and expert checklists and is only as good as they are.
- **Knowledge quality.** Product and integration documentation may be incomplete or out of date. Writing checklists takes time from senior engineers.
- **Confident but wrong agents.** LLM assessments of feasibility can sound authoritative without evidence. Every finding must cite a source, and the presales engineer owns the final estimate.
- **Multi-agent cost and reliability.** Orchestrated agent systems can use around 15x the tokens of a single chat, and published research finds their gains are often small. The specialist-agent design should be benchmarked against a simpler single-agent baseline.
- **Adoption.** Engineers currently use their own methods. A workbench that slows them down will be bypassed.
- **Actuals capture depends on delivery discipline.** If delivery teams don't record actual effort and the cause of each overrun, the learning loop never starts.
- **Customer data confidentiality.** Customer requirements will be sent to LLM providers. This needs data-handling approval.

## Open Questions

1. Where does the 20–50% figure come from? Do signed SOWs and delivery timesheets exist for building a baseline?
2. Which product documentation and integration specifications exist, where are they kept, and how current are they?
3. Is the MVP output (estimate, assumptions, questions) enough, or does the Head of Delivery expect proposal documents too?
4. What is the typical cycle time from first contact to proposal today?
5. Does policy allow customer requirement data to be sent to OpenAI or Anthropic models?
