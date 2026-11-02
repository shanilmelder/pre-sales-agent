# Knowledge setup for the Larkspur scenario

Do this once, as a platform administrator, before creating the Opportunity. It shows the
Knowledge Base features (Stories 3.1-3.6) and lets the mandatory-gap check (Story 4.2) fire
for an insurance project.

## 1. Catalogue entries (Admin > Catalogue)

Integration Types to add:

| Name | Description |
|------|-------------|
| Policy administration integration | Lookup, cover check and excess against a policy system |
| Payments integration | Bank payment files and instant payments for claim settlement |
| Document and correspondence | Letter templates and multi-language member correspondence |

Work Packages to add:

| Name | Description |
|------|-------------|
| Data migration | Trial and final migration with reconciliation |
| Regulatory and outsourcing assurance | Regulator notification support, exit plan, audit rights |

The existing Integration Types **ERP integration** (Dynamics 365 Finance postings) and
**Identity and single sign-on** (Okta) also apply.

## 2. Knowledge Source (Knowledge > Register a Source)

Upload `insurance-claims-migration-playbook.md`:

- Title: Insurance claims migration and integration playbook
- Product: Claims platform
- Integration Types: Policy administration integration, Payments integration, ERP integration
- Version: 2

The existing **Microsoft Dynamics 365 integration guide** in the Knowledge Base also covers
the finance postings, so Research Agent citations come from two Sources.

## 3. Checklist (Knowledge > Checklists > New)

Title: **Claims payments readiness**, domain Engineering, scope tag Payments integration.
Items (mark the first three **mandatory**):

1. Payment rails agreed: file, instant, or both (mandatory)
2. Bank test environment requested, with a date (mandatory)
3. Payment approval rules and authority limits documented (mandatory)
4. Return and rejection file handling agreed
5. Payee validation (IBAN check) owner agreed
6. Finance posting cut-off time confirmed

Publish it. Items the Sources don't answer turn into deterministic Gaps.

## 4. Coverage and graph

Open **Knowledge > Coverage**: Payments integration is covered by one Source and one
Checklist; Document and correspondence has no Source yet, which is a coverage gap worth
pointing out in the demo.
