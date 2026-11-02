// Build docs/user-guide/index.html from scenes.json + the chapter text below.
//   node build-guide.mjs <repo> <shots dir>
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const [REPO, SHOTS] = process.argv.slice(2);
const OUT = join(REPO, "docs/user-guide");
const IMG = join(OUT, "images");
mkdirSync(IMG, { recursive: true });
const scenes = JSON.parse(readFileSync(join(OUT, "scenes.json"), "utf8"));
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// Chapter intros and how-to steps (the figure captions come from the narration).
const chapters = {
  "Welcome": {
    id: "welcome",
    intro: "The Pre Sales Agent Framework helps a presales team answer a tender. You give it everything the customer sent. Agents extract the requirements, find what's missing, assess feasibility and effort, and draft an estimate. People confirm, decide and approve at every step, and every number can be traced back to the sentence it came from.",
    steps: ["Sign in with your company account (Auth0). Your roles decide what you can see; Opportunity access comes from being its owner, a collaborator or a reviewer.", "Use the sidebar or press <kbd>Ctrl</kbd> <kbd>K</kbd> to open the command palette.", "The toggle at the bottom of the sidebar switches light and dark theme; <kbd>[</kbd> collapses the sidebar and <kbd>?</kbd> lists keyboard shortcuts."],
  },
  "1. Prepare your knowledge": {
    id: "knowledge",
    intro: "Knowledge is set up once by an administrator and reused on every bid. Agents cite it, Checklists turn it into must-ask questions, and Coverage shows where it is thin.",
    steps: ["<b>Admin > Catalogue > New entry</b>: add each Integration Type and Work Package with a code, name and definition.", "<b>Knowledge > Sources > Register Source</b>: upload a delivery guide or playbook, give it a title and product, and tick the Integration Types it covers. Wait for <i>Ready</i>; if it shows <i>Embedding failed</i>, check the embedding model server is running and click <b>Retry</b>.", "<b>Knowledge > Checklists > New Checklist</b>: name it, choose a domain and scope (products or Integration Types), add items with an impact and a reason, tick <i>Mandatory</i> on the must-ask ones, then <b>Publish</b>.", "<b>Knowledge > Coverage</b> and <b>Graph</b>: check each product and Integration Type for <i>Ready</i>, <i>Partial</i> or <i>Missing</i> coverage."],
  },
  "2. Create the opportunity": {
    id: "create",
    intro: "An Opportunity is one bid for one customer. It holds every Source, Requirement, Gap, Assessment and Estimate version for that bid, and its Overview tracks eight stages from Sources added to Review and Baseline.",
    steps: ["Click <b>New Opportunity</b> (or press <kbd>c</kbd> with single-key shortcuts on).", "Click <b>Import from file</b> and choose the customer's email, transcript or document. Fields marked <i>From file</i> were filled by the Opportunity Intake Agent.", "Check the customer name, title, products in scope (one per line), industry and target proposal date.", "Click <b>Create Opportunity</b>. The imported file becomes Source 1 and the Overview opens."],
  },
  "3. Add sources": {
    id: "sources",
    intro: "Sources are the customer's own words. They are stored unchanged and versioned, and every Requirement and Finding cites them. Stage 1 of the pipeline is complete when every Source is parsed.",
    steps: ["Open the <b>Sources</b> tab and drop files, or click <b>Choose files</b>: .eml, .msg, .txt, .docx, .pdf and .vtt (Teams transcripts), up to 50 MB each.", "Click <b>Paste text</b> for a chat message or anything else without a file, then <b>Add</b>.", "Wait until every Source shows <i>Parsed</i>.", "Select a Source to open the Inspector: metadata, <b>Download original</b>, and the extracted text.", "Text that tries to instruct the AI (for example \"ignore previous instructions\") is treated as content and never followed."],
  },
  "4. Confirm requirements": {
    id: "requirements",
    intro: "The Intake Agent extracts Requirements automatically, but only people confirm them. Confirmed Requirements are locked: later Sources propose changes instead of overwriting them. Stages 2 and 3 cover extraction and confirmation.",
    steps: ["Filter by <b>Category</b> or <b>State</b>, and open a Requirement to see its Evidence highlighted in the Source.", "Use <b>Edit</b>, <b>Split</b> or <b>Merge</b> to fix wording or granularity. To merge, select each Requirement for merge, click <b>Merge (n)</b>, write the merged text and click <b>Merge</b>.", "Tick the Integration Types on each integration Requirement in the Inspector; the Gaps page warns about any without one.", "Click <b>Confirm all</b> (or <b>Confirm</b> on each).", "When a new Source changes a confirmed Requirement, a <i>pending changes</i> panel appears. Click <b>Review</b>, then <b>Accept</b> or <b>Reject</b>, and confirm again.", "If the banner says Assessments used Requirements that have changed, re-run them from the Assessments tab."],
  },
  "5. Close the gaps": {
    id: "gaps",
    intro: "A Gap is something the estimate needs that the Sources don't say. Each Gap gets a Clarification Question. Every Gap ends in one of four ways: answered, converted to an Assumption (a Condition or a Contingency), converted to a Risk, or dismissed with a reason. Stage 4 is complete when none is open.",
    steps: ["Review the Gaps, ranked by impact. Filter by Impact, Area or Question status. Mandatory Checklist Gaps are marked <i>Checklist</i> and <i>Mandatory</i>.", "Open a Gap and use <b>Edit question</b> to sharpen the draft, then <b>Approve question</b> or <b>Approve all</b>.", "<b>Export questions</b> as Word, an email draft (.eml) or copied text, then <b>Mark all sent</b> with the date.", "When the customer replies, open the question, click <b>Record answer</b>, paste the answer and record it. The answer becomes a Source.", "Where the app shows <i>Possible answer in Source …</i> on another question, click <b>Confirm</b> or <b>Not an answer</b>.", "Gaps the customer can't answer yet become Contingencies, and decisions they own become Conditions, when you accept the Estimate's Assumptions (step 8). Use <b>Convert to Risk</b> or <b>Dismiss</b> for the rest."],
  },
  "6. Run the assessments": {
    id: "assessments",
    intro: "Specialist agents judge the confirmed scope. They propose; you decide. Runs start automatically when Requirements and Gaps change, and you can start one yourself. Stage 5 is complete when no critical Finding is open.",
    steps: ["Open <b>Assessments</b>. The agent run panel shows each agent's progress and time; <b>Cancel run</b> or <b>Start new run</b> from there.", "Read each agent's verdict, confidence, effort and cited Requirements in <b>Results so far</b>.", "Disagree? Click <b>Challenge</b> on an agent's result, give the reason (required), choose the Assessments to rerun and click <b>Rerun</b>. A new Estimate version follows.", "Work through <b>Findings</b>, ranked by severity. For each critical Finding choose <b>Supply Evidence</b>, <b>Mark resolved</b> or <b>Override</b>, with a reason."],
  },
  "7. Resolve conflicts": {
    id: "conflicts",
    intro: "A Conflict is two things that can't both be true: two dates, two volumes, or two agents sizing the same Requirement differently. Stage 6 is complete when none is open.",
    steps: ["Open <b>Conflicts</b>; the first open Conflict is selected.", "Choose one of the positions shown, or <b>A different position</b>.", "Give a reason (required) and click <b>Resolve</b>. The decision and reason are kept in the resolved list and the Trace."],
  },
  "8. Build and submit the estimate": {
    id: "estimate",
    intro: "The Estimate is built from the Assessments, line by line. Every line covers named Requirements, and every Assumption and Risk comes from a Gap. Stage 7 is complete when every Assumption is accepted.",
    steps: ["Review the lines: covered Requirements, role mix (Engineer, PM, QA), effort, contingency and total hours.", "To change a line, click its title, set <b>Effort (h)</b> or the role mix, give a <b>Reason for the change</b> and <b>Save</b>. The line is marked <i>Edited</i>.", "In the <b>Assumptions Register</b>, check the Conditions and Contingencies (with hours), then <b>Accept</b> each or <b>Accept all</b>. Accepting converts the Gaps they came from.", "When the Overview shows no blockers, click <b>Submit</b> and confirm. Submitted versions can't be edited; <b>New version</b> starts the next one.", "Use <b>Diff vs</b>, <b>All versions</b> and <b>Export</b> (Excel or Word)."],
  },
  "9. Review and baseline": {
    id: "review",
    intro: "Stage 8: a named reviewer approves the submitted version, and the owner sets it as the Baseline that delivery is measured against.",
    steps: ["Share the Opportunity: on the Overview, type a name or email under <b>Add collaborator</b> and click <b>Add</b>.", "On the Estimate, click <b>Request review</b>, choose the review type (Engineering, PM or Security), choose reviewers, add a message and click <b>Send</b>.", "The reviewer opens it from their <b>Inbox</b> and chooses <b>Approve</b>, <b>Reject</b>, <b>Challenge</b>, <b>Request evidence</b>, <b>Request alternative</b> or <b>Escalate</b>. The owner is notified in their Inbox.", "Once approved, click <b>Set Baseline</b> and confirm. A Baseline is replaced only by a newer approved version.", "Open <b>Trace</b> and filter by Subject, Actor or Event to audit any decision."],
  },
  "10. Track actuals and close the bid": {
    id: "actuals",
    intro: "After delivery, actual hours close the loop: they show which estimates, and which Assumptions, held up. The outcome then sets how long the data is kept.",
    steps: ["On <b>Actuals</b>, click <b>Import from file</b>, then <b>Download template</b>. Fill in Actual h and a variance cause per line, naming the failed Assumption on an overrun.", "Click <b>Choose file</b>, check the preview (to create, to correct, invalid) and click <b>Confirm</b>. Or enter hours by line and click <b>Save Actuals</b>.", "On the Overview, click <b>Mark as won</b> or <b>Close as lost</b>, give a reason and confirm. The Outcome card shows the retention date; <b>Reopen</b> undoes it with a reason."],
  },
  "11. Reports": {
    id: "reports",
    intro: "Reports compare estimates with actuals across every Opportunity you can read. They are for the Head of Delivery and platform administrators.",
    steps: ["Open <b>Reports > Estimate vs actual</b>. The tiles show closed Opportunities, total variance and failed Assumptions.", "Choose <b>Group by</b>: Integration Type, Opportunity, Product, Work Package or Cause. Filter by product, work package, integration type, cause and closed dates.", "Expand a row to see the Opportunities behind it, and click its failed Assumptions to see which ones failed, with a link to the Trace.", "Pipeline and Cost and usage are not available yet."],
  },
  "12. Administration": {
    id: "admin",
    intro: "Admin is for platform administrators. Roles themselves are managed in Auth0.",
    steps: ["<b>Users and roles</b>: who has which role; <b>Invite user</b> opens Auth0.", "<b>Agents</b>: the registry of agents, versions, models and tool permissions, plus <b>Denied tool calls</b>.", "<b>Evals</b>: run reference sets and check release bars before accepting a new agent configuration.", "<b>Retention</b>: Opportunities due for purge in the next 30 days and the last 20 purges. Purging is automatic after the retention date.", "<b>Settings</b> (everyone): theme, row density and single-key shortcuts, saved in this browser."],
  },
  "Wrap-up": { id: "wrap", intro: "", steps: [] },
};

