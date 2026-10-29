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
    steps: ["Sign in with your company account (Auth0). Your roles decide what you can see; Opportunity access comes from being its owner or a collaborator.", "Use the sidebar or press <kbd>Ctrl</kbd> <kbd>K</kbd> to open the command palette.", "The toggle at the bottom of the sidebar switches light and dark theme; <kbd>[</kbd> collapses the sidebar and <kbd>?</kbd> lists keyboard shortcuts."],
  },
  "1. Prepare your knowledge": {
    id: "knowledge",
    intro: "Knowledge is set up once by an administrator and reused on every bid. Agents cite it, Checklists turn it into mandatory questions, and Coverage shows where it is thin.",
    steps: ["<b>Knowledge > Sources > Register Source</b>: upload a delivery guide or playbook and tag it with products and integration types. It is chunked and indexed for search.", "<b>Knowledge > Checklists > New Checklist</b>: add items for an integration type, mark the must-ask ones as Mandatory, then publish a version.", "<b>Knowledge > Coverage</b>: check each product and integration type for <i>Ready</i>, <i>Partial</i> or <i>Missing</i> coverage.", "<b>Knowledge > Graph</b>: search and explore how products, integration types, sources and checklists connect."],
  },
  "2. Create the opportunity": {
    id: "create",
    intro: "An Opportunity is one bid for one customer. It holds every Source, Requirement, Gap, Assessment and Estimate version for that bid.",
    steps: ["Click <b>New Opportunity</b> (or press <kbd>c</kbd> with single-key shortcuts on).", "Click <b>Import from file</b> and choose the customer's email, transcript or document. Fields marked <i>From file</i> were filled by the Opportunity Intake Agent, with the quote it used.", "Check the customer name, title, products in scope (one per line) and industry, and set the target proposal date.", "Click <b>Create Opportunity</b>. The imported file becomes Source 1. Add collaborators from the Opportunity header."],
  },
  "3. Follow progress on the Overview": {
    id: "overview",
    intro: "The Overview answers one question: what stands between this bid and submission?",
    steps: ["Read the four tiles: Requirements confirmed, Open Gaps, Open Conflicts and the current Estimate.", "Follow the <b>Submission pipeline</b>: eight stages from <i>Sources added</i> to <i>Review and Baseline</i>.", "Work through <b>Needs you</b>, which lists Findings, Gaps and Assumptions waiting for you, most severe first.", "Use <b>Submission blockers</b> to jump straight to whatever stops Submit."],
  },
  "4. Add sources": {
    id: "sources",
    intro: "Sources are the customer's own words. They are stored unchanged and versioned, and every Requirement and Finding cites them.",
    steps: ["Open the <b>Sources</b> tab and drop files, or click <b>Choose files</b>. Supported formats: .eml, .msg, .txt, .docx, .pdf and .vtt (Teams transcripts), up to 50 MB each.", "Click <b>Paste text</b> for a chat message or anything else without a file.", "Wait until every Source shows <i>Parsed</i> before opening Requirements, so extraction sees all of them.", "Select a Source to open the Inspector: metadata, <b>Download original</b>, and the extracted text."],
  },
  "5. Confirm requirements": {
    id: "requirements",
    intro: "Requirements are extracted automatically, but only people confirm them. Confirmed Requirements are locked: later Sources propose changes instead of overwriting them.",
    steps: ["Filter by <b>Category</b> or <b>State</b>, and open a Requirement to see its evidence highlighted in the Source.", "Use <b>Edit</b>, <b>Split</b> or <b>Merge</b> to fix the wording or granularity; change the classification if needed.", "Confirm each Requirement. <b>Add requirement</b> adds one by hand.", "When a new Source changes a confirmed Requirement, accept or reject the pending change.", "Text in a Source that tries to instruct the AI is treated as content and flagged, never followed."],
  },
  "6. Close the gaps": {
    id: "gaps",
    intro: "A Gap is something the estimate needs that the Sources don't say. Each Gap gets a Clarification Question, and every Gap ends in one of four ways: answered, converted to an Assumption (a Condition or a Contingency), converted to a Risk, or dismissed with a reason.",
    steps: ["Set the Integration Types on integration Requirements (the yellow banner shows any that are missing) so the right Checklists apply.", "Review the Gaps, ranked by impact. Filter by Impact, Area or Question status.", "Edit, merge or drop the drafted questions, then <b>Approve</b> (or <b>Approve all</b>), export them and mark them <i>Sent</i>.", "When the customer replies, record the answer on the question. Confirm or reject any <i>Possible answer</i> suggestions on other questions.", "Convert what the customer can't know yet into a <b>Contingency</b> (priced in hours), and what they must decide or provide into a <b>Condition</b>."],
  },
  "7. Run the assessments": {
    id: "assessments",
    intro: "An assessment run asks specialist agents to judge the confirmed scope. They propose; you decide.",
    steps: ["Open <b>Assessments</b> and click <b>Start new run</b>. Watch each agent's progress and duration; pause, resume or cancel a task if needed.", "Read each agent's verdict, confidence, effort and cited Requirements in <b>Results so far</b>.", "Work through <b>Findings</b>, ranked by severity. Resolve each critical Finding, or override it with a reason.", "Disagree with an agent? Click <b>Challenge</b>, give the new information, confirm the reassessment and a new Estimate version follows."],
  },
  "8. Resolve conflicts": {
    id: "conflicts",
    intro: "A Conflict is two things that can't both be true: two dates, two volumes, or two agents sizing the same Requirement differently. Open Conflicts block submission.",
    steps: ["Open <b>Conflicts</b> and select an open Conflict.", "Choose one of the positions shown, or <b>A different position</b>.", "Give a reason (required) and click <b>Resolve</b>. The decision and reason are kept in the resolved list and the Trace."],
  },
  "9. Build and submit the estimate": {
    id: "estimate",
    intro: "The Estimate is built from the Assessments, line by line. Every line covers named Requirements, and every Assumption and Risk comes from a Gap.",
    steps: ["Review the draft lines: covered Requirements, role mix (Engineer, PM, QA), effort, contingency and total hours. Edit a line in place, with a reason.", "Accept each Assumption in the <b>Assumptions Register</b> and check the Contingency hours and Risks.", "Clear the <b>Submission blockers</b>, then <b>Submit</b>. Submitted versions can't be edited; <b>New version</b> starts the next one.", "Send a <b>Review request</b> to a named reviewer. Once approved, set the <b>Baseline</b>.", "Use <b>Diff vs</b> and <b>All versions</b> to compare, and <b>Export</b> the Estimate, Assumptions Register and questions to Excel or Word."],
  },
  "10. Review in the Inbox": {
    id: "inbox",
    intro: "The Inbox holds your review requests and notifications.",
    steps: ["Select an item to open it beside the list.", "As a reviewer, open the Estimate, then approve it or send it back with comments.", "Use <b>Mark all read</b> to clear the list."],
  },
  "11. Track actuals and trace decisions": {
    id: "actuals",
    intro: "After delivery, actual hours close the loop: they show which estimates and which Assumptions held up.",
    steps: ["On <b>Actuals</b>, enter actual hours per line and pick a variance cause; name the failed Assumption on an overrun.", "Or click <b>Import from file</b>: <b>Download template</b>, fill it in, <b>Choose file</b>, review the preview and <b>Confirm</b>.", "Click <b>Save Actuals</b>. <b>Reports</b> then shows estimate against actual across Opportunities, with a drill-down from an overrun to its failed Assumption (Head of Delivery and platform administrators).", "Open <b>Trace</b> and filter by Subject, Actor or Event to audit any decision."],
  },
  "12. Administration": {
    id: "admin",
    intro: "Admin is for platform administrators. Roles themselves are managed in Auth0.",
    steps: ["<b>Users and roles</b>: see who has which role; <b>Invite user</b> opens Auth0.", "<b>Catalogue</b>: add Integration Types and Work Packages (<b>New entry</b>).", "<b>Agents</b>: the registry of agents, versions, models and tool permissions, plus <b>Denied tool calls</b>.", "<b>Evals</b>: run reference sets and check release bars before accepting a new agent configuration.", "<b>Settings</b> (everyone): theme, row density and single-key shortcuts, saved in this browser."],
  },
  "Wrap-up": { id: "wrap", intro: "", steps: [] },
};

