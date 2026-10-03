// No-flash theme. The server renders `<html data-theme>` from the preferences cookie and
// adds `.dark` only for an explicit Dark choice; it can't know the OS theme. This inline
// script runs in <head> before first paint and keeps `.dark` in step with the chosen theme
// (Dark: on; Light: off; System: `prefers-color-scheme`):
// - on load (synchronously, so the first paint is already right);
// - on OS theme changes (media query listener);
// - when React re-renders <html> after a Settings change (MutationObserver callbacks run
//   as microtasks, before the next paint). React may reset `className` to the server value
//   (no `.dark` for System), or leave it untouched when the server value is unchanged
//   (System -> Light keeps a script-added `.dark`), so the script owns the final state.

export const THEME_SCRIPT = `(function () {
  try {
    var root = document.documentElement;
    var media = window.matchMedia("(prefers-color-scheme: dark)");
    var apply = function () {
      var theme = root.getAttribute("data-theme");
      var want = theme === "dark" || (theme === "system" && media.matches);
      if (root.classList.contains("dark") !== want) root.classList.toggle("dark", want);
    };
    apply();
    media.addEventListener("change", apply);
    new MutationObserver(apply).observe(root, {
      attributes: true,
      attributeFilter: ["class", "data-theme"],
    });
  } catch (e) {}
})();`;

export function ThemeScript() {
  return <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />;
}
