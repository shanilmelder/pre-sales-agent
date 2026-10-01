# PRD Quality Review — Agentic AI Presales Platform (pre-sales-agent)

Reviewed: prd.md and addendum.md (2026-10-01 draft). Context: internal tool, fast-path draft; `[ASSUMPTION]` tags are intentional and pending confirmation, and are not counted against the PRD as defects.

## Overall verdict
The PRD has a clear thesis ("the deals we win are deals we can deliver"), a specific Vision, a strong Glossary and honest Non-Goals and counter-metrics. Gap detection is placed at the centre and the Release plan follows from it. The risk sits in the R1 seams. R1 has no path to an approved Baseline, Challenge (R1) depends on targeted reassessment that is scheduled for R3, and the core-value FRs (Gap detection, Specialist assessments, Red Team) have no quality bar an engineer could test. Fix those and the PRD is ready to feed architecture and epics.

## Decision-readiness — adequate

Major decisions are stated as decisions, not as "considerations". Examples: Negotiation is deferred to R3 with a human-resolution fallback (§4.8, UJ-3). The LLM never calculates prices (FR-24). Mandatory constraints are checked deterministically (FR-30). No Agent has send or approve permission (FR-57). Calibration "never appl[ies] silently" (FR-51). The addendum's "Changes from the original spec, and why" records what was given up and why, which is useful. The counter-metrics (§7) name real trade-offs, such as "Hitting SM-1 by padding every Estimate isn't success."

What holds the PRD back is that real tensions go unflagged. There is exactly one `[NOTE FOR PM]` (§6, R4 timing), and it marks a safe checkpoint rather than a contested choice. The tensions a sceptical sponsor would raise are left implicit. FR-14's hard block on submission sits against SM-C3 ("no worse than today"). The multi-agent design is justified only by a future comparison in FR-60, which has no decision rule attached. R1 has no approval or segregation-of-duties model.

### Findings
- **[medium]** Multi-agent bet has no decision rule (FR-60, §12 "Multi-agent cost and reliability") — FR-60 compares against "a single-agent baseline, to test whether the multi-agent design earns its cost", but the PRD never says what happens if the single-agent baseline matches or beats it. The multi-agent architecture is the largest cost driver in R1 (4.5–4.8). *Fix:* add a `[NOTE FOR PM]` with the decision criterion, e.g. "If single-agent Gap recall is within X% at lower cost, R1 collapses Specialist and Critic Agents into ...".
- **[medium]** Hard submission block vs speed counter-metric not acknowledged (FR-14, FR-29, SM-C3) — FR-14 "blocks Estimate submission while any Gap or Unknown is unresolved". On a tight proposal date, this is exactly the friction that leads engineers to bypass the workbench (§12 risk). The PRD lists both but never treats them as a trade-off. *Fix:* add a `[NOTE FOR PM]` stating the accepted cost, or define a fast path (e.g. bulk-convert remaining Unknowns to Contingencies with one recorded reason).

## Substance over theater — strong

The Vision could not be dropped into another PRD unchanged. It names the 20–50% underestimate, its causes, and the Condition/Contingency mechanism. The JTBD roles (§2.1) each map to features, and the UJs use three protagonists, each carrying context inline. The NFRs are mostly bounded (P95 latencies, 50 concurrent runs, WCAG 2.1 AA, Chrome/Edge only). Non-Goals do real work. No innovation theater.

### Findings
- **[low]** Sales rep JTBD has no capability behind it (§2.1, FR-58) — "Tell me ... how the proposal is progressing" is not served by any FR. The sales rep appears only as a role in FR-58 and as the recipient of exported questions (FR-12). *Fix:* add a read-only status view for the sales rep to FR-2, or trim the JTBD to "tell me what to ask the customer".
- **[low]** NFR-4 and the §9 Privacy line read as boilerplate — "encrypted in transit and at rest", "minimised in prompts and logs" give no product-specific bound (e.g. which personal-data fields are redacted before prompting). *Fix:* name the PII classes to be redacted, or point to the Q5 outcome.

## Strategic coherence — strong

