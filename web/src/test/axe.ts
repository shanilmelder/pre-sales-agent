import axe from "axe-core";

/** WCAG 2.1 AA violations in `container` (axe-core in jsdom; colour contrast is checked
 * separately from the token values, since jsdom does no layout or painting). */
export async function axeViolations(container: Element) {
  const results = await axe.run(container, {
    runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
  });
  return results.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length} nodes)`);
}
