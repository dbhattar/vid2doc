export type ThemePreference = 'light' | 'dark' | 'system';

// Deliberately the SAME key and value semantics Starlight's own theme
// picker uses internally (see @astrojs/starlight/components/ThemeSelect.astro)
// -- /docs pages already ship a working light/dark/auto switcher via
// Starlight, and since this is one site/domain (not a separate app), reusing
// its storage means toggling here and toggling there stay in sync, instead
// of running two disconnected theme systems on the same origin.
export const THEME_STORAGE_KEY = 'starlight-theme';

function resolveSystemPreference(): 'light' | 'dark' {
  return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

/** Always resolves to a concrete light/dark attribute -- matches Starlight's
 * own behavior of never leaving data-theme unset, so both toggles agree on
 * what "current theme" means. */
export function applyTheme(pref: ThemePreference) {
  const resolved = pref === 'system' ? resolveSystemPreference() : pref;
  document.documentElement.dataset.theme = resolved;
}

export function loadThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // ignore, e.g. private browsing
  }
  return 'system';
}

export function saveThemePreference(pref: ThemePreference) {
  try {
    // Starlight's own storeTheme() writes '' (not absence of the key) for auto/system.
    localStorage.setItem(THEME_STORAGE_KEY, pref === 'system' ? '' : pref);
  } catch {
    // ignore, e.g. private browsing
  }
}

export function nextThemePreference(current: ThemePreference): ThemePreference {
  return current === 'system' ? 'light' : current === 'light' ? 'dark' : 'system';
}

/** Keeps data-theme correct if the OS scheme changes while the user is on
 * "system" -- Starlight registers its own equivalent listener for its
 * picker; this is this toggle's counterpart so the homepage/blog stay in
 * sync too. */
export function watchSystemPreference(onChange: () => void) {
  matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
    if (loadThemePreference() === 'system') onChange();
  });
}
