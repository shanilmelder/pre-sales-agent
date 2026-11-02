#!/usr/bin/env node
// Drive the signed-in web app through Chrome's DevTools protocol. No npm dependencies: it
// launches the system Chrome with a dedicated profile (./profile, git-ignored) and talks
// CDP over Node's built-in WebSocket.
//
//   node driver.mjs login                  headed Chrome; sign in to Auth0 once, it closes itself
//   node driver.mjs whoami                 prints the signed-in user (exit 5 if signed out)
//   node driver.mjs <step> [<step> ...]    headless; runs the steps in order
//
// Steps (each is one argument, `verb:arg`; quote it in the shell):
//   goto:/opportunities       navigate (path or full URL) and wait for the load + network idle
//   wait:<css>                wait up to 15 s for a selector to appear
//   click:<css>               click the first match (scrolls it into view first)
//   clicktext:<text>          click the first button/link/tab whose text contains <text>
//   type:<css>=<text>         focus the field, clear it, type <text>
//   text:<css>                print the element's innerText (first 2000 chars)
//   eval:<js>                 print the result of a JS expression in the page
//   shot:<name>               screenshot to shots/<name>.png (full viewport, 1440x900)
//   sleep:<ms>                wait
//
// Exit codes: 0 ok, 5 signed out (run `login`), 6 a step failed, 7 Chrome failed to start.
import { spawn } from "node:child_process";
import { mkdirSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const BASE = process.env.BASE_URL ?? "http://localhost:3000";
const PROFILE = process.env.PROFILE_DIR ?? join(HERE, "profile");
const COOKIES = join(PROFILE, "session-cookies.json");
const SHOTS = process.env.SHOT_DIR ?? join(HERE, "shots");
const CHROME = process.env.CHROME ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = Number(process.env.CDP_PORT ?? 9333);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function launch({ headless }) {
  mkdirSync(PROFILE, { recursive: true });
  const args = [
    `--user-data-dir=${PROFILE}`,
    `--remote-debugging-port=${PORT}`,
    "--no-first-run",
    "--no-default-browser-check",
    // The driver kills Chrome, so the next launch would offer to restore stale tabs.
    "--hide-crash-restore-bubble",
    "--disable-session-crashed-bubble",
    "--window-size=1440,900",
  ];
  if (headless) args.push("--headless=new", "--disable-gpu", "--hide-scrollbars");
  args.push("about:blank");
  const proc = spawn(CHROME, args, { stdio: "ignore" });
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return { proc, page: await connect(page.webSocketDebuggerUrl) };
    } catch {}
    await sleep(200);
  }
  proc.kill();
  console.error(`chrome did not open a DevTools port on ${PORT} (another Chrome on this profile?)`);
  process.exit(7);
}

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((ok, fail) => {
    ws.onopen = ok;
    ws.onerror = fail;
  });
  let id = 0;
  const pending = new Map();
  const listeners = new Set();
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.id && pending.has(data.id)) {
      const { ok, fail } = pending.get(data.id);
      pending.delete(data.id);
      data.error ? fail(new Error(data.error.message)) : ok(data.result);
    } else if (data.method === "Page.javascriptDialogOpening") {
      // A dialog blocks every Runtime.evaluate until it closes; accept it and say so.
      console.error(`dialog (${data.params.type}): ${data.params.message}`);
      send("Page.handleJavaScriptDialog", { accept: true }).catch(() => {});
    } else if (data.method) {
      for (const fn of listeners) fn(data);
    }
  };
  const send = (method, params = {}) =>
    new Promise((ok, fail) => {
      const n = ++id;
      const timer = setTimeout(() => {
        pending.delete(n);
        fail(new Error(`${method} got no answer in 60 s`));
      }, 60000);
      pending.set(n, {
        ok: (v) => (clearTimeout(timer), ok(v)),
        fail: (e) => (clearTimeout(timer), fail(e)),
      });
      if (process.env.CDP_DEBUG) console.error(`cdp> ${method}`);
      ws.send(JSON.stringify({ id: n, method, params }));
    });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Network.enable");
  await send("Emulation.setDeviceMetricsOverride", {
    width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
  });
  return { send, listeners, close: () => ws.close() };
}

