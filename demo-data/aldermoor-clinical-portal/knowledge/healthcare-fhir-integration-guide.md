# Healthcare EPR integration guide (HL7 FHIR R4 and HL7 v2)

Internal delivery knowledge, version 3, reviewed October 2026. Owner: Integration practice.

## When this applies

Any project that reads from or writes to a hospital electronic patient record (EPR):
patient portals, referral services, scheduling, clinical letters.

## Typical effort (hours)

| Item | Low | Typical | High |
|------|-----|---------|------|
| FHIR R4 read: Patient, Appointment, Schedule | 60 | 90 | 140 |
| FHIR DocumentReference (letters), with confidentiality filtering | 40 | 70 | 110 |
| Appointment write-back over FHIR | 80 | 120 | 200 |
| Appointment write-back over HL7 v2 SIU via an integration engine | 140 | 200 | 320 |
| HL7 v2 ADT consumer (A04, A08, A40 merges) | 50 | 80 | 120 |
| Clinic code mapping, per 100 clinic codes | 16 | 24 | 40 |

## Lessons learned

- EPR vendors rarely confirm write-back support before contract award. Carry it as a
  contingency sized at the difference between FHIR and HL7 v2 write-back (about 80 h).
- Patient merges (A40) are the most common cause of portal defects: test with real merge
  scenarios from the customer's integration engine.
- Clinic code lists are always dirtier than the customer thinks. Budget a walk-through
  per specialty.
- Confidential letters (safeguarding, sexual health, mental health) must be filtered at
  the API, never in the user interface.

## Mandatory checks before estimating

- EPR product and version, FHIR version and which resources are readable and writable.
- Who owns integration engine changes (customer or supplier).
- Test environment: dedicated or shared, refresh cycle, synthetic data.
- Clinical safety officer on both sides and the hazard log approach.
- Data residency and audit log retention.
