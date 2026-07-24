import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { useAuth } from '../auth/AuthContext'

function crumbFor(pathname: string): string {
  if (pathname === '/dashboard') return 'Questions'
  if (pathname === '/questions/new') return 'New question'
  if (pathname.startsWith('/questions/')) return 'Question'
  if (pathname === '/assessments/new') return 'New assessment'
  if (pathname === '/assessments') return 'Assessments'
  if (pathname.startsWith('/assessments/')) return 'Assessment'
  return ''
}

export function AppLayout({ children }: { children: ReactNode }) {
  const { logout } = useAuth()
  const { pathname } = useLocation()

  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <header className="topbar">
          <div className="crumb">
            Workspace <span>/</span> <b>{crumbFor(pathname)}</b>
          </div>
          <div className="topbar-user">
            <button type="button" className="btn ghost sm" onClick={logout}>
              Log out
            </button>
          </div>
        </header>
        <div className="content">{children}</div>
      </div>
    </div>
  )
}
