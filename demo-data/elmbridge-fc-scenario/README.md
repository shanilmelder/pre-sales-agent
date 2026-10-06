# Demo scenario — Harbourline Home & Garden, Elmbridge FC (fictional)

A complete second demo scenario built to show **both kinds of Assumption** side by side: several
**Contingencies** (uncertainty we carry, priced in hours) and many **Conditions** (things the
customer must provide or decide). **All names, companies and email domains are fictional**
(`.example` domains), so it is safe to send to the cloud model.

Opportunity to create: **Elmbridge FC automation**, customer **Harbourline Home & Garden**,
industry *E-commerce fulfilment (home & garden)*, products e.g. AS/RS, goods-to-person picking,
automated packing, sortation.

## Files

| File | What it is | Kind |
|------|------------|------|
| `01-kickoff-call-teams-transcript.vtt` | Teams kick-off call: operations, IT, facilities | Transcript |
| `02-email-it-systems-and-integration.eml` | IT lead: D365, legacy WMS, sign-on, network | Email |
| `03-email-facilities-building-and-site.eml` | Facilities: floor slab, sprinklers, power, mezzanine | Email |
| `04-email-operations-data-and-volumes.eml` | Operations: volumes, product data, cartons, returns, testing | Email |
| `05-email-procurement-commercial-terms.eml` | Procurement: timeline, fixed price, named allowances, carriers | Email |
| `06-site-visit-notes.txt` | Our solutions engineer's site-visit notes | Note |

Upload all six before opening the Requirements tab, so extraction sees everything.

## What it is designed to show

Every source says plainly which side owns each open point: either "**nobody can know this
until the work starts, price an allowance**" or "**that's our decision, we'll come back to
you**". That wording is what steers each Gap to a Contingency or a Condition.

### Contingencies (the customer cannot answer; the Gap is marked "Unknown to the customer:")

| Gap | Why nobody can know |
|-----|---------------------|
| Unknown number of legacy WMS interfaces | 2009 in-house WMS, no documentation; interfaces are only found by tracing them during migration |
| Unknown floor slab thickness / reinforcement | No drawings; core samples only after the tenant leaves on 15 Jan 2027 |
| Unknown fire-authority sprinkler requirements | The authority only decides after reviewing the final design |
| Unknown marketplace volume increase | New channel, no history, "could be 10%, could be double" |
| Unknown product data quality | Dimensions/weights unreliable; only known once every SKU is measured |

The first three come out as Contingencies on every run; the last two most runs (otherwise they
show as Conditions or are folded into another Gap).

### Conditions (the customer owns the decision or the information)

- Choice of D365 integration method (data entities vs file-based batch)
- Dedicated or shared D365 sandbox
- Single sign-on provider (Okta or Microsoft Entra ID)
- Dedicated or shared VLAN for the automation
- Who supplies three-phase power to the drop positions
- Final carton range for the auto-bagger and carton erector
- Keep or remove the mezzanine over docks 1-3
- Returns processing in this phase or the next
- Who prepares acceptance test orders, and how many super-users
- Building handover / site-access date (negotiated with the landlord)
- Which two parcel carriers win the tender (sometimes a Contingency instead)

## What to expect

Checked with dry runs of the whole chain (extraction → Gaps → Assumptions) on
`gpt-oss:120b-cloud`, three runs:

| Run | Contingencies | Conditions |
|-----|---------------|------------|
| 1 | 4 | 12 |
| 2 | 5 | 13 |
| 3 | 4 | 12 |

The model is not deterministic, so titles, counts and hours vary from run to run; the split
between the two kinds holds.

## Demo tips

- In the **Gaps** tab, the Contingency Gaps are the ones whose "why it matters" starts with
  **"Unknown to the customer:"**: a good moment to explain the difference.
- In the **Estimate**, accept a couple of Contingencies first so the hours show up against
  their lines, then **Accept all** for the Conditions.
- Good talking point: procurement (`05`) explicitly asks for each allowance to be shown
  separately with its hours, rather than hidden in rates.
