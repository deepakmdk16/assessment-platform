import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { applyPref, osIsDark, readPref, storePref, type ThemePref } from './theme'

interface ThemeContextValue {
  pref: ThemePref
  /** The theme actually in effect right now (auto resolved against the OS). */
  resolved: 'light' | 'dark'
  setPref: (pref: ThemePref) => void
}

const ThemeContext = createContext<ThemeContextValue | undefined>(undefined)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [pref, setPrefState] = useState<ThemePref>(readPref)
  const [osDark, setOsDark] = useState<boolean>(osIsDark)

  // Keep the <html> attribute in sync with the preference.
  useEffect(() => {
    applyPref(pref)
  }, [pref])

  // Track the OS preference so Auto follows it live. Setting state from the
  // media-query event (not synchronously in the effect) is the intended pattern.
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => setOsDark(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  // Derived, not stored: no setState-in-effect, no drift.
  const resolved: 'light' | 'dark' = pref === 'auto' ? (osDark ? 'dark' : 'light') : pref

  const value = useMemo<ThemeContextValue>(
    () => ({
      pref,
      resolved,
      setPref: (next) => {
        storePref(next)
        setPrefState(next)
      },
    }),
    [pref, resolved],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components -- hook is colocated with its provider
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within a ThemeProvider')
  return ctx
}
