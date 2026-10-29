# Demo data

Three complete, fictional demo scenarios. **All people, companies and email domains are
fictional** (`.example` domains), so the files are safe to send to the cloud model.

| Folder | Customer | Domain | What it's built around |
|--------|----------|--------|------------------------|
| `aldermoor-clinical-portal/` | Aldermoor Health Trust | Healthcare (acute hospital trust) | Patient portal and e-referrals on a hospital EPR (HL7 FHIR / HL7 v2), clinical safety, UK data residency |
| `larkspur-claims-platform/` | Larkspur Mutual | Insurance (general insurer) | Claims platform replacing a mainframe system: payments, finance postings, regulator outsourcing, 1.4 million claims to migrate |
| `elmbridge-fc-scenario/` | Harbourline Home & Garden | Warehouse automation (e-commerce) | AS/RS, picking, packing and sortation for a new fulfilment centre; many Contingencies and Conditions |

Each folder covers **every feature** in the app, in the same order. Its own `README.md`
says what to expect at each step for that customer.

## Folder layout (the same in each scenario)

| Path | Used for | Feature |
|------|----------|---------|
| `knowledge/setup-catalogue-and-checklist.md` | Catalogue entries, a Checklist to author | Catalogue, Checklists, mandatory Gaps (3.1, 3.4, 4.1, 4.2) |
| `knowledge/*.md` (the other file) | Register as a Knowledge Source | Knowledge Sources, search, coverage, graph (3.2, 3.3, 3.5, 3.6) |
| `00-start-here-*.eml` | **New Opportunity > Import from file** | Opportunity from an email (1.7) |
| `01-*.vtt` | Upload | Transcript Source |
| `02-*.eml`, `03-*.eml` | Upload | Email Sources |
| `04-*.docx` | Upload | Document Source (Word) |
| `05-*.pdf` | Upload | Document Source (PDF) |
| `06-*.txt` | Upload | Note Source |
| `07-paste-*.txt` | **Paste text** (open, copy, paste) | Pasted Source (2.1b); contains a planted prompt-injection line (2.8) |
| `later/*.eml` | Upload **after** confirming Requirements | Incremental intake, pending changes (2.7) |
| `answers/*.txt` | Paste as a customer answer on a sent Clarification Question | Record answers, "Possible answer" matches, Requirement updates (4.7) |

(Elmbridge numbers its files differently because it keeps its original 01-06; see its README.)

## Feature walkthrough (any scenario)

1. **Knowledge (admin).** Follow `knowledge/setup-catalogue-and-checklist.md`: add the
   catalogue entries, register the Knowledge Source, author and publish the Checklist.
   Then search the Knowledge Base and open Coverage and Graph.
2. **Create the Opportunity.** New Opportunity > Import from file > `00-start-here-*.eml`.
   Review the suggested customer, title, industry and products ("From file"), then create.
   Share it with a collaborator (and a sales rep) to show roles.
3. **Add Sources.** Upload `01`-`06`, then Paste text with the contents of `07`. Open the
   source viewer on a passage. Wait for every Source to be Parsed.
4. **Requirements.** Show the types (functional, integration, data, security,
   non-functional, commercial), the cited Evidence, edit / split / merge / confirm. Check
   the pasted Source's injection line was treated as content, not as an instruction (no
   Requirement was confirmed or changed by it).
5. **Incremental intake.** After confirming some Requirements, upload `later/*.eml`. Show
   the pending changes on locked Requirements, accept or reject them.
6. **Gaps.** Set the Integration Types in scope (the new catalogue ones included) so the
   Checklist applies. Show the deterministic Gaps from mandatory Checklist items, the
   model-detected Gaps, the "Unknown to the customer:" Contingency Gaps versus Condition
   Gaps. Edit, merge, drop and approve Clarification Questions, export them, mark them sent.
7. **Answers.** On a sent question, record an answer by pasting `answers/answer-01-*.txt`.
   Then paste `answer-02-*.txt` against one question: it also answers other sent questions,
   so "Possible answer in Source ..." suggestions appear; Confirm one, reject one. Show the
   Requirement changes the answer caused.
8. **Assessments.** Start the assessment run. Watch the Engineering, PM, Security and
   Research Agents in the agent run panel; pause / resume or cancel one; compare effort.
   The Research Agent cites the Knowledge Source you registered.
9. **Conflicts, Critic, Red Team.** Open Conflicts: the scenario's planted contradictions
   (volumes, dates, availability, hosting / automation) show up. Resolve one with a reason.
   The Red Team flags the fixed-price commercial pressure; show a blocking finding and an
   override.
10. **Estimate.** Draft the Estimate from the Assessments. Convert Gaps into Assumptions
    (Contingencies with hours, Conditions without) and Risks. Edit a line in place. Try to
    submit: the submission blockers gate lists what's missing; clear it and submit. Create
    a new version and compare. Export the Estimate, Assumptions Register and questions.
11. **Review and Challenge.** Send a Review Request to a named reviewer, see the Inbox
    notification, record a decision. Raise a Challenge (each README suggests one), confirm
    reassessment, see the new Estimate Version.
12. **Baseline and Decision Trace.** Set the Baseline. Open Decision Trace, trace a number
    to its Evidence and compare versions.
13. **Actuals.** On the Actuals tab, Import from file > Download template. Fill it with
    `tools/fill_actuals.py` (below) and import it; review the preview and Confirm. Open
    Reports for variance, then drill down from an overrun to the failed Assumption.
14. **Outcome.** Record the outcome (won or lost) and the retention dates.

## Tools

Run from `backend/` (they use the backend venv's `openpyxl` and `python-docx`):

```bash
# Rebuild the .docx and .pdf Sources from tools/doc-sources/ after editing their text
uv run python ../demo-data/tools/build_docs.py

# Fill a downloaded Actuals template (scenario: aldermoor | larkspur | elmbridge)
uv run python ../demo-data/tools/fill_actuals.py ~/Downloads/actuals-template.xlsx aldermoor
```

`fill_actuals.py` overruns the lines of each scenario's planted story (for example the EPR
write-back for Aldermoor), names failed Assumptions from the template's Lists sheet, and
keeps every other line within a few percent of its estimate. Its output passes the app's
import validation.

## Notes

- The model is not deterministic: titles, counts and hours change between runs. The planted
  contradictions, unknowns and customer decisions are written plainly so they come out on
  most runs.
- Upload every Source before opening the Requirements tab, so extraction sees all of them.
  The `later/` file is the exception: it is meant to arrive after Requirements are confirmed.
