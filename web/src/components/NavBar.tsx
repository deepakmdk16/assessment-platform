import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function NavBar() {
  const { user, logout } = useAuth()

  return (
    <header className="navbar">
      <Link to="/dashboard" className="navbar-brand">
        Assessment Platform
      </Link>
      {user && (
        <div className="navbar-actions">
          <span className="navbar-user">{user.name}</span>
          <button type="button" className="button-link" onClick={logout}>
            Log out
          </button>
        </div>
      )}
    </header>
  )
}