const features = [
  ["Opportunities", ["Opportunity list with derived status, open items and current Estimate", "Views: All, Mine, Due in 14 days; filters by status, owner, product and proposal date", "Create by hand or <b>Import from file</b> (email, transcript, document) with AI-filled fields", "Owner, collaborators and reviewers; sales representatives see a restricted view", "Overview: tiles, eight-stage submission pipeline, <i>Needs you</i> queue, submission blockers, recent activity, latest agent decision", "Outcome: won or lost with a reason, retention date, reopen with a reason"]],
  ["Sources and intake", ["Upload .eml, .msg, .txt, .docx, .pdf and .vtt, up to 50 MB each, or paste text", "Sources stored unchanged and versioned; download the original", "Source Inspector with extracted text and activity", "Customer answers recorded as Sources", "Prompt-injection text in customer content treated as content and flagged"]],
  ["Requirements", ["Automatic extraction with cited Evidence (source and passage)", "Categories: functional, integration, data, security, non-functional, commercial", "Edit, split, merge, reclassify, add, delete, confirm and confirm all", "Integration Type tagging so Checklists apply", "Locked once confirmed; incremental intake raises pending changes to accept or reject", "Warning when Assessments used Requirements that have since changed"]],
  ["Gaps and clarification", ["Model-detected Gaps plus mandatory Gaps from Checklist items", "Ranked by impact; filters by impact, area and question status", "Drafted Clarification Questions: edit, approve, approve all, export (Word, .eml, copy), mark sent", "Record answers; <i>Possible answer</i> suggestions on other sent questions to confirm or reject", "Convert to Condition or Contingency (via Assumptions), convert to Risk, or dismiss with a reason", "Banners for missing Integration Types and missing knowledge coverage"]],
  ["Assessments", ["Engineering, PM, Security and Research agents, a Critic and a Red Team", "Live agent run panel with progress, duration, cancel and new run", "Verdict, confidence, effort and cited Requirements per agent", "Findings by severity; supply evidence, mark resolved or override with a reason", "Challenges that rerun chosen Assessments and produce a new Estimate version"]],
  ["Conflicts", ["Contradictions between Sources and between agents' sizing", "Choose a position or a different one, with a required reason", "Open Conflicts block submission; resolved list with who decided"]],
  ["Estimate", ["Lines built from Assessments, covering named Requirements, with role mix and hours", "Edit lines in place with a reason; every edit traced and marked Edited", "Assumptions Register: Conditions and Contingencies (with hours), each from a Gap, accepted by a named person", "Risks register", "Submission blockers; version lifecycle Draft, In review, Approved, Baseline", "Review requests by type (Engineering, PM, Security) to named reviewers", "New version, All versions, Diff against any version; export to Excel and Word"]],
  ["Review", ["Reviewer Inbox with the full review page", "Decisions: approve, reject, challenge, request evidence, request alternative, escalate", "Owner notified of every decision; Set Baseline on an approved version"]],
  ["Actuals and Reports", ["Actual hours per Estimate line with a variance cause and failed Assumption", "Import from an Excel or CSV template with preview and confirm", "Estimate vs actual report grouped by Integration Type, Opportunity, Product, Work Package or Cause", "Drill-down to Opportunities and failed Assumptions, linked to the Trace", "Pipeline and Cost and usage reports (not available yet)"]],
  ["Knowledge", ["Catalogue of Integration Types and Work Packages", "Knowledge Sources tagged by product and Integration Type, with review dates, stale flag and retry", "Checklists with mandatory items, versioned and published", "Coverage matrix and Knowledge Graph", "Research Agent cites Knowledge Sources in Assessments"]],
  ["Trust and audit", ["Append-only Trace of every human and agent action, filterable by subject, actor and event", "Agent Registry with per-agent tool permissions; denied calls blocked and audited", "Evals with release bars (extraction recall, citation validity, gap recall, evidence support)", "Retention: automatic purge after the retention date, with a due list and purge history"]],
  ["Workspace", ["Inbox for review requests and notifications", "Command palette (<kbd>Ctrl</kbd> <kbd>K</kbd>), keyboard shortcuts (<kbd>?</kbd>), collapsible sidebar", "Light, dark or system theme; comfortable or compact density; optional single-key shortcuts", "Roles from Auth0: presales engineer, delivery manager, engineering reviewer, Head of Delivery, sales representative, platform administrator"]],
];