async function evaluate(page, expression) {
  const r = await page.send("Runtime.evaluate", {
    expression, awaitPromise: true, returnByValue: true,
  });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? "eval failed");
  return r.result.value;
}

// Load event, then no network request in flight for 500 ms (Next streams RSC after load).
async function settle(page, timeout = 20000) {
  let inflight = 0;
  let last = Date.now();
  const fn = (e) => {
    if (e.method === "Network.requestWillBeSent") inflight++, (last = Date.now());
    if (e.method === "Network.loadingFinished" || e.method === "Network.loadingFailed")
      (inflight = Math.max(0, inflight - 1)), (last = Date.now());
  };
  page.listeners.add(fn);
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const ready = await evaluate(page, "document.readyState").catch(() => "loading");
    if (ready === "complete" && inflight === 0 && Date.now() - last > 500) break;
    await sleep(100);
  }
  page.listeners.delete(fn);
}

async function waitFor(page, css, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await evaluate(page, `!!document.querySelector(${JSON.stringify(css)})`)) return;
    await sleep(150);
  }
  throw new Error(`timed out waiting for ${css}`);
}

async function clickAt(page, expr) {
  const box = await evaluate(page, `(() => {
    const el = ${expr};
    if (!el) return null;
    el.scrollIntoView({ block: "center" });
    const r = el.getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  })()`);
  if (!box) throw new Error("no element to click");
  for (const type of ["mousePressed", "mouseReleased"])
    await page.send("Input.dispatchMouseEvent", { type, ...box, button: "left", clickCount: 1 });
  await settle(page);
}

// A page expression for the first visible form control whose <label> (or aria-label) is the
// text, or failing that contains it. Labels inside a <form> win over toolbar filters. A "last:"
// prefix picks the last match instead (the newest of several repeated items).
const byLabel = (text) => `(() => {
  const last = ${JSON.stringify(text.startsWith("last:"))};
  const t = ${JSON.stringify(text.replace(/^last:/, ""))};
  const visible = (e) => e && e.getClientRects().length > 0;
  const pick = (xs) => (last ? xs.at(-1) : xs[0]) ?? null;
  const labels = [...new Set([...document.querySelectorAll("form label"), ...document.querySelectorAll("label")])];
  const clean = (s) => s.split("*").join("").trim();
  const ctl = (pred) => labels.filter((l) => pred(l) && visible(l.control)).map((l) => l.control);
  const aria = [...document.querySelectorAll("[aria-label]")]
    .filter((e) => e.getAttribute("aria-label").includes(t) && visible(e));
  return pick(ctl((l) => clean(l.innerText) === t)) ?? pick(ctl((l) => l.innerText.includes(t)))
    ?? pick(aria);
})()`;

const url = (p) => (/^https?:/.test(p) ? p : BASE + p);
const location = (page) => evaluate(page, "location.href");
const signedOut = (href) => !href.startsWith(BASE) || new URL(href).pathname.startsWith("/auth/");

