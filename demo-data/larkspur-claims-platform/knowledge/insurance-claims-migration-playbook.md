# Insurance claims platform: migration and integration playbook

Internal delivery knowledge, version 2, reviewed September 2026. Owner: Financial services practice.

## When this applies

Replacing a claims or policy system for a general insurer: claims handling, payments,
finance postings, document generation and migration of claims history.

## Typical effort (hours)

| Item | Low | Typical | High |
|------|-----|---------|------|
| Policy system lookup and cover check (REST over mainframe) | 60 | 100 | 160 |
| General ledger postings to an ERP (daily journals) | 70 | 110 | 170 |
| SEPA credit transfer file out and return file in | 60 | 90 | 140 |
| SEPA instant payments (per bank API) | 80 | 120 | 180 |
| Fraud scoring service integration | 40 | 70 | 110 |
| Letter templates, per 10 templates (one language) | 20 | 30 | 45 |
| Open claims migration with reconciliation | 300 | 450 | 700 |
| Closed claims history, read-only archive | 120 | 200 | 320 |
| Mapping legacy claim status codes, per 10 codes | 12 | 20 | 35 |

## Lessons learned

- Legacy claim status codes are always more than the customer thinks; carry the
  unknown codes as a contingency, sized per 10 codes.
- Reserve reconciliation "to the cent" needs at least two trial migrations.
- Regulator outsourcing reviews often add exit-plan and audit-right work late. Carry a
  contingency of about 60 hours.
- Straight-through settlement and "every payment approved by a handler" are often both
  in the same RFP: resolve which wins before estimating.

## Mandatory checks before estimating

- Policy system interface: who builds it and when it is available.
- Payment rails: file, instant, or both; bank test environment lead time.
- Finance posting cut-off and journal format.
- Data residency and the regulator's outsourcing process.
- Number of letter templates and languages.
