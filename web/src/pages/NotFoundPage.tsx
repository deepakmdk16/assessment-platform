import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="page">
      <h1>Page not found</h1>
      <Link to="/dashboard">Go to dashboard</Link>
    </div>
  )
}