const glossary = [
  ["Opportunity", "One bid for one customer."],
  ["Source", "Anything the customer sent or said: an email, transcript, document, note or answer. Stored unchanged."],
  ["Evidence", "The exact passage in a Source that supports a Requirement or Finding."],
  ["Requirement", "One thing the customer needs, with its category and Evidence. People confirm it."],
  ["Gap", "Information the estimate needs that the Sources don't give."],
  ["Clarification Question", "The question that closes a Gap, approved and sent to the customer."],
  ["Condition", "An Assumption the customer must make true: a decision or something they provide. No hours."],
  ["Contingency", "An Assumption for something nobody can know yet, priced as an allowance in hours."],
  ["Assessment", "A specialist agent's verdict, effort and reasoning for the confirmed scope."],
  ["Finding", "A problem an agent raises, ranked by severity. Critical Findings block submission."],
  ["Conflict", "Two statements or sizings that can't both be true."],
  ["Baseline", "The approved Estimate version that delivery is measured against."],
  ["Actuals", "Hours actually spent per Estimate line, with the cause of any variance."],
  ["Trace", "The append-only record of every action, by people and agents."],
];

// Convert screenshots once to WebP for the page.
for (const s of new Set(scenes.map((x) => x.img))) {
  const out = join(IMG, `${s}.webp`);
  if (!existsSync(out))
    execFileSync("ffmpeg", ["-v", "error", "-y", "-i", join(SHOTS, `${s}.png`), "-vf", "scale=1920:-1:flags=lanczos", "-c:v", "libwebp", "-quality", "90", out]);
}

