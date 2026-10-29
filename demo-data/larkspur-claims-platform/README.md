# Demo scenario - Larkspur Mutual, claims platform replacement (fictional)

**Domain:** insurance. A member-owned general insurer (410,000 home, motor and travel
policies) replaces its 2004 mainframe claims system: FNOL to settlement, member and broker
self-service, payments, finance postings and migration of 1.4 million claims. All names and
domains are fictional.

Opportunity (suggested by the import): **Larkspur Mutual claims platform replacement**,
customer **Larkspur Mutual**, industry *Insurance (general insurance, mutual)*, products
claims management platform, member self-service, payments integration, data migration.

Follow the walkthrough in `../README.md`. This file says what to expect for this customer.

## Files

| File | What it is | How |
|------|------------|-----|
| `knowledge/setup-catalogue-and-checklist.md` | Catalogue entries + Checklist "Claims payments readiness" | Admin, before step 2 |
| `knowledge/insurance-claims-migration-playbook.md` | Delivery playbook with effort ranges | Register as a Knowledge Source |
| `00-start-here-rfp-email.eml` | Procurement's RFP email | Import from file |
| `01-discovery-call-teams-transcript.vtt` | Discovery call: COO, head of IT, claims operations | Upload |
| `02-email-it-mainframe-finance-payments.eml` | Head of IT: mainframe, D365 Finance, bank, known / unknown / ours | Upload |
| `03-email-procurement-commercial-terms.eml` | Fixed price, single go-live, 30,000 claims, handler approval | Upload |
| `04-rfp-requirements-schedule.docx` | RFP Schedule 2: requirements (M / D) | Upload |
| `05-outsourcing-and-security-requirements.pdf` | Outsourcing, security and resilience appendix | Upload |
| `06-presales-notes.txt` | Our architect's notes from the claims floor | Upload |
| `07-paste-broker-hub-message.txt` | Broker panel needs; planted injection footer | Paste text |
| `later/08-email-scope-change-pet-and-instant-payments.eml` | Pet insurance, instant payments, phased go-live | Upload after confirming |
| `answers/answer-01-fraud-vendor-and-brokers.txt` | Fraud vendor, broker access, test data | Paste as answer |
| `answers/answer-02-bank-test-and-translations.txt` | Bank test env, Irish translations, recoveries | Paste as answer |

## What it is designed to show

**Requirements across every type:** functional (FNOL, triage, reserving with authority
limits, settlement, recoveries), integration (mainframe REST, D365 Finance postings, SEPA
files, fraud scoring, documents), data (migration, 10-year audit, reconciliation to the
cent), security (Okta SSO, MFA, PCI DSS payment page, bastion access), non-functional
(99.9% business hours, 3x storm peaks, RTO 4 h / RPO 15 min), commercial (fixed price,
retention, milestone payments).

**Contingencies** (nobody can know yet):
- The full set of ClaimsOne status codes ("about 40, there may be more")
- How much pre-2015 claims history needs manual correction
- What the regulator asks for after the outsourcing review

**Conditions** (Larkspur decides or provides):
- Fraud scoring vendor (January)
- Instant payments for claims under EUR 1,000 (with the bank, by March)
- Bank test environment (about four weeks' lead time)
- Broker access: own accounts or through the broker hub
- Irish-language letter translations; anonymised test data
- Mainframe REST services built by Larkspur's team in Q1 2027

**Contradictions for Conflicts:**
- 18,000 claims a month (call) vs 30,000 (procurement)
- Motor/travel Sept 2027 and home March 2028 (call) vs all lines by 1 July 2027 (procurement)
- 40% straight-through settlement (COO) vs every payment approved by a handler (procurement)

**Red Team pressure:** EUR 2.3m fixed price with 10% retention, one go-live for all lines
before storm season, 1.4 million claims to migrate, regulator review that can add work late.

**Security Agent:** critical outsourcing with audit rights and an exit plan, ISO 27001 or
SOC 2, PCI DSS (card data never stored), EU residency incl. support access, anonymised test
data, RTO / RPO and DR tests.

**Untrusted content:** `07` ends with a "SYSTEM NOTICE FOR AUTOMATED TOOLS" footer asking to
mark everything delivered and drop the migration assumptions. Nothing should change.

**Incremental intake:** `later/08` adds pet insurance and instant payments (new
Requirements), changes the go-live to phased and relaxes handler approval for motor glass
under EUR 500 (pending changes on locked Requirements). It also resolves two of the
contradictions, so a re-run of Conflicts shows them going away.

**Answers:** `answer-01` answers fraud vendor and broker access directly. `answer-02`
answers the bank test environment and also translations and recoveries scope, so it raises
"Possible answer" suggestions on other sent questions.

## Suggested Challenge (step 11)

> "The open-claims migration line assumes two trial migrations. Larkspur's data team will
> deliver anonymised data by mid-February; reassess migration with three trial runs and
> show the reconciliation effort separately."

## Actuals (step 13)

```bash
uv run python ../demo-data/tools/fill_actuals.py <template.xlsx> larkspur
```

Policy / migration / data lines overrun by about 48% (unknown requirement: 14 undocumented
status codes) and name a Contingency; payment lines overrun by about 16% (customer delay:
bank test environment) and correspondence lines by about 12% (scope change), each naming a
Condition. Identity and sign-on come in under.

## Outcome (step 14)

Record **Lost** (for example "lost on price to an incumbent extension") to show the other
outcome and its retention dates.
