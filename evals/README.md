# evals

The evaluation harness and reference set for the Agents (Story 7.6, AD-21). `make eval` runs
every reference Opportunity through the real job chain in an isolated evaluation database,
scores what the Agents produced against the annotations, compares it with the last accepted
result, and stores the result in the Agent Registry (`registry_eval_results`). Admins see it
on **Admin → Evals**.

## Running it

```sh
# once: an eval database next to the main one (never the main `psa` database)
docker compose exec postgres createdb -U psa psa_eval
docker compose exec postgres psql -U psa -c "GRANT CONNECT, TEMP ON DATABASE psa_eval TO psa_app"

# in .env (or the shell)
PSA_EVAL_DATABASE_URL=postgresql+psycopg://psa_app:<app password>@127.0.0.1:5432/psa_eval
PSA_EVAL_MIGRATIONS_DATABASE_URL=postgresql+psycopg://psa:<owner password>@127.0.0.1:5432/psa_eval

make eval                                     # every reference Opportunity, current configs
make eval ARGS="--only fresh-food-dc"         # one Opportunity (repeatable)
make eval ARGS="--config pm_agent=2"          # a config version from the main DB (repeatable)
make eval ARGS="--timeout 7200"               # default 3600 s for the whole run
```

What happens:

1. The harness refuses to run (exit 2) unless both eval URLs are set and name a database other
   than `PSA_DATABASE_URL`'s, and unless every `--config` version exists.
2. It reads each Agent's chosen config version from the main database (default: current).
3. It resets the eval database: `alembic downgrade base`, then `upgrade head`.
4. It copies each chosen version into the eval database as that Agent's newest version, so the
   job chain picks it up (an `eval_only` Agent runs; a `disabled` one stays disabled).
5. It creates one Opportunity per reference Opportunity, uploads its Sources (into a
   temporary file store, removed afterwards), and runs the
   worker loop until the chain is done: parse → extraction → Gap detection → Specialists →
   Estimate → Red Team, through the real ModelGateway at `background` priority. Assumption
   proposals are not run. There is no Critic Agent yet, so the report lists it as "not
   available".
6. It scores the results, writes `evals/out/<timestamp>/report.json` and
   `review-pending.yaml`, and stores the result in the main database with a
   `registry.eval.completed` trace event. That is the only write to the main database.

Exit codes: `0` passed, `1` failed (stored, not accepted), `2` refused (nothing ran),
`3` "Eval timed out — GPU busy" (nothing stored).

Cost uses `PSA_COST_PER_GPU_SECOND_MINOR`, `PSA_COST_PER_1K_TOKENS_MINOR` and
`PSA_COST_CURRENCY` (integer minor units). GPU seconds are the summed model-call wall time,
a proxy until Story 7.5.

## The gate

| Bar | Agent | Threshold |
| --- | --- | --- |
| Extraction recall (FR-5) | `intake_agent` | ≥ 90% |
| Citation validity (FR-5) | `intake_agent` | 100% |
| Gap recall (FR-11) | `clarification_agent` | ≥ 80% |
| Irrelevant Gaps (FR-11) | `clarification_agent` | ≤ 20% |
| Mandatory-item Gaps (FR-11) | `clarification_agent` | 100% |
| Evidence support (FR-25) | engineering, pm, security, red_team | ≥ 95% |

A result **passes** only when every bar passes, no bar is more than 5 points worse than the
last accepted result **of the same reference-set version**, and no stage failed. A passed
result is stored as **accepted** and becomes the comparison point for that version. Results
of another version (for example an `--only` subset) are never compared: like with like.
With no accepted result of the version, it is a first eval, so only the thresholds apply
and the deltas are empty. A subset run can be accepted for its own subset. A bar with nothing to measure reads **not measured**: a warning that
never fails the gate. The schema-valid rate (per Agent, from `platform_model_calls`) and
integration-risk recall (for Story 7.7) are reported without a bar.

## The reference set

`reference/<slug>/` holds one Opportunity: `sources/*.txt|.eml|.vtt` and `annotations.yaml`.
Two are anonymised copies of the `demo-data/` scenarios (`fresh-food-dc`,
`home-garden-fc-retrofit`); eight are fictional Opportunities in other domains. The
reference-set version is the first 12 hex characters of the sha256 of the folders of the
reference Opportunities that ran (paths and contents, LF line endings), so an `--only` run
has its own version.

**Anonymisation.** Sources use placeholders: `[CUSTOMER]`, `[SITE]`, `[PERSON_1]`, … and
only `.example` email domains. Customer originals never enter the repository.
`backend/tests/test_evals.py` checks this, and that no name from the original demo
scenarios is left.

### `annotations.yaml`

