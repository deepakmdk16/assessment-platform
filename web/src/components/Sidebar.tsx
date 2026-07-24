import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ThemeToggle } from './ThemeToggle'

function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .filter(Boolean)
    .slice(0, 2)
    .join('')
    .toUpperCase()
}

export function Sidebar() {
  const { user } = useAuth()
  const { pathname } = useLocation()

  const onNew = pathname === '/questions/new'
  const onQuestions = pathname === '/dashboard' || (pathname.startsWith('/questions/') && !onNew)
  const onSubmissions = pathname.startsWith('/submissions')
  const onAssessments = pathname.startsWith('/assessments')

  return (
    <aside className="sidebar">
      <Link to="/dashboard" className="brand">
        <span className="brand-mark" aria-hidden="true" />
        <span className="brand-name">assess.dev</span>
      </Link>

      <div className="nav-label">Workspace</div>
      <nav className="nav">
        <Link to="/dashboard" className={onQuestions ? 'on' : undefined}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 6h16M4 12h16M4 18h10" />
          </svg>
          Questions
        </Link>
        <Link to="/assessments" className={onAssessments ? 'on' : undefined}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M4 5h16v14H4zM4 10h16M10 10v9" />
          </svg>
          Assessments
        </Link>
        <Link to="/submissions" className={onSubmissions ? 'on' : undefined}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 5h9M9 12h9M9 19h9M4 5h.01M4 12h.01M4 19h.01" />
          </svg>
          Submissions
        </Link>
        <Link to="/questions/new" className={onNew ? 'on' : undefined}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New question
        </Link>
      </nav>

      <div className="side-foot">
        <ThemeToggle />
        {user && (
          <div className="side-id">
            <span className="avatar" aria-hidden="true">
              {initials(user.name)}
            </span>
            <span className="side-who">
              {user.name}
              <br />
              <small>Interviewer</small>
            </span>
          </div>
        )}
      </div>
    </aside>
  )
}