const features = [
  ["Opportunities", ["Opportunity list with derived status, open items and current Estimate", "Views: All, Mine, Due in 14 days; filters by status, owner, product and proposal date", "Create by hand or <b>Import from file</b> (email, transcript, document) with AI-suggested fields", "Owner and collaborators; sales representatives see a restricted view", "Overview tiles, eight-stage submission pipeline, <i>Needs you</i> queue, submission blockers, recent activity", "Record the outcome (won or lost), contract end date and retention; reopen with a reason"]],
  ["Sources and intake", ["Upload .eml, .msg, .txt, .docx, .pdf and .vtt, up to 50 MB each, or paste text", "Sources stored unchanged and versioned; download the original", "Source Inspector with extracted text and activity", "Customer answers recorded as Sources", "Prompt-injection lines in customer content flagged and ignored"]],
  ["Requirements", ["Automatic extraction with cited Evidence (source and passage)", "Categories: functional, integration, data, security, non-functional, commercial", "Edit, split, merge, reclassify, add, delete and confirm", "Confirmed Requirements locked; incremental intake raises pending changes to accept or reject", "Integration Type tagging so Checklists apply"]],
  ["Gaps and clarification", ["Model-detected Gaps plus deterministic Gaps from mandatory Checklist items", "Ranked by impact, filtered by impact, area and question status", "Drafted Clarification Questions: edit, merge, drop, approve, approve all, export, mark sent", "Record answers; <i>Possible answer</i> suggestions across other sent questions", "Convert to Condition, Contingency or Risk, or dismiss with a reason", "Banners for missing Integration Types and missing knowledge coverage"]],
  ["Assessments", ["Engineering, PM, Security, Research and Critic agents plus a Red Team", "Live agent run panel with progress, duration, pause, resume, cancel and retry", "Verdict, confidence, effort and cited Requirements per agent", "Findings table by severity; resolve or override with a reason", "Challenges that trigger reassessment and a new Estimate version"]],
  ["Conflicts", ["Contradictions between Sources (dates, volumes) and between agents (sizing)", "Choose a position or a different one, with a required reason", "Open Conflicts block submission; resolved list with who decided"]],
  ["Estimate", ["Lines built from Assessments, covering named Requirements, with role mix and hours", "Edit lines in place with a reason; every edit traced", "Assumptions Register: Conditions and Contingencies (with hours), each from a Gap, each accepted by a named person", "Risks register", "Submission blockers gate; version lifecycle Draft, In review, Approved, Baseline", "Review requests to named reviewers; decisions recorded", "New version, All versions, Diff against any version", "Export to Excel (.xlsx) and Word (.docx)"]],
  ["Actuals and Reports", ["Actual hours per Estimate line with a variance cause and failed Assumption", "Import from an Excel or CSV template with preview and confirm", "Reports: estimate against actual, pipeline and cost, with drill-down to failed Assumptions"]],
  ["Knowledge", ["Knowledge Sources tagged by product and integration type, with review dates and stale flag", "Checklists with mandatory items, versioned and published", "Coverage matrix by product and integration type", "Knowledge Graph with search and coverage states", "Research Agent cites Knowledge Sources in Assessments"]],
  ["Trust and audit", ["Append-only Decision Trace for every human and agent action", "Filter by subject, actor and event; trace a number to its Evidence", "Agent Registry with per-agent tool permissions; denied calls blocked and audited", "Evals with release bars (extraction recall, citation validity, gap recall, evidence support)"]],
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
    execFileSync("ffmpeg", ["-v", "error", "-y", "-i", join(SHOTS, `${s}.png`), "-c:v", "libwebp", "-quality", "88", out]);
}