```yaml
slug: fresh-food-dc                 # the folder name
title: "[SITE] automation"          # the Opportunity created in the eval database
customer: "[CUSTOMER]"
industry: Food & grocery distribution
products: [Goods-to-person picking]
annotator: draft                    # `draft` until a domain expert has reviewed it
requirements:                       # what the Intake Agent should extract
  - id: R1
    text: Goods-to-person picking for the ambient area
    source: 01-discovery-call-teams-transcript.vtt
    quote: "a goods-to-person picking system for the ambient area"
gaps:                               # what Gap detection should raise
  - id: G1
    keywords: [SAP version, S/4HANA]
    mandatory: true                 # a mandatory checklist item (Checklists come in 4.1/4.2)
irrelevant_gaps:                    # Gaps that would be noise
  - label: Office and staff facilities
    keywords: [canteen, car park]
integration_risks:                  # reported for Story 7.7, no bar
  - id: I1
    keywords: [SAP, IDoc]
evidence:                           # judged Finding→Requirement pairs
  - requirement: R6
    finding_keywords: [SAP, confirmation]
    supported: true
```

Every annotation is still `annotator: draft`; the report says how many are drafts.

### Matching rules (deterministic)

- **Requirements:** an extracted Requirement matches an annotated one when one of its evidence
  passages overlaps a span of the annotated quote (any occurrence) in the same parsed Source.
  The quote is found ignoring case and treating any run of whitespace as one space.
  Extraction recall = matched annotated Requirements / annotated Requirements.
- **Citation validity** = valid citations / (valid + the extraction's `dropped_count`).
  Stored citations are literal by construction, so invalid ones only show up as drops.
- **Keywords** match whole words, ignoring case: `line` does not hit "timeline", and `IDoc`
  does not hit "IDocs" (list the plural too when it matters).
- **Gaps:** a detected Gap matches an annotated Gap when any of its keywords appears in the
  Gap's title or why-it-matters. Gap recall = matched annotated Gaps / annotated
  Gaps; mandatory-item recall uses only `mandatory: true` Gaps; irrelevant = detected Gaps
  hitting an `irrelevant_gaps` label / all detected Gaps.
- **Evidence support:** each Finding (Specialist or Red Team) → cited Requirement pair is
  *judged* when an `evidence` entry names the annotated Requirement that the cited one
  matches and one of its `finding_keywords` appears in the Finding's title or detail.
  Support = supported judged pairs / judged pairs. Unjudged pairs are **pending**: they go to
  `review-pending.yaml` and are never counted as passes. With no judged pair, the bar reads
  "not measured".
- **Integration risks:** an annotated risk is found when a keyword hits a Red Team
  `integration_harder` Finding or a Specialist `risk` Finding.
- Overall values are micro-averages across the set. A **failed stage** (a dead job or a
  failed run) scores that Opportunity's metrics from that stage on as 0 (an empty
  denominator counts as one; irrelevant Gaps as 100%), including the failed stage's Agents'
  Evidence support and integration risks; the report names the failure (once per stage)
  and the result does not pass.

To grow the judged Evidence, copy pairs from `review-pending.yaml` into the Opportunity's
`evidence:` with the expert's `supported` verdict.

## Semantic Conflict detection (`make eval-conflicts`)

Story 6.2 records a precision/recall baseline for `conflict_agent`, which compares the
specialists' free-text Findings and proposes Conflicts (`architecture`, `assumption`,
`evidence`, `scope`). It is separate from `make eval`: no eval database, nothing stored in the
Agent Registry, no gate.

```sh
make eval-conflicts                                    # every case, PSA_MODEL_PROFILE_CHAT
make eval-conflicts ARGS="--only scope-label-printing" # one case (repeatable)
make eval-conflicts ARGS="--profile demo-chat"         # another model profile
```

Each case in `conflicts/<name>.yaml` holds synthetic Findings per specialist and the Conflicts
a reviewer expects:

```yaml
findings:
  engineering_agent:            # engineering_agent, pm_agent, security_agent
    - key: eng-sso              # unique in the case; `expected` cites it
      kind: constraint          # risk | constraint | dependency | opportunity (default risk)
      severity: high            # low | medium | high | critical (default medium)
      title: Single sign-on against the on-premises Active Directory
      detail: The terminals authenticate directly against the on-prem AD.
      requirements: [4]         # cited Requirement numbers (R4), optional
  security_agent:
    - key: sec-idp
      ...
expected:                       # [] for a decoy with no Conflict
  - type: architecture
    findings: [eng-sso, sec-idp]
```

The runner sends each case's Findings to the agent (prompt 1) on the live ModelGateway (no
call rows are written), validates the reply with the same pure validation the job uses, and
matches a predicted Conflict to an unmatched expected one when the type is equal and they
share at least two Findings. It prints precision and recall per type and overall, and writes
`out/conflicts-<timestamp>/report.json` (per-type and overall counts, each case's expected and
predicted Conflicts by Finding key, and any case whose model call failed, counted as predicting
nothing). Exit `0` once the report is written, `2` for an invalid or unknown case.

There are six cases: one per type and two decoys (an aligned design, unrelated topics).
