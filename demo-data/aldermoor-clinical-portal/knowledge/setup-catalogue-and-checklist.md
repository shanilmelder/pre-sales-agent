# Knowledge setup for the Aldermoor scenario

Do this once, as a platform administrator, before creating the Opportunity. It shows the
Knowledge Base features (Stories 3.1-3.6) and lets the mandatory-gap check (Story 4.2) fire
for a healthcare project.

## 1. Catalogue entries (Admin > Catalogue)

Integration Types to add:

| Name | Description |
|------|-------------|
| EPR integration (HL7 FHIR) | Read/write integration with a hospital electronic patient record over FHIR R4 or HL7 v2 |
| Patient notifications | SMS and email reminders through a customer-contracted gateway |

Work Packages to add:

| Name | Description |
|------|-------------|
| Clinical safety assurance | Clinical safety case, hazard log, clinical safety officer reviews |
| Data protection and assurance | DPIA, penetration test, remediation |

The existing Integration Types **Identity and single sign-on** and **Network and
infrastructure** also apply.

## 2. Knowledge Source (Knowledge > Register a Source)

Upload `healthcare-fhir-integration-guide.md`:

- Title: Healthcare EPR integration guide
- Product: Patient portal
- Integration Types: EPR integration (HL7 FHIR), Patient notifications
- Version: 3

Wait for it to reach **Ready** (chunked and embedded), then search it for "write-back" to
show a citable passage.

## 3. Checklist (Knowledge > Checklists > New)

Title: **Healthcare EPR integration readiness**, domain Engineering, scope tag
EPR integration (HL7 FHIR). Items (mark the first four **mandatory**):

1. EPR product, version and FHIR version are known (mandatory)
2. Readable and writable FHIR resources are confirmed by the EPR vendor (mandatory)
3. Owner of integration engine changes is agreed (mandatory)
4. Clinical safety officer named on the customer side (mandatory)
5. Test environment is dedicated, with synthetic patients
6. Confidential letter categories and their codes are listed
7. Audit log retention period is agreed

Publish it. When the Opportunity's Integration Types include EPR integration, items the
Sources don't answer turn into deterministic Gaps.

## 4. Coverage and graph

After the Opportunity has Requirements, open **Knowledge > Coverage** to see EPR
integration covered by one Source and one Checklist, and **Knowledge > Graph** to see the
new entries linked.