The thesis is explicit (§1) and the architecture of the PRD follows it. Gap detection is "the core of the product" (§4.4), Unknowns cannot vanish (FR-14), Assumptions are carried into the proposal (FR-34, FR-47), and Actuals close the loop (4.14). SM-1 validates the thesis directly, and four counter-metrics are paired with it. The R4 dependency on data rather than code is stated honestly (§6).

### Findings
- **[medium]** No leading indicator of accuracy within the R1 pilot window (§7, §13) — SM-1 and SM-4 need delivered projects (months, and §6 says R4 comes 9–18 months later). SM-2, SM-3 and SM-6 measure activity. A 4–6 week pilot therefore cannot show that the thesis is working. *Fix:* add a leading SM, e.g. "share of Gaps raised by the platform that the reviewer or presales lead rates as material and previously unsurfaced", or Gap recall against reconstructed past deals (§12 baseline mitigation).
- **[medium]** R1 is close to the whole platform (§6 table) — R1 includes 14 of the 17 feature areas, among them Research Agent, Critic and Red Team, Conflict detection, Agent Registry, eval harness and Actuals reporting. "Estimation core" is the stated MVP kind, but nothing within R1 is marked as cuttable. *Fix:* mark the R1 must-haves for the thesis (4.2, 4.3, 4.4, 4.9, 4.11, FR-49) versus the R1 nice-to-haves (FR-23, FR-28, FR-30, FR-50), or add a `[NOTE FOR PM]` on R1 size.
- **[low]** SM-C1 and SM-4 have no thresholds — "must not fall materially" and "falling quarter on quarter". *Fix:* set a number, or tag `[ASSUMPTION]` pending Q1/Q6.

## Done-ness clarity — thin

The plumbing FRs are testable: FR-3 (failed task never appears successful), FR-16 (idempotent start), FR-18 (limits, partial results preserved), FR-25 (rejection rules), FR-39 (no self-approval), FR-57 (no send/approve permission). The FRs that carry the product's value are not. An engineer could ship FR-11 or FR-20–FR-23 and FR-28 as written with no way to know whether they are done.

### Findings
- **[high]** Core intelligence FRs have no quality bar (FR-5, FR-11, FR-20–FR-23, FR-27, FR-28) — FR-11 "raises a Gap for each piece of missing information needed to estimate" is unbounded. FR-20 "assesses technical feasibility ..." and FR-28 "argues that integrations are harder" carry no consequence bullets at all. FR-60 provides the harness, but no pass threshold is set. *Fix:* define acceptance against the FR-60 reference set, e.g. "Gap recall ≥ X% of expert-identified Gaps on reference Opportunities; Requirement extraction precision/recall ≥ Y%; every Specialist Assessment yields per-integration effort lines (FR-26)". Tag the numbers `[ASSUMPTION]` if needed.
- **[medium]** Undefined triggers and thresholds — FR-43 "change materially" defines nothing. FR-30 has no rule for when two positions count as a Conflict (e.g. effort delta > X%). FR-29 "Critical ... Findings" has no severity scale. FR-11 "ranked by estimated impact" has no method. *Fix:* give each one a rule or a configurable parameter with a default.
- **[medium]** Adjective-only consequences — FR-2 "at a glance", FR-12 "plain language", FR-61 "detected where possible", FR-37 "in one view". *Fix:* replace them with checkable conditions. For FR-61, reference the addendum's §28 prompt-injection test as the acceptance test.
- **[low]** FR-10 and FR-23 lack consequences — no definition of "lacks documentation", and no statement of who maintains the Research allow-list. *Fix:* add one bullet each.

## Scope honesty — adequate

Non-Goals (§5) are explicit and cover the omissions most likely to be assumed silently (customer portal, autonomous sending, pricing engine, RFP Q&A). Inline `[ASSUMPTION]` tags round-trip cleanly to §16. Open-items density is about 22 assumptions, 8 Open Questions and 1 note. That is fine for a fast-path draft, but Q1 (baseline) and Q5 (LLM data approval) block R1 and should be marked as such.