const order = [...new Set(scenes.map((s) => s.chapter))];
const toc = order.filter((c) => c !== "Wrap-up").map((c) => `<li><a href="#${chapters[c].id}">${esc(c.replace(/^\d+\. /, ""))}</a></li>`).join("");

let figN = 0;
const sections = order.filter((c) => c !== "Wrap-up").map((c) => {
  const ch = chapters[c];
  const num = c.match(/^(\d+)\./)?.[1];
  const figs = scenes.filter((s) => s.chapter === c).map((s) => {
    figN++;
    return `<figure><a class="shot" href="images/${s.img}.webp" target="_blank" rel="noopener"><img src="images/${s.img}.webp" alt="${esc(s.say.split(". ")[0])}" loading="lazy" width="1920" height="1200"></a><figcaption><span class="fig">Fig. ${figN}</span>${esc(s.say)}</figcaption></figure>`;
  }).join("");
  const steps = ch.steps.length ? `<div class="how"><h3>How to</h3><ol>${ch.steps.map((x) => `<li>${x}</li>`).join("")}</ol></div>` : "";
  return `<section id="${ch.id}"><p class="eyebrow">${num ? `Step ${num}` : "Start here"}</p><h2>${esc(c.replace(/^\d+\. /, ""))}</h2><p class="lede">${ch.intro}</p>${steps}${figs}</section>`;
}).join("\n");