const steps = {
  async goto(page, arg) {
    await page.send("Page.navigate", { url: url(arg) });
    await settle(page);
    const href = await location(page);
    if (signedOut(href)) {
      console.error(`signed out (landed on ${href}); run: node driver.mjs login`);
      process.exitCode = 5;
      throw new Error("signed out");
    }
    console.log(`at ${href}`);
  },
  wait: (page, arg) => waitFor(page, arg),
  click: (page, arg) => clickAt(page, `document.querySelector(${JSON.stringify(arg)})`),
  clicktext: (page, arg) =>
    clickAt(page, `[...document.querySelectorAll('button,a,[role=tab],[role=button],[role=menuitem]')]
      .find((e) => e.offsetParent !== null && e.innerText.includes(${JSON.stringify(arg)}))`),
  // clickin:<container css>|<text>  like clicktext:, but only inside the container (e.g. the
  // right pane, so a list row that happens to contain the same word is not hit first)
  clickin: (page, arg) => {
    const [css, text] = arg.split("|");
    return clickAt(page, `[...(document.querySelector(${JSON.stringify(css)})?.querySelectorAll(
      'button,a,[role=tab],[role=button],[role=menuitem]') ?? [])]
      .find((e) => e.offsetParent !== null && e.innerText.trim().startsWith(${JSON.stringify(text)}))`);
  },
  async type(page, arg) {
    const i = arg.indexOf("=");
    const css = arg.slice(0, i);
    await evaluate(page, `(() => { const e = document.querySelector(${JSON.stringify(css)});
      e.focus(); e.select?.(); })()`);
    await page.send("Input.insertText", { text: arg.slice(i + 1) });
  },
  // upload:<css>=<path>|<path>  set files on an <input type=file> and fire its change event.
  // The bytes go in through a DataTransfer: DOM.setFileInputFiles froze headless Chrome's
  // renderer a few seconds later on Windows.
  async upload(page, arg) {
    const i = arg.lastIndexOf("="); // selectors may hold "=", file paths do not
    const files = arg.slice(i + 1).split("|").map((p) => ({
      name: basename(p), b64: readFileSync(p).toString("base64"),
    }));
    const ok = await evaluate(page, `(() => {
      const input = document.querySelector(${JSON.stringify(arg.slice(0, i))});
      if (!input) return false;
      const dt = new DataTransfer();
      for (const f of ${JSON.stringify(files)}) {
        const bytes = Uint8Array.from(atob(f.b64), (c) => c.charCodeAt(0));
        dt.items.add(new File([bytes], f.name));
      }
      input.files = dt.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    if (!ok) throw new Error(`no element ${arg.slice(0, i)}`);
    await settle(page);
  },
  // typelabel:<label text>=<text>  like type:, but finds the field by its visible label
  async typelabel(page, arg) {
    const i = arg.indexOf("=");
    const ok = await evaluate(page, `(() => { const e = ${byLabel(arg.slice(0, i))};
      if (!e) return false; e.scrollIntoView({ block: "center" }); e.focus(); e.select?.(); return true; })()`);
    if (!ok) throw new Error(`no field labelled ${arg.slice(0, i)}`);
    await page.send("Input.insertText", { text: arg.slice(i + 1) });
  },
  // select:<label text>=<option value or text>  choose an option in a <select> found by label
  async select(page, arg) {
    const i = arg.indexOf("=");
    const ok = await evaluate(page, `(() => { const e = ${byLabel(arg.slice(0, i))};
      const want = ${JSON.stringify(arg.slice(i + 1))};
      const o = e && [...e.options].find((o) => o.value === want || o.text.trim() === want);
      if (!o) return false;
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value").set.call(e, o.value);
      e.dispatchEvent(new Event("change", { bubbles: true })); return true; })()`);
    if (!ok) throw new Error(`no option ${arg}`);
    await settle(page);
  },
  // check:<label text>  click a checkbox or radio by its label, if not already checked
  async check(page, arg) {
    const state = await evaluate(page, `(() => { const e = ${byLabel(arg)}; return e ? e.checked : null; })()`);
    if (state === null) throw new Error(`no checkbox labelled ${arg}`);
    if (!state) await clickAt(page, byLabel(arg));
  },
  async text(page, arg) {
    const t = await evaluate(page, `document.querySelector(${JSON.stringify(arg)})?.innerText ?? null`);
    if (t === null) throw new Error(`no element ${arg}`);
    console.log(t.slice(0, 2000));
  },
  async eval(page, arg) {
    console.log(JSON.stringify(await evaluate(page, arg), null, 2));
  },
  async shot(page, arg) {
    mkdirSync(SHOTS, { recursive: true });
    const { data } = await page.send("Page.captureScreenshot", { format: "png" });
    const file = resolve(SHOTS, `${arg}.png`);
    writeFileSync(file, Buffer.from(data, "base64"));
    console.log(`screenshot: ${file}`);
  },
  sleep: (_page, arg) => sleep(Number(arg)),
  // key:Enter / key:Escape / key:Tab  press a key in the focused element
  async key(page, arg) {
    const codes = { Enter: 13, Escape: 27, Tab: 9 };
    const ev = { key: arg, code: arg, windowsVirtualKeyCode: codes[arg] ?? 0 };
    const text = arg === "Enter" ? { text: String.fromCharCode(13) } : {};
    await page.send("Input.dispatchKeyEvent", { type: "keyDown", ...ev, ...text });
    await page.send("Input.dispatchKeyEvent", { type: "keyUp", ...ev });
    await settle(page);
  },
  // /auth/profile answers 204 without a session, the user's claims with one.
  async whoami(page) {
    await page.send("Page.navigate", { url: BASE + "/healthz" });
    await settle(page);
    const me = await evaluate(page, `fetch("/auth/profile").then((r) => r.status === 200 ? r.json() : null)`);
    if (!me) {
      console.error("signed out; run: node driver.mjs login");
      process.exitCode = 5;
      throw new Error("signed out");
    }
    console.log(`signed in as ${me.email ?? me.name ?? me.sub}`);
  },
};

async function login() {
  // Headed: a person types the Auth0 credentials. The session cookie lands in ./profile.
  const { proc, page: first } = await launch({ headless: false });
  // Start from no cookies: a half-finished login left in the profile makes Auth0 answer "we
  // couldn't find your session".
  await first.send("Network.clearBrowserCookies");
  await first.send("Page.navigate", { url: BASE + "/auth/login?returnTo=%2Fopportunities" });
  first.close();
  console.log("sign in in the Chrome window; waiting up to 5 minutes...");
  const end = Date.now() + 300000;
  while (Date.now() < end) {
    await sleep(1000);
    // Poll the HTTP target list, not the page socket: the Auth0 round trip can swap the page's
    // renderer and drop the socket, which would leave a CDP call waiting forever.
    const list = await fetch(`http://127.0.0.1:${PORT}/json/list`).then((r) => r.json()).catch(() => []);
    const target = list.find((t) => t.type === "page" && t.url && !signedOut(t.url));
    if (target) {
      const href = target.url;
      const page = await connect(target.webSocketDebuggerUrl);
      await settle(page);
      // Killing Chrome loses cookies it hasn't flushed to the profile yet, so keep them in a file
      // that run() loads back.
      const { cookies } = await page.send("Network.getCookies", { urls: [BASE] });
      writeFileSync(COOKIES, JSON.stringify(cookies));
      console.log(`signed in (${href})`);
      page.close();
      proc.kill();
      return;
    }
  }
  proc.kill();
  console.error("gave up waiting for sign-in");
  process.exit(5);
}

async function run(argv) {
  const { proc, page } = await launch({ headless: true });
  try {
    if (existsSync(COOKIES)) {
      await page.send("Network.setCookies", { cookies: JSON.parse(readFileSync(COOKIES, "utf8")) });
    }
    for (const step of argv) {
      const i = step.indexOf(":");
      const verb = i < 0 ? step : step.slice(0, i);
      const arg = i < 0 ? "" : step.slice(i + 1);
      if (!steps[verb]) throw new Error(`unknown step: ${verb}`);
      await steps[verb](page, arg);
    }
  } catch (err) {
    console.error(`step failed: ${err.message}`);
    process.exitCode ||= 6;
    await steps.shot(page, "error").catch(() => {});
  } finally {
    page.close();
    proc.kill();
  }
}

const [cmd, ...rest] = process.argv.slice(2);
if (!cmd) {
  console.error("usage: node driver.mjs login | whoami | <step> [<step> ...]");
  process.exit(64);
}
if (!existsSync(CHROME)) {
  console.error(`no Chrome at ${CHROME}; set CHROME=...`);
  process.exit(7);
}
if (cmd === "login") await login();
else await run([cmd, ...rest]);
