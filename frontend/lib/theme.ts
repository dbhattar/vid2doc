export type ThemePreference = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "framewrite:theme";

export function applyTheme(pref: ThemePreference) {
  if (pref === "system") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", pref);
  }
}

export function loadThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // ignore, e.g. private browsing
  }
  return "system";
}

export function saveThemePreference(pref: ThemePreference) {
  try {
    if (pref === "system") {
      localStorage.removeItem(THEME_STORAGE_KEY);
    } else {
      localStorage.setItem(THEME_STORAGE_KEY, pref);
    }
  } catch {
    // ignore, e.g. private browsing
  }
}

export function nextThemePreference(current: ThemePreference): ThemePreference {
  return current === "system" ? "light" : current === "light" ? "dark" : "system";
}

/** Inlined as a `beforeInteractive` script in the root layout -- must stay a
 * self-contained string with no imports, since it runs before any app code,
 * purely to set `data-theme` before first paint and avoid a flash of the
 * wrong theme. Keep in sync with the functions above if the storage key or
 * logic ever changes. */
export const THEME_INIT_SCRIPT = `
(function () {
  try {
    var stored = localStorage.getItem('${THEME_STORAGE_KEY}');
    if (stored === 'light' || stored === 'dark') {
      document.documentElement.setAttribute('data-theme', stored);
    }
  } catch (e) {}
})();
`;