The weakness is release scoping that contradicts itself at FR level (next dimension's findings overlap). Several deferrals are implicit rather than called out.

### Findings
- **[high]** R1 has no way to set a Baseline (FR-39 [R2], Glossary "Baseline", FR-49, SM-1) — the Baseline is "the approved Estimate Version", but the only approval mechanism that sets one is FR-39, which is R2. Yet R1 records Actuals "per Estimate line" (FR-49), and SM-1 measures "Baseline and Actuals". *Fix:* add an R1 FR, e.g. "the Opportunity owner, after all Review Requests are approved, marks an Estimate Version as Baseline; recorded in the Decision Trace", and state that policy-driven approval replaces it in R2.
- **[high]** Challenge in R1 depends on R3 targeted reassessment (FR-38 [R1] vs FR-44 [R3], FR-7, UJ-2) — FR-38 says "the platform reassesses only the affected Assessments, shows the delta". That capability is FR-43/FR-44 in R3, and FR-7 says "in R1 the engineer chooses what to rerun". *Fix:* restate FR-38 for R1 (engineer selects the affected Assessments, the platform reruns them and shows the delta) and note the automatic version in R3. Align UJ-2.
- **[medium]** FR-29 override "where policy permits" with no R1 policy — policies arrive in R2 (FR-39). *Fix:* state the R1 default (e.g. only the Opportunity owner plus one named reviewer can override critical Findings).
- **[low]** Open Questions not tagged by blocking Release (§15) — *Fix:* mark Q1, Q2, Q5, Q7 as R1 blockers and Q3, Q4 as R2.

## Downstream usability — strong

This PRD feeds architecture and epics (addendum maps spec sections onto FRs), so this dimension matters. The Glossary is thorough, and capitalised terms are used consistently across FRs, UJs and SMs. FR-1–FR-61, UJ-1–UJ-5, SM-1–SM-6, SM-C1–SM-C4 and NFR-1–NFR-8 are contiguous and unique. Every UJ has a named protagonist. Features state which UJs they realise.

### Findings
- **[medium]** UJ-5 contradicts FR-51 — UJ-5 says "From Release 4 the platform raises its estimate for this integration type automatically", but FR-51 says Calibration "suggests adjustments" and that suggestions "never apply silently" and "can be overridden". Story writers will pull from both. *Fix:* reword UJ-5 to "suggests a higher estimate ... which Ravi accepts or overrides".
- **[low]** Glossary gaps — the Research Agent and Critic/Red Team Agents sit outside the "Specialist Agent" definition (engineering, PM, security, commercial), yet Research is specified under §4.6 Specialist Assessment. "Delivery manager" (FR-49, FR-58) is not in §2.1 or the Glossary. The Opportunity status values (§4.1) are not defined. *Fix:* add the Research Agent to the Specialist Agent definition or move FR-23, add the delivery manager role, and define the status lifecycle.

## Shape fit — strong

This is an internal tool, but it involves multiple roles with handoffs (presales engineer → reviewers → commercial → Head of Delivery → delivery manager). Five UJs with named protagonists are justified rather than overhead. The capability-spec structure with Release tags fits a chain-top PRD. Technology choices are correctly kept in the addendum. The PRD is neither over- nor under-formalised.

No findings.

## Mechanical notes
- **Broken cross-reference:** §0 says inferred content is "collected in §12". The Assumptions Index is §16, and §12 is Risks.
- **Assumptions Index roundtrip:** clean. All 22 inline tags appear in §16 and every §16 entry appears inline. The §4.3 and FR-8 entries are merged into one index line, which is acceptable.
- **Term collision:** "Baseline" is a Glossary term (approved Estimate Version), but lowercase "baseline" is also used for the historical accuracy baseline (§12 row 1, Q1, Q6) and for the "single-agent baseline" (FR-60). *Fix:* use "historical baseline" and "single-agent benchmark".
- **External references:** FR-60 "see brief, Risks" and §0 link to the brief and the spec. Fine for now, but downstream extraction will need those files present.
- **Release tags:** §0 claims "every feature and FR is tagged". FRs in single-Release features inherit the feature tag, which is acceptable. FR-36 carries a redundant [R1].
- **Required sections:** all are present for an internal chain-top PRD (Vision, users, Glossary, FRs, Non-Goals, Releases, SMs with counter-metrics, NFRs, governance, risks, rollout, stakeholders, open questions, assumptions).
