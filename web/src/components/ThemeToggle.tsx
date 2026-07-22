import type { ReactNode } from 'react'
import { useTheme } from '../theme/ThemeContext'
import type { ThemePref } from '../theme/theme'

const SUN = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19" />
  </svg>
)
const MOON = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" />
  </svg>
)
const AUTO = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M8 20h8M12 16v4" />
  </svg>
)

const OPTIONS: { value: ThemePref; label: string; icon: ReactNode }[] = [
  { value: 'light', label: 'Light', icon: SUN },
  { value: 'dark', label: 'Dark', icon: MOON },
  { value: 'auto', label: 'Auto', icon: AUTO },
]

const ICON: Record<ThemePref, ReactNode> = { light: SUN, dark: MOON, auto: AUTO }
const CYCLE: ThemePref[] = ['auto', 'light', 'dark']

/** Single icon button that cycles auto → light → dark. For surfaces without a
 *  sidebar (the candidate assessment header). */
export function ThemeCycleButton() {
  const { pref, setPref } = useTheme()
  const next = CYCLE[(CYCLE.indexOf(pref) + 1) % CYCLE.length]
  return (
    <button
      type="button"
      className="icon-btn"
      title={`Theme: ${pref} — switch to ${next}`}
      aria-label={`Theme: ${pref}. Switch to ${next}.`}
      onClick={() => setPref(next)}
    >
      {ICON[pref]}
    </button>
  )
}

/** Segmented Light / Dark / Auto control for the sidebar footer. */
export function ThemeToggle() {
  const { pref, setPref } = useTheme()
  return (
    <div className="theme-seg" role="group" aria-label="Theme">
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          className={pref === o.value ? 'on' : undefined}
          aria-pressed={pref === o.value}
          title={`${o.label} theme`}
          onClick={() => setPref(o.value)}
        >
          {o.icon}
          {o.label}
        </button>
      ))}
    </div>
  )
}
