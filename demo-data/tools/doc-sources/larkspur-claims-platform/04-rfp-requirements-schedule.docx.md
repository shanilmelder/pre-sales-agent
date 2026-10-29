# Larkspur Mutual - Claims Platform RFP, Schedule 2: Requirements

Version 1.0, 12 October 2026. M = mandatory, D = desirable.

## A. Claims handling

| ID | Requirement | M/D |
|----|-------------|-----|
| CL-01 | First notification of loss by phone (handler), online (member) and broker | M |
| CL-02 | Automatic cover check and excess against the policy system at FNOL | M |
| CL-03 | Triage rules configurable by the business: fast-track, standard, complex, fraud referral | M |
| CL-04 | Reserving with authority limits per handler grade (EUR 5k / 25k / 100k / unlimited) | M |
| CL-05 | Settlement and payment, including partial and repeat payments | M |
| CL-06 | Motor recoveries from third-party insurers | D |
| CL-07 | Straight-through settlement for motor glass and travel cancellation under EUR 1,000 | D |

## B. Member and broker self-service

- Members submit and track claims online with photo and document upload, signed in with their existing member portal account.
- Brokers notify and track claims for their clients.
- Status updates by email and SMS at each claim stage.

## C. Integration

- Policy administration (mainframe) through REST services on the Larkspur API gateway.
- Microsoft Dynamics 365 Finance: daily general ledger postings for reserves and payments.
- Bank: SEPA credit transfer files (pain.001 out, pain.002 back).
- Fraud scoring service (vendor to be selected): score at FNOL and on every reserve change.
- Document system: 140 letter templates in English and Irish.

## D. Data migration

- About 9,000 open claims with full history, reserves and payments.
- About 1.4 million closed claims from the last seven years, read-only, searchable.
- Reconciliation report proving reserves and paid totals match ClaimsOne to the cent.

## E. Non-functional and compliance

- EU data residency (AWS Dublin). Encryption at rest and in transit.
- Full audit trail of every decision, kept for 10 years after claim closure.
- Explainable automated decisions for complaint handling.
- Staff single sign-on through Okta, with multi-factor authentication.
- Capacity for 3x normal volume in storm weeks without degradation.
