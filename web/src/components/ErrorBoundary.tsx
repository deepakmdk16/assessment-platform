import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
  /** Shown instead of the default app card when this subtree throws (e.g. the
   *  candidate IDE passes its own reassuring fallback). */
  fallback?: ReactNode
}

interface State {
  error: Error | null
}

/** Catches render throws in its subtree so an unexpected error (Monaco failing
 *  to load, an unforeseen `full_result` shape) shows a fallback instead of a
 *  blank white page. Error boundaries must be class components. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // No logging backend yet; surface it to the console so it isn't swallowed.
    console.error('Unhandled render error:', error, info.componentStack)
  }

  render(): ReactNode {
    if (this.state.error === null) return this.props.children
    if (this.props.fallback !== undefined) return this.props.fallback
    return <AppErrorFallback error={this.state.error} />
  }
}

function WarningIcon() {
  return (
    <div className="boundary-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
      </svg>
    </div>
  )
}

function AppErrorFallback({ error }: { error: Error }) {
  return (
    <div className="boundary">
      <WarningIcon />
      <h2>This page hit an unexpected error</h2>
      <p>
        Something went wrong while rendering. Your saved questions and submissions are unaffected —
        this is only a display problem.
      </p>
      <div className="boundary-actions">
        <button type="button" className="btn accent" onClick={() => window.location.reload()}>
          Reload page
        </button>
        <a className="btn sec" href="/dashboard">
          Back to dashboard
        </a>
      </div>
      {import.meta.env.DEV && (
        <details className="boundary-detail">
          <summary>Technical details (dev only)</summary>
          <pre className="code">{error.stack ?? error.message}</pre>
        </details>
      )}
    </div>
  )
}

/** Fallback for the candidate IDE — the worst place to white-screen. The copy is
 *  deliberately honest: a boundary can't recover the editor's unsaved buffer, so
 *  it distinguishes "already submitted" from "not yet" and reassures on time. */
export function CandidateErrorFallback() {
  return (
    <div className="boundary">
      <WarningIcon />
      <h2>Something went wrong on this page</h2>
      <p>
        Reload to get back to your assessment. If you’d already pressed Submit, your solution was
        received. If not, reload and continue — your remaining time is unaffected.
      </p>
      <div className="boundary-actions">
        <button type="button" className="btn accent" onClick={() => window.location.reload()}>
          Reload &amp; continue
        </button>
      </div>
    </div>
  )
}
