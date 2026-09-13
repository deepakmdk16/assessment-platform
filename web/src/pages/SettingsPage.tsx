import { useEffect, useId, useState } from 'react'
import { Link, Navigate, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth/AuthContext'
import { DEFAULT_SECTION, SETTINGS_SECTIONS } from '../settings-sections'

/** Settings: one route per section, with a rail to move between them (P3a).
 *
 *  The rail lists only what this person may open, which makes loading the role
 *  a four-state affair, and every shortcut through it is visible:
 *
 *  - unknown → treat as member, and an admin refreshing on /settings/privacy is
 *    bounced out before the answer arrives;
 *  - unknown → treat as admin, and the panel flashes open for someone the next
 *    tick redirects;
 *  - failed → treat as member, and one network blip silently demotes an admin
 *    for the rest of the session, `replace` taking the URL with it.
 *
 *  So an admin-only section waits while the role is loading, and says so if the
 *  load failed. Only a role actually known to be `member` redirects.
 */
export function SettingsPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const { section } = useParams<{ section: string }>()
  const selectId = useId()
  const [isAdmin, setIsAdmin] = useState<boolean | null>(null)
  const [roleFailed, setRoleFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    // The role comes from the organisation, not the login: which parts of
    // Settings exist for you is the roster's business (X01).
    void api
      .getOrg()
      .then((org) => {
        if (!cancelled) setIsAdmin(org.role === 'admin')
      })
      .catch(() => {
        // Unknown, not "member": this must not quietly cost an admin their own
        // sections, so the gated route says what happened instead of leaving.
        if (!cancelled) setRoleFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const visible = SETTINGS_SECTIONS.filter((s) => isAdmin === true || !s.admin)
  const current = SETTINGS_SECTIONS.find((s) => s.id === section)
  const gated = current?.admin === true

  if (!user) return null
  // An unknown section, or one this person is known not to have. Either way the
  // answer is the same: the first section, not a blank panel or a 403 to read.
  if (!current || (gated && isAdmin === false)) {
    return <Navigate to={`/settings/${DEFAULT_SECTION}`} replace />
  }
  // The role decides whether this section exists at all, so while it is in
  // flight there is nothing honest to draw — not even its name.
  if (gated && isAdmin === null && !roleFailed) return null

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <div className="sub">{current.sub}</div>
        </div>
      </div>

      <div className="settings-layout">
        <nav className="subnav" aria-label="Settings sections">
          {visible.map((s) => (
            <Link
              key={s.id}
              to={`/settings/${s.id}`}
              className={s.id === current.id ? 'on' : undefined}
              aria-current={s.id === current.id ? 'page' : undefined}
            >
              {s.label}
            </Link>
          ))}
        </nav>

        <div>
          {/* The rail's shape below the breakpoint: same sections, one control. */}
          <div className="subnav-select">
            <label htmlFor={selectId}>Section</label>
            <select
              id={selectId}
              value={current.id}
              onChange={(e) => navigate(`/settings/${e.target.value}`)}
            >
              {visible.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>

          <h2 className="section-title">{current.label}</h2>
          {gated && roleFailed ? (
            <p role="alert" className="form-error">
              Couldn’t check what you’re allowed to see here. Reload the page to try again.
            </p>
          ) : (
            current.panel()
          )}
        </div>
      </div>
    </>
  )
}
