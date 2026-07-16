import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="auth">
      <div className="auth-card notice-card">
        <h1>Page not found</h1>
        <p className="auth-alt">
          <Link to="/dashboard">Go to dashboard</Link>
        </p>
      </div>
    </div>
  )
}
