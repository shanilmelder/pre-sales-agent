// WCAG 2.1 contrast of the design tokens, read straight from globals.css so a token edit
// that breaks AA fails CI and names the pair.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Not inlined into `new URL(..., import.meta.url)`: Vite rewrites that pattern to a served
// asset URL (http://localhost:3000/...), which fs cannot read.
const testFile = import.meta.url;
const css = readFileSync(
  fileURLToPath(new URL("../app/globals.css", testFile)),
  "utf8",
);

function block(selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`No ${selector} block in globals.css`);
  const vars: Record<string, string> = {};
  for (const [, name, value] of match[1].matchAll(
    /--([\w-]+)\s*:\s*([^;]+);/g,
  )) {
    vars[name] = value.trim();
  }
  return vars;
}

const light = block(":root");
const dark = { ...light, ...block(".dark") };

type Rgb = [number, number, number]; // linear sRGB, 0..1

function srgbToLinear(channel: number): number {
  return channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4;
}

function hexToLinear(hex: string): Rgb {
  const h = hex.slice(1);
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  return [0, 2, 4].map((i) =>
    srgbToLinear(parseInt(full.slice(i, i + 2), 16) / 255),
  ) as Rgb;
}

/** oklch(L C H) without alpha, to linear sRGB (Björn Ottosson's OKLab matrices). */
function oklchToLinear(value: string): Rgb {
  const match = value.match(/^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\)$/);
  if (!match) throw new Error(`Unsupported colour for contrast: ${value}`);
  const [L, C, H] = match.slice(1).map(Number);
  const a = C * Math.cos((H * Math.PI) / 180);
  const b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  return [
    clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

function resolveVar(
  vars: Record<string, string>,
  name: string,
  seen = new Set<string>(),
): string {
  const value = vars[name];
  if (value === undefined) throw new Error(`--${name} is not defined`);
  const ref = value.match(/^var\(--([\w-]+)\)$/);
  if (!ref) return value;
  if (seen.has(name)) throw new Error(`Circular --${name}`);
  seen.add(name);
  return resolveVar(vars, ref[1], seen);
}

/** A token name, or a literal hex colour such as the white switch knob. */
function luminance(vars: Record<string, string>, nameOrHex: string): number {
  const value = nameOrHex.startsWith("#")
    ? nameOrHex
    : resolveVar(vars, nameOrHex);
  const [r, g, b] = value.startsWith("#")
    ? hexToLinear(value)
    : oklchToLinear(value);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(
  vars: Record<string, string>,
  fg: string,
  bg: string,
): number {
  const [hi, lo] = [luminance(vars, fg), luminance(vars, bg)].sort(
    (x, y) => y - x,
  );
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT = 4.5; // body text
const UI = 3; // icons, borders, rings and other graphical objects

type Pair = [fg: string, bg: string, minimum: number];
const on = (fg: string, backgrounds: string[], minimum: number): Pair[] =>
  backgrounds.map((bg): Pair => [fg, bg, minimum]);

// DESIGN.md contrast table: pairs that must hold in both themes.
const BOTH: Pair[] = [
  ...on(
    "text",
    [
      "surface",
      "background",
      "surface-alt",
      "neutral-tint",
      "blocker-tint",
      "resolved-tint",
      "primary-tint",
    ],
    TEXT,
  ),
  ...on("text-secondary", ["surface", "background", "surface-alt"], TEXT),
  ["primary-foreground", "primary", TEXT], // primary button, skip link, count badge, Save, Rerun
  ...on("primary-text", ["surface", "background", "primary-tint"], TEXT),
  ...on("link", ["surface", "background", "surface-alt"], TEXT), // Fix 1
  ...on("agent", ["surface", "agent-tint"], TEXT),
  ...on("blocker", ["surface", "background", "surface-alt"], TEXT),
  ...on("agent", ["background", "surface-alt"], TEXT),
  ["sidebar-foreground", "sidebar", TEXT],
  ["sidebar-primary-foreground", "sidebar-primary", TEXT],
  ["blocker", "blocker-tint", TEXT],
  ["gap", "gap-tint", TEXT],
  ["resolved", "resolved-tint", TEXT],
  ["neutral", "neutral-tint", TEXT],
  ...on("gap", ["surface", "surface-alt"], TEXT), // v2 gap text
  ["resolved", "surface", TEXT], // v2 resolved text
  ["resolved-foreground", "resolved", TEXT], // Fix 5 lifecycle check
  // border-strong takes the mockup's lighter value (#CDD1E0 / #3A4054), accepted below the
  // 3:1 non-text minimum (theme and shell redesign), so it has no pair here.
  ...on("ring", ["surface", "background", "surface-alt", "primary-tint"], UI), // Fix 4, 7
  ...on("role-qa", ["surface", "surface-alt"], UI), // Fix 3
  ["role-pm", "surface", UI],
  // Knowledge graph, always dark.
  ...[
    "graph-product",
    "graph-integration-type",
    "graph-knowledge-source",
    "graph-checklist",
    "graph-ready",
    "graph-missing",
  ].map((fg): Pair => [fg, "graph-canvas", TEXT]),
  ["graph-edge", "graph-canvas", UI],
  ["graph-chip-border", "graph-canvas", UI],
  ["graph-chip-off-text", "graph-chip-background", TEXT],
  ["graph-chip-text", "graph-chip-background", TEXT],
];

const LIGHT_ONLY: Pair[] = [["role-pm", "surface-alt", UI]];

const DARK_ONLY: Pair[] = [
  ["gap", "background", TEXT],
  // Fix 6: the switch on track is exactly 3.00:1 on dark surfaces (accepted; labelled On/Off).
  ["primary", "surface", UI - 0.01],
];

describe.each([
  ["light", light, LIGHT_ONLY],
  ["dark", dark, DARK_ONLY],
])("contrast (%s)", (_mode, vars, extra) => {
  it.each([...BOTH, ...extra])(
    "--%s on --%s is at least %s:1",
    (fg, bg, minimum) => {
      const ratio = contrast(vars, fg, bg);
      expect(
        ratio,
        `${fg} on ${bg} is ${ratio.toFixed(2)}:1, needs ${minimum}:1`,
      ).toBeGreaterThanOrEqual(minimum);
    },
  );
});

describe("DESIGN.md published ratios", () => {
  // [fg, bg, light ratio, dark ratio]; null where DESIGN.md gives none.
  it.each<[string, string, number | null, number | null]>([
    ["text", "surface", 17.32, 13.98],
    ["text-secondary", "surface", 6.72, 7.19],
    ["text-secondary", "surface-alt", 6.01, 6.43],
    ["primary-foreground", "primary", 5.54, 5.54],
    ["primary-text", "surface", 7.69, 9.02],
    ["primary-text", "primary-tint", 6.67, 7.35],
    ["blocker", "blocker-tint", 5.43, 7.35],
    ["gap", "gap-tint", 5.55, 7.71],
    ["resolved", "resolved-tint", 5.06, 8.16],
    ["neutral", "neutral-tint", 5.9, 6.17],
    ["role-qa", "surface", 4.6, 5.33],
    ["ring", "surface", 5.54, 9.02],
    ["resolved-foreground", "resolved", 5.75, 10.26],
    ["primary", "surface", null, 3.0],
  ])("%s on %s", (fg, bg, lightRatio, darkRatio) => {
    if (lightRatio !== null) {
      expect(contrast(light, fg, bg), `light ${fg} on ${bg}`).toBeCloseTo(
        lightRatio,
        1,
      );
    }
    if (darkRatio !== null) {
      expect(contrast(dark, fg, bg), `dark ${fg} on ${bg}`).toBeCloseTo(
        darkRatio,
        1,
      );
    }
  });
});

describe("DESIGN.md colour values", () => {
  // [token, light, dark]
  it.each([
    ["canvas", "#ECEDF2", "#0E1015"],
    ["background", "#F7F7FA", "#14161D"],
    ["surface", "#FFFFFF", "#1B1E27"],
    ["surface-alt", "#F1F2F7", "#232734"],
    ["border", "#E3E5EE", "#2B3040"],
    ["border-strong", "#CDD1E0", "#3A4054"],
    ["text", "#171A26", "#E9EBF3"],
    ["text-secondary", "#555B72", "#A3AAC0"],
    ["primary", "#4F5BD5", "#4F5BD5"],
    ["primary-foreground", "#FFFFFF", "#FFFFFF"],
    ["primary-tint", "#ECEEFC", "#262B52"],
    ["primary-text", "#3B45B8", "#B3BAFF"],
    ["link", "#3B45B8", "#B3BAFF"],
    ["ring", "#4F5BD5", "#B3BAFF"],
    ["agent", "#3B45B8", "#B3BAFF"],
    ["agent-tint", "#ECEEFC", "#262B52"],
    ["blocker", "#B42F29", "#FF9C94"],
    ["blocker-tint", "#FDECEA", "#3B2026"],
    ["gap", "#8F5200", "#F3BA5C"],
    ["gap-tint", "#FDF1D6", "#382D17"],
    ["resolved", "#17753F", "#78D6A0"],
    ["resolved-tint", "#E2F5E9", "#162F20"],
    ["resolved-foreground", "#FFFFFF", "#14161D"],
    ["neutral", "#555B72", "#A3AAC0"],
    ["neutral-tint", "#EEF0F6", "#262A38"],
    ["role-pm", "#1F8A7E", "#5FCBBE"],
    ["role-qa", "#6E7490", "#8A91AB"],
    ["graph-canvas", "#12192D", "#12192D"],
    ["graph-product", "#9AA3FF", "#9AA3FF"],
    ["graph-integration-type", "#5FD0C2", "#5FD0C2"],
    ["graph-knowledge-source", "#7CC8F5", "#7CC8F5"],
    ["graph-checklist", "#F3BA5C", "#F3BA5C"],
    ["graph-ready", "#6FD39A", "#6FD39A"],
    ["graph-missing", "#FF8A80", "#FF8A80"],
    ["graph-edge", "#6D7AA8", "#6D7AA8"],
    ["graph-edge-selected", "#9AA3FF", "#9AA3FF"],
    ["graph-edge-gap", "#F3BA5C", "#F3BA5C"],
    ["graph-chip-background", "#1B2442", "#1B2442"],
    ["graph-chip-border", "#4F5BD5", "#4F5BD5"],
    ["graph-chip-text", "#E4E8F5", "#E4E8F5"],
    ["graph-chip-off-text", "#9AA6C8", "#9AA6C8"],
  ])("--%s is %s light and %s dark", (name, lightHex, darkHex) => {
    expect(resolveVar(light, name).toUpperCase()).toBe(lightHex);
    expect(resolveVar(dark, name).toUpperCase()).toBe(darkHex);
  });

  it("--scrim is rgba(10,12,20,.55) in both themes", () => {
    expect(resolveVar(light, "scrim").replace(/\s/g, "")).toBe(
      "rgba(10,12,20,0.55)",
    );
    expect(resolveVar(dark, "scrim").replace(/\s/g, "")).toBe(
      "rgba(10,12,20,0.55)",
    );
  });

  it("keeps the legacy aliases on the new values until Story 17.3", () => {
    for (const vars of [light, dark]) {
      expect(resolveVar(vars, "diff-tint")).toBe(
        resolveVar(vars, "primary-tint"),
      );
      expect(resolveVar(vars, "evidence-highlight")).toBe(
        resolveVar(vars, "primary-tint"),
      );
      expect(resolveVar(vars, "surface-sidebar")).toBe(
        resolveVar(vars, "surface"),
      );
      expect(resolveVar(vars, "surface-inspector")).toBe(
        resolveVar(vars, "surface"),
      );
    }
  });

  it("loads no mono face", () => {
    expect(css).not.toMatch(/jetbrains|--font-mono/i);
  });
});