const featureHtml = features.map(([area, items]) => `<div class="farea"><h3>${area}</h3><ul>${items.map((i) => `<li>${i}</li>`).join("")}</ul></div>`).join("");
const glossHtml = glossary.map(([t, d]) => `<div><dt>${t}</dt><dd>${d}</dd></div>`).join("");

const html = `<title>Pre Sales Agent User Guide</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@500&display=swap">
<style>
/* Layout: sticky contents rail beside one reading column; screenshots run the column's full width. */
:root {
  --bg: #f6f7fb; --surface: #ffffff; --ink: #1b2033; --muted: #5b6380; --line: #dfe2ee;
  --accent: #4f46e5; --accent-soft: #eceafe; --ok: #15803d;
  --display: "Sora", "Segoe UI", system-ui, sans-serif;
  --body: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11141f; --surface: #181c2b; --ink: #e7e9f3; --muted: #9aa1bd; --line: #2a3047;
  --accent: #8b85ff; --accent-soft: #24234a; --ok: #4ade80; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #11141f; --surface: #181c2b; --ink: #e7e9f3; --muted: #9aa1bd; --line: #2a3047;
  --accent: #8b85ff; --accent-soft: #24234a; --ok: #4ade80; color-scheme: dark }
* { box-sizing: border-box }
body { background: var(--bg); color: var(--ink); font: 16px/1.65 var(--body);
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px)); }
a { color: var(--accent) }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px }
kbd { font: 500 0.8em var(--mono); background: var(--surface); border: 1px solid var(--line); border-bottom-width: 2px; border-radius: 5px; padding: 0.05em 0.4em }
.wrap { max-width: 1180px; margin: 0 auto; display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 56px; padding-block: 48px 96px }
nav { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 24px); align-self: start; font-size: 14px }
nav p { font: 600 11px var(--body); letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); margin: 0 0 10px }
nav ol { list-style: none; margin: 0 0 24px; padding: 0; display: grid; gap: 2px; counter-reset: s }
nav li a { display: block; color: var(--muted); text-decoration: none; padding: 5px 10px; border-radius: 6px }
nav li a:hover { color: var(--ink); background: var(--accent-soft) }
main { min-width: 0; max-width: 820px }
header h1 { font: 700 clamp(34px, 5vw, 52px)/1.08 var(--display); letter-spacing: -0.02em; margin: 0 0 16px; text-wrap: balance }
header .sub { font-size: 19px; color: var(--muted); margin: 0 0 28px; max-width: 62ch }
.meta { display: flex; flex-wrap: wrap; gap: 8px 20px; font-size: 13px; color: var(--muted); margin-bottom: 32px }
.meta b { color: var(--ink); font-weight: 600 }
video { width: 100%; max-width: 100%; aspect-ratio: 16 / 10; display: block; border-radius: 10px; border: 1px solid var(--line); background: #0f1220 }
.vidnote { font-size: 13px; color: var(--muted); margin: 8px 0 0 }
section { padding-top: 64px }
.eyebrow { font: 600 12px var(--body); letter-spacing: 0.12em; text-transform: uppercase; color: var(--accent); margin: 0 0 6px }
h2 { font: 600 30px/1.2 var(--display); letter-spacing: -0.01em; margin: 0 0 14px; text-wrap: balance }
h3 { font: 600 17px var(--display); margin: 0 0 10px }
.lede { font-size: 17.5px; max-width: 66ch; margin: 0 0 24px }
.how { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 20px 24px 8px; margin-bottom: 32px }
.how ol { margin: 0; padding-left: 22px; display: grid; gap: 8px }
.how li { padding-left: 4px; max-width: 68ch }
.how li::marker { font: 500 14px var(--mono); color: var(--accent) }
.how ol { padding-bottom: 14px }
figure { margin: 0 0 36px }
.shot { display: block; border-radius: 10px; overflow: hidden; border: 1px solid var(--line); box-shadow: 0 8px 28px -18px rgba(20, 24, 60, 0.45) }
.shot img { display: block; width: 100%; height: auto }
figcaption { font-size: 14.5px; color: var(--muted); margin-top: 10px; max-width: 70ch }
.fig { font: 500 12px var(--mono); color: var(--accent); margin-right: 8px }
.example { border-left: 3px solid var(--accent); background: var(--accent-soft); border-radius: 0 10px 10px 0; padding: 16px 20px; margin: 0 0 8px }
.example p { margin: 0 }
.example dl { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 14px 0 0 }
.example dt { font-size: 12px; color: var(--muted) }
.example dd { margin: 0; font: 600 18px var(--display); font-variant-numeric: tabular-nums }
.gloss { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px 28px; margin: 0 }
.gloss dt { font-weight: 600 }
.gloss dd { margin: 2px 0 0; color: var(--muted); font-size: 15px }
.features { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 28px 32px }
.farea h3 { padding-bottom: 8px; border-bottom: 1px solid var(--line) }
.farea ul { margin: 0; padding-left: 18px; display: grid; gap: 6px; font-size: 15px }
.farea li::marker { color: var(--accent) }
footer { margin-top: 72px; padding-top: 20px; border-top: 1px solid var(--line); font-size: 13px; color: var(--muted) }
@media (max-width: 880px) { .wrap { grid-template-columns: minmax(0, 1fr); gap: 0; padding-block: 28px 64px } nav { display: none } }
@media (prefers-reduced-motion: reduce) { * { scroll-behavior: auto !important } }
html { scroll-behavior: smooth }
</style>
<div class="wrap">
<nav aria-label="Contents">
<p>Guide</p>
<ol><li><a href="#tour">Video tour</a></li><li><a href="#example">The example</a></li><li><a href="#concepts">Key terms</a></li></ol>
<p>Walkthrough</p>
<ol>${toc}</ol>
<p>Reference</p>
<ol><li><a href="#features">Full feature list</a></li></ol>
</nav>
<main>
<header id="tour">
<p class="eyebrow">User guide</p>
<h1>Pre Sales Agent Framework</h1>
<p class="sub">From the customer's first email to a reviewed, baselined estimate. This guide follows one real bid through the app, step by step, with screenshots from the running product.</p>
<div class="meta"><span><b>Version</b> 0.1.0-local</span><span><b>Captured</b> 29 October 2026</span><span><b>Narration</b> ElevenLabs, voice “Alice”</span></div>
<video controls preload="metadata" poster="images/000-title-card.webp" src="pre-sales-agent-product-tour.mp4">
<track kind="captions" srclang="en" label="English" src="pre-sales-agent-product-tour.vtt" default>
</video>
<p class="vidnote">The narrated video tour (about 15 minutes, with captions) covers the same steps as the walkthrough below.</p>
</header>

<section id="example">
<p class="eyebrow">The example</p>
<h2>Larkspur Mutual claims platform replacement</h2>
<p class="lede">Larkspur Mutual, a fictional general insurer, is replacing its ClaimsOne mainframe claims system. The new platform covers first notification of loss, triage, reserving, settlement and member self-service, with integrations to the policy mainframe, Dynamics 365 finance and SEPA bank payments, and migration of 1.4 million closed claims. The walkthrough starts from an empty workspace and takes this bid through all eight stages of the submission pipeline, then records actuals and the outcome. Every screenshot comes from that one run.</p>
<div class="example"><p>Where Larkspur ended up</p>
<dl><div><dt>Sources</dt><dd>11</dd></div><div><dt>Requirements confirmed</dt><dd>74 of 74</dd></div><div><dt>Conflicts resolved</dt><dd>26</dd></div><div><dt>Baseline estimate</dt><dd>10,022 h</dd></div><div><dt>Contingency</dt><dd>920 h</dd></div><div><dt>Actual vs estimate</dt><dd>+3.1%</dd></div></dl></div>
<p class="vidnote">All names, companies and email domains in the demo data are fictional. Try it yourself with the files in <code>demo-data/</code>.</p>
</section>

<section id="concepts">
<p class="eyebrow">Key terms</p>
<h2>The words the app uses</h2>
<dl class="gloss">${glossHtml}</dl>
</section>

${sections}

<section id="features">
<p class="eyebrow">Reference</p>
<h2>Full feature list</h2>
<p class="lede">Everything the application does today, grouped by area.</p>
<div class="features">${featureHtml}</div>
</section>

<footer>Pre Sales Agent Framework user guide. Screenshots taken from the local build on main, 29 October 2026. Agent output varies between runs, so your titles, counts and hours will differ.</footer>
</main>
</div>
`;
writeFileSync(join(OUT, "index.html"), html);
console.log(`wrote ${join(OUT, "index.html")} with ${figN} figures`);
