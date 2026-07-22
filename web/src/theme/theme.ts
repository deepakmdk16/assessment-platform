/** Theme preference plumbing (no React), shared by ThemeContext and main.tsx.
 *  light / dark = pinned; auto = follow the OS (prefers-color-scheme). */
export type ThemePref = 'light' | 'dark' | 'auto'

const STORAGE_KEY = 'assessment-theme'

export function readPref(): ThemePref {
  const v = localStorage.getItem(STORAGE_KEY)
  return v === 'light' || v === 'dark' || v === 'auto' ? v : 'auto'
}

export function storePref(pref: ThemePref): void {
  localStorage.setItem(STORAGE_KEY, pref)
}

/** Stamp (or clear) data-theme on <html>. Auto clears it so the media query in
 *  tokens.css governs; light/dark pin it, overriding the media query. */
export function applyPref(pref: ThemePref): void {
  const root = document.documentElement
  if (pref === 'auto') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', pref)
}

export function osIsDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** Apply the persisted preference before React renders, so there's no flash of
 *  the wrong theme on load. Called once from main.tsx. */
export function initTheme(): void {
  applyPref(readPref())
}

/** Monaco's theme name for a resolved app theme. */
export function monacoTheme(resolved: 'light' | 'dark'): 'vs' | 'vs-dark' {
  return resolved === 'dark' ? 'vs-dark' : 'vs'
}
