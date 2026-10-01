# Reconciliation: PRD vs Product Brief

**Input:** `_bmad-output/planning-artifacts/briefs/brief-pre-sales-agent-2026-10-01/brief.md` + `addendum.md`
**Checked against:** `prd.md` + `addendum.md` (2026-10-01)
**Excluded:** the user's override of the brief's MVP scope (full product, phased R1–R4). Items the brief lists as "Out (later)" are not flagged for appearing in the PRD.

Overall the PRD carries the brief faithfully: the problem, positioning, MVP capabilities (now R1), metrics, risks and open questions are all present. The gaps are mostly places where a brief statement was softened, or where the PRD names a metric or outcome without the FR that makes it possible.

## High

| # | Brief source | What is missing or contradicted in the PRD | Suggested home |
|---|---|---|---|
| B1 | Brief addendum, landscape digest, "Intralogistics" bullet | **Dropped entirely.** The research concluded that vendor design and simulation tools (for example a storage-grid designer) are the credible source of feasibility data, and that the platform should call them rather than have the LLM estimate. The PRD has no FR for deterministic feasibility or design tools, no Engineering Agent rule to prefer them, and no dependency in §11. Only pricing gets the "LLM never calculates" rule (FR-24). | FR-20 (tool-backed feasibility where a tool exists); §11 dependency; §9 Safety and correctness |
| B2 | Brief §Success Metrics "Unknowns surfaced before estimate" (clarification questions *sent* before the estimate) | **SM-3 cannot be measured.** FR-12 only exports questions, and nothing records that or when they were sent to the customer, or when answers arrived. Questions need a status lifecycle (draft, approved, sent with date, answered, unanswered) to support SM-3 and the brief's "chasing the customer" cycle-time problem. | FR-12 / FR-13 |
| B3 | Brief §The Problem "nobody can reconstruct which assumption failed **or who accepted the risk**"; Head of Delivery role | FR-34 classifies and links Assumptions but does not require a **named person to accept each Assumption** (with timestamp). UJ-5 and SM-5 depend on "who accepted it", but FR-41's generic actor/timestamp does not capture explicit acceptance of an Assumption. | FR-34 (accepted-by per Assumption); FR-41 |
| B4 | Brief §Risks "Confident but wrong agents": "**Every finding must cite a source**" | Weakened. FR-25 and §9 reject only **material** Findings without Evidence, and "material" is undefined. Either restore "every Finding" or define materiality and how a non-material unsourced Finding is labelled to the user. | FR-25; §9 |

## Medium

| # | Brief source | What is missing or contradicted | Suggested home |
|---|---|---|---|
| B5 | Brief §Who It Serves, Sales rep "**supplies customer context and passes clarification questions** to the customer"; PRD JTBD "how the proposal is progressing" | The sales rep is a role in FR-58 but no FR gives them anything to do. They cannot add Opportunity Sources or context, view approved questions, record answers (FR-13 names only the presales engineer), or see Opportunity progress. | FR-4, FR-12, FR-13, FR-2 (extend actors to sales rep) |
| B6 | Brief §The Problem "nobody can tell **which kinds of integration** we consistently underestimate"; metric notes | FR-26, FR-50 and FR-51 all slice by "integration type" and "work package", but no FR defines a **controlled taxonomy** of integration types and work packages that Estimates, Actuals and Knowledge Sources share. Without it, variance cannot be grouped and Calibration has nothing to aggregate. | FR-33 (template defines taxonomy); FR-8 tagging; FR-56/admin config |
| B7 | Brief §Success Metrics "Scope added mid-delivery from unsurfaced requirements … **Requires delivery to tag the cause of each change request**" | SM-4 was rebased onto close-out variance causes (FR-49). The brief's leading indicator, **change requests tagged with cause during delivery**, was dropped. FR-49 makes milestone entry optional and has no change-request capture, so the signal arrives months later. | FR-49 (record change requests with cause during delivery) or note the deliberate change in §7 |
| B8 | Brief addendum "Evidence for negotiation and debate loops is thin"; brief §Solution "disagreement between functions does not cause underestimation" | The PRD keeps Negotiation in R3 (accepted deviation), but does not make it **conditional on evidence**, for example FR-60 showing that Negotiation beats human resolution or a single-agent baseline on reference Opportunities before it is enabled. SM-C2 limits its cost but not whether it should exist. | FR-32 (enablement criterion); FR-60 (add Negotiation-vs-no-Negotiation comparison) |

## Low

| # | Brief source | Note | Suggested home |
|---|---|---|---|
| B9 | Brief §Success Metrics, accuracy note "**Results lag by one delivery cycle**" | The PRD's R4 note covers Calibration lag but not that SM-1 itself cannot be read until R1-estimated projects deliver. The sponsor needs a leading-indicator view (SM-2, SM-3, SM-5) in the meantime. | §7 note under SM-1 |
| B10 | Brief §MVP "Each assumption is marked as a proposal condition or a **priced** contingency" | In R1 there is no Commercial Agent or pricing service. FR-34 allows "cost **or** effort", so R1 Contingencies may carry effort only. Confirm this is acceptable for R1 exports (FR-36), or require a cost conversion using configured rates. | FR-34 / FR-36 |
| B11 | Brief §The Problem "Long proposal cycles caused by rework and chasing the customer" | Only SM-C3 (no worse than today) touches this. No metric or report tracks clarification turnaround. That is optional, but it would show the value of B2's lifecycle. | §7 (optional secondary metric) |
