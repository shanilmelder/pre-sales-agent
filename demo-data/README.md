# Demo input — Meridian Fresh Foods, Riverside DC (fictional)

Sample customer input for the stakeholder demo. **All names, companies and email domains are fictional** (`.example` domains), so it is safe to send to the cloud model.

| File | What it is | Upload as |
|------|------------|-----------|
| `01-discovery-call-teams-transcript.vtt` | Teams discovery call (ops, IT, finance) | Upload (`.vtt`) |
| `02-email-it-integration-follow-up.eml` | IT manager's follow-up: SAP, master data, security | Upload (`.eml`) |
| `03-email-procurement-rfp-terms.eml` | Procurement: timeline, phasing, commercial terms | Upload (`.eml`) |
| `04-email-legacy-conveyor-contingency.eml` | Ops: unknown 2011 conveyor controls (designed to produce a **Contingency**) | Upload (`.eml`) |
| `05-email-customer-dependencies-condition.eml` | IT: things the customer must provide or decide (designed to produce **Conditions**) | Upload (`.eml`) |

Opportunity to create: **Riverside DC automation**, customer **Meridian Fresh Foods**, industry *Food & grocery distribution*, products e.g. goods-to-person picking, WMS integration.

## What it is designed to show

- **Requirements across every type:** functional (goods-to-person picking, batching and waves, replenishment, dashboards), integration (SAP order release and confirmations, three carriers), data (master data, two-year audit log), security (SSO, vendor access, ISO 27001, pen test, network separation), non-functional (99.5% availability 05:00–23:00, 6 days; peak volumes), commercial (budget, milestones, warranty, support).
- **Gaps the agents should find:**
  - SAP version at go-live (ECC or S/4HANA) and integration method (IDoc vs API) undecided
  - Role of the existing WMS undecided (replace or sit underneath)
  - Identity provider for SSO not named
  - 30% of SKUs missing dimensions and weights — who measures them?
  - SAP test system only from January and shared
  - Chilled-zone temperature range and alarm handling details; data must stay in-country (hosting)
- **Condition Gaps** (from `05`): the customer must provide or decide them, so each should become a Condition ("The estimate assumes the customer provides…"), no hours:
  - Carrier label and manifest specifications from the three carriers
  - Keep or replace the existing label printers
  - As-built drawings and floor flatness survey from the landlord
  - Network for the automation (VLANs, IP ranges, firewall rules, chilled-zone Wi-Fi)
  - Vendor accounts on the customer's remote access gateway (about three weeks to approve)
  - Sign-off of the chilled zone layout (dock doors, air curtains), planned for November
  - Test orders and expected results for acceptance testing
- **A Contingency Gap** (from `04`): the legacy conveyor's controls are unknown until our engineers open the cabinet, so we carry it as hours.
- **A contradiction:** peak volume is "3,500, maybe 5,000 in December" in the call, then "4,200 order lines per hour plus 20% growth" in the procurement email.
- **Commercial pressure for the Red Team:** fixed price, 2.4 million budget, go-live before the November peak with a March handover, phased chilled go-live, 4-hour 24/7 support in peak season.

## Tips

- Upload all the files before opening the Requirements tab, so extraction sees everything.
- Approve the Clarification Questions you want to show **before** Accept all on the Assumptions.
- Good line to edit live in the Estimate: the SAP integration or master-data line (e.g. "Reuse the existing IDoc mapping").

## Second scenario: Conditions and Contingencies

`elmbridge-fc-scenario/` is a complete second scenario (Harbourline Home & Garden, Elmbridge FC) with a call transcript, four emails and site-visit notes. It is built to show **several Contingencies and many Conditions** in the same Estimate. See its own `README.md`.
