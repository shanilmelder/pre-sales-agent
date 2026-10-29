# Aldermoor Patient & Referral Portal - Statement of Requirements

Issued by Aldermoor Health Trust Digital Procurement, version 1.2, 21 October 2026. Requirements marked MUST are mandatory; SHOULD are scored.

## 1. Patient portal

| ID | Requirement | Priority |
|----|-------------|----------|
| PP-01 | Patients view upcoming and past outpatient appointments for all three hospitals | MUST |
| PP-02 | Patients confirm, cancel or request to rebook an appointment; changes reach CarePoint within 5 minutes | MUST |
| PP-03 | Patients read clinic letters in the portal; letters with a confidentiality code are never shown | MUST |
| PP-04 | Pre-appointment questionnaires, configurable per clinic by Trust staff without supplier help | MUST |
| PP-05 | Proxy access for carers and parents, with an audit of what the proxy viewed | SHOULD |
| PP-06 | Portal available in English plus the five most common languages in the catchment | SHOULD |

## 2. Referrals

| ID | Requirement | Priority |
|----|-------------|----------|
| RF-01 | GP practices send referrals electronically with attachments up to 20 MB | MUST |
| RF-02 | Consultant triage worklist: accept, reject or redirect with a reason | MUST |
| RF-03 | Referral to treatment clock starts on receipt of the referral | MUST |
| RF-04 | Referrer sees the referral status without phoning the hospital | SHOULD |

## 3. Integration

- CarePoint EPR 11.4: read Patient, Appointment, Schedule and DocumentReference over FHIR R4.
- Appointment write-back to CarePoint: FHIR if supported, otherwise HL7 v2 SIU through the Trust integration engine.
- Patient demographics and merges from the HL7 v2 ADT feed (A04, A08, A40).
- SMS and email reminders through the Trust's existing SMS gateway contract.

## 4. Non-functional

- Availability 99.5% from 07:00 to 22:00, seven days a week.
- 15,000 concurrent patient sessions at the Monday morning peak; page response under 2 seconds for 95% of requests.
- Accessibility: WCAG 2.2 AA, verified by an independent audit before go-live.
- Patient data hosted in the UK only. Audit trail of every record access kept for 8 years.

## 5. Delivery

- Clinical safety case and hazard log produced by the supplier's clinical safety officer.
- Data protection impact assessment completed with the Trust's DPO before go-live.
- Training for 14 booking clerks and about 120 clinicians; train-the-trainer is acceptable.
- 90 days of hypercare after each go-live.
