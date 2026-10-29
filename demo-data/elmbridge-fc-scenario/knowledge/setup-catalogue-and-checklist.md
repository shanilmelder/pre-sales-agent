# Knowledge setup for the Elmbridge scenario

The warehouse catalogue (ERP, WMS, Carrier, Identity and single sign-on, Network and
infrastructure; Mechanical installation, Software and integration, Testing and
commissioning, Project management, Training and hypercare) and six warehouse Knowledge
Sources are already in the Knowledge Base. This adds one Source and one Checklist so the
Knowledge features have something new to show for this scenario.

## 1. Knowledge Source (Knowledge > Register a Source)

Upload `returns-processing-cell-guide.md`:

- Title: Returns processing cell guide
- Product: Goods-to-person picking
- Integration Types: WMS integration, ERP integration
- Version: 1

## 2. Checklist (Knowledge > Checklists > New)

Title: **Building and site readiness**, domain Delivery, scope tag Mechanical installation.
Items (mark the first four **mandatory**):

1. Floor slab thickness and flatness survey available (mandatory)
2. Fire authority's sprinkler requirements known (mandatory)
3. Site access and building handover date agreed (mandatory)
4. Power supply to drop positions agreed, with owner (mandatory)
5. Mezzanine and structural obstructions listed
6. Hot works and work-at-height permit process agreed

Publish it. Items 1 and 2 can't be answered before the work starts, so they show up as
Gaps that become Contingencies; items 3 and 4 become Conditions.

## 3. Coverage

Open **Knowledge > Coverage**: WMS integration now has two Sources; Identity and single
sign-on still has none, a coverage gap worth pointing out.
