// WCAG 2.1 contrast of the design tokens, read straight from globals.css so a token edit
// that breaks AA fails CI and names the pair.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Not inlined into `new URL(..., import.meta.url)`: Vite rewrites that pattern to a served
// asset URL (http://localhost:3000/...), which fs cannot read.
const testFile = import.meta.url;
const css = readFileSync(fileURLToPath(new URL("../app/globals.css", testFile)), "utf8");

function block(selector: string): Record<string, string> {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`(?:^|\\n)${escaped}\\s*\\{([^}]*)\\}`));
  if (!match) throw new Error(`No ${selector} block in globals.css`);
  const vars: Record<string, string> = {};
  for (const [, name, value] of match[1].matchAll(/--([\w-]+)\s*:\s*([^;]+);/g)) {
    vars[name] = value.trim();
  }
  return vars;
}

const light = block(":root");
const dark = { ...light, ...block(".dark") };

type Rgb = [number, number, number]; // linear sRGB, 0..1

function srgbToLinear(channel: number): number {
  return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
}

function hexToLinear(hex: string): Rgb {
  const h = hex.slice(1);
  const full = h.length === 3 ? [...h].map((c) => c + c).join("") : h;
  return [0, 2, 4].map((i) => srgbToLinear(parseInt(full.slice(i, i + 2), 16) / 255)) as Rgb;
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

function resolveVar(vars: Record<string, string>, name: string, seen = new Set<string>()): string {
  const value = vars[name];
  if (value === undefined) throw new Error(`--${name} is not defined`);
  const ref = value.match(/^var\(--([\w-]+)\)$/);
  if (!ref) return value;
  if (seen.has(name)) throw new Error(`Circular --${name}`);
  seen.add(name);
  return resolveVar(vars, ref[1], seen);
}

function luminance(vars: Record<string, string>, name: string): number {
  const value = resolveVar(vars, name);
  const [r, g, b] = value.startsWith("#") ? hexToLinear(value) : oklchToLinear(value);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(vars: Record<string, string>, fg: string, bg: string): number {
  const [hi, lo] = [luminance(vars, fg), luminance(vars, bg)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const TEXT = 4.5; // body text
const UI = 3; // icons, bars, dots, focus accents and large text

const SURFACES = ["background", "card", "surface-sidebar", "surface-inspector"];

// [foreground token, surface token, minimum ratio]
const PAIRS: [string, string, number][] = [
  ["primary-foreground", "primary", TEXT],
  // Primary links/active nav and the semantic text+icon labels, on every pane surface.
  ...["primary", "blocker", "gap", "resolved"].flatMap((fg) =>
    SURFACES.map((bg): [string, string, number] => [fg, bg, TEXT]),
  ),
  // The agent-running dot is non-text UI.
  ...SURFACES.map((bg): [string, string, number] => ["agent", bg, UI]),
  // Body text on every surface and tint.
  ...[...SURFACES, "diff-tint", "blocker-tint"].map((bg): [string, string, number] => [
    "foreground",
    bg,
    TEXT,
  ]),
  // Blocker row: blocker red is never text on blocker-tint, only the 2px bar or an icon.
  ["blocker", "blocker-tint", UI],
  // Conflict proposal: primary top border.
  ["primary", "diff-tint", UI],
  // Muted (meta) text on every surface and tint.
  ...[...SURFACES, "diff-tint", "blocker-tint"].map((bg): [string, string, number] => [
    "muted-foreground",
    bg,
    TEXT,
  ]),
  // Destructive text (shadcn destructive buttons and error messages).
  ...["background", "card", "surface-inspector"].map((bg): [string, string, number] => [
    "destructive",
    bg,
    TEXT,
  ]),
  ["sidebar-foreground", "sidebar", TEXT],
  ["sidebar-primary-foreground", "sidebar-primary", TEXT],
];

describe.each([
  ["light", light],
  ["dark", dark],
])("contrast (%s)", (_mode, vars) => {
  it.each(PAIRS)("--%s on --%s is at least %s:1", (fg, bg, minimum) => {
    const ratio = contrast(vars, fg, bg);
    expect(
      ratio,
      `--${fg} on --${bg} is ${ratio.toFixed(2)}:1, needs ${minimum}:1`,
    ).toBeGreaterThanOrEqual(minimum);
  });
});

describe("DESIGN.md colour values", () => {
  it.each([
    ["primary", "#4F5BD5", "#7C86E8"],
    ["primary-foreground", "#FFFFFF", "#0E1030"],
    ["blocker", "#DC2626", "#F87171"],
    ["gap", "#B45309", "#FBBF24"],
    ["resolved", "#15803D", "#4ADE80"],
    ["agent", "#4F5BD5", "#7C86E8"],
    ["diff-tint", "#EEF0FC", "#1E2140"],
    ["blocker-tint", "#FEF2F2", "#2A1414"],
    ["surface-sidebar", "#F7F7F8", "#111113"],
    ["surface-inspector", "#FBFBFC", "#16161A"],
  ])("--%s is %s light and %s dark", (name, lightHex, darkHex) => {
    expect(resolveVar(light, name).toUpperCase()).toBe(lightHex);
    expect(resolveVar(dark, name).toUpperCase()).toBe(darkHex);
  });

  it("matches the published light-mode ratios on white and the sidebar", () => {
    // DESIGN.md: primary 5.5/5.2, blocker 4.8/4.5, gap 5.0/4.7, resolved 5.0/4.7.
    const round = (x: number) => Math.round(x * 10) / 10;
    expect(round(contrast(light, "primary", "background"))).toBe(5.5);
    expect(round(contrast(light, "primary", "surface-sidebar"))).toBe(5.2);
    expect(round(contrast(light, "blocker", "background"))).toBe(4.8);
    expect(round(contrast(light, "blocker", "surface-sidebar"))).toBe(4.5);
    expect(round(contrast(light, "gap", "background"))).toBe(5.0);
    expect(round(contrast(light, "gap", "surface-sidebar"))).toBe(4.7);
    expect(round(contrast(light, "resolved", "background"))).toBe(5.0);
    expect(round(contrast(light, "resolved", "surface-sidebar"))).toBe(4.7);
  });
});