const order = [...new Set(scenes.map((s) => s.chapter))];
const toc = order.filter((c) => c !== "Wrap-up").map((c) => `<li><a href="#${chapters[c].id}">${esc(c.replace(/^\d+\. /, ""))}</a></li>`).join("");

let figN = 0;
const sections = order.filter((c) => c !== "Wrap-up").map((c) => {
  const ch = chapters[c];
  const num = c.match(/^(\d+)\./)?.[1];
  const figs = scenes.filter((s) => s.chapter === c).map((s) => {
    figN++;
    return `<figure><a class="shot" href="images/${s.img}.webp" target="_blank" rel="noopener"><img src="images/${s.img}.webp" alt="${esc(s.say.split(". ")[0])}" loading="lazy" width="1440" height="900"></a><figcaption><span class="fig">Fig. ${figN}</span>${esc(s.say)}</figcaption></figure>`;
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
<video controls preload="metadata" poster="images/01-opportunities.webp" src="pre-sales-agent-product-tour.mp4">
<track kind="captions" srclang="en" label="English" src="pre-sales-agent-product-tour.vtt" default>
</video>
<p class="vidnote">The narrated video tour (about 10 minutes, with captions) covers the same steps as the walkthrough below.</p>
</header>

<section id="example">
<p class="eyebrow">The example</p>
<h2>Larkspur Mutual claims platform replacement</h2>
<p class="lede">Larkspur Mutual, a fictional general insurer, is replacing its ClaimsOne mainframe claims system. The new platform covers first notification of loss, triage, reserving, settlement and member self-service, with integrations to the policy mainframe, Dynamics 365 finance and SEPA bank payments, and migration of 1.4 million closed claims. The walkthrough shows this bid after it has been through every stage. Where a stage is easier to understand mid-flight, it also shows a second, unfinished bid, <b>Aldermoor Health Trust</b>'s patient and referral portal.</p>
<div class="example"><p>Where Larkspur ended up</p>
<dl><div><dt>Sources</dt><dd>11</dd></div><div><dt>Requirements confirmed</dt><dd>87 of 87</dd></div><div><dt>Gaps closed</dt><dd>23</dd></div><div><dt>Conflicts resolved</dt><dd>38</dd></div><div><dt>Baseline estimate</dt><dd>12,072 h</dd></div><div><dt>Contingency</dt><dd>1,140 h</dd></div></dl></div>
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
