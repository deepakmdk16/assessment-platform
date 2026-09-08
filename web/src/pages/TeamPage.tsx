import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'
import { parseServerDate } from '../invites'
import type { Member, OrgInvite, Organization, OrgRole } from '../types'

function message(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback
}

/** The organisation: who is in it, what they may do, and who has been asked to
 *  join (X01).
 *
 *  Everything an interviewer authors belongs to the organisation rather than to
 *  them, so this page is where a company stops being one login. `role` decides
 *  what is rendered at all: a plain member sees the roster read-only rather than
 *  being offered controls whose click comes back 403.
 */
export function TeamPage() {
  const { user } = useAuth()
  const [org, setOrg] = useState<Organization | null>(null)
  const [members, setMembers] = useState<Member[] | null>(null)
  const [invites, setInvites] = useState<OrgInvite[]>([])
  const [error, setError] = useState<string | null>(null)
  // Reachable: an admin removed this account from its organisation. The API
  // answers 403 to every scoped route until it belongs somewhere again, so
  // the page has to offer the way out rather than just report the refusal.
  const [orphaned, setOrphaned] = useState(false)

  const isAdmin = org?.role === 'admin'
  const adminCount = (members ?? []).filter((m) => m.role === 'admin').length

  // Fetches, but doesn't write state: the mount effect wants a cancellation
  // guard around the write and the roster handlers don't, so the two callers
  // apply the result themselves rather than sharing a half-right guard.
  const fetchAll = useCallback(async () => {
    const [nextOrg, nextMembers] = await Promise.all([api.getOrg(), api.listMembers()])
    // Pending invitations are admin-only on the server; asking as a plain member
    // would only produce a 403 to swallow.
    const pending = nextOrg.role === 'admin' ? await api.listOrgInvites() : []
    return { nextOrg, nextMembers, pending }
  }, [])

  const reload = useCallback(
    () =>
      fetchAll()
        .then(({ nextOrg, nextMembers, pending }) => {
          setOrg(nextOrg)
          setMembers(nextMembers)
          setInvites(pending)
        })
        .catch((err: unknown) => {
          if (err instanceof ApiError && err.status === 403) {
            setOrphaned(true)
            setOrg(null)
            return
          }
          setError(message(err, 'Failed to load the team'))
        }),
    [fetchAll],
  )

  useEffect(() => {
    let cancelled = false
    void fetchAll()
      .then(({ nextOrg, nextMembers, pending }) => {
        if (cancelled) return
        setOrg(nextOrg)
        setMembers(nextMembers)
        setInvites(pending)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 403) setOrphaned(true)
        else setError(message(err, 'Failed to load the team'))
      })
    return () => {
      cancelled = true
    }
  }, [fetchAll])

  return (
    <div className="wizard">
      <div className="page-head">
        <div>
          <h1>Team</h1>
          <div className="sub">
            Everyone here shares one question library, one set of assessments, and every candidate
            submission.
          </div>
        </div>
      </div>

      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {orphaned && (
        <FoundOrgCard
          onFounded={() => {
            // Refetch rather than adopting the create response: the roster and
            // the (empty) invitation list have to arrive too, or the page renders
            // an organisation with nobody in it.
            setOrphaned(false)
            void reload()
          }}
        />
      )}
      {!error && !orphaned && org === null && <p className="page-loading">Loading…</p>}

      {org && (
        <>
          <h2 className="section-title">Organisation</h2>
          {isAdmin ? (
            // Keyed on the name so a reload that brings a different one reseeds
            // the field. Without it the input keeps a stale value and Save
            // silently reverts someone else's rename.
            <OrgNameCard key={org.name} org={org} onRenamed={setOrg} />
          ) : (
            <div className="card pad">
              <dl className="account-kv">
                <dt>Name</dt>
                <dd>{org.name}</dd>
                <dt>Your role</dt>
                <dd>
                  <span className="chip chip-neutral">{org.role}</span>
                </dd>
              </dl>
              <p className="draft-hint">
                Only an admin can rename the organisation or change who belongs to it.
              </p>
            </div>
          )}

          <h2 className="section-title">People</h2>
          <MemberTable
            members={members ?? []}
            isAdmin={isAdmin}
            adminCount={adminCount}
            selfId={user ? Number(user.id) : null}
            onChanged={() => void reload()}
          />

          {isAdmin && (
            <>
              <h2 className="section-title">Invite someone</h2>
              <InviteForm
                onInvited={(invite) =>
                  // The server replaces any pending invitation for the same
                  // address rather than adding one (one seat, one live link), so
                  // mirror that here — otherwise the superseded row lingers with
                  // a link that no longer works and a Revoke that 404s.
                  setInvites((prev) => [invite, ...prev.filter((i) => i.email !== invite.email)])
                }
              />

              <h2 className="section-title">Pending invitations</h2>
              <PendingInvites
                invites={invites}
                onRevoked={(id) => setInvites((prev) => prev.filter((i) => i.id !== id))}
              />
            </>
          )}
        </>
      )}
    </div>
  )
}

function FoundOrgCard({ onFounded }: { onFounded: () => void }) {
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSaving(true)
    try {
      await api.createOrg(name.trim())
      onFounded()
    } catch (err) {
      setError(message(err, 'Failed to create the organisation'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="card pad" onSubmit={(e) => void handleSubmit(e)}>
      <div className="card-title">You don&rsquo;t belong to an organisation</div>
      <p className="draft-hint">
        Someone removed this account from theirs, so there is nothing here to show you. Your login
        still works — start an organisation of your own, or wait for a new invitation.
      </p>
      <div className="stack">
        <div className="field">
          <label htmlFor="new-org-name">Organisation name</label>
          <input
            id="new-org-name"
            required
            placeholder="e.g. Acme Corp"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      <div className="card-actions">
        <button type="submit" className="btn accent" disabled={saving || !name.trim()}>
          {saving ? 'Creating…' : 'Create organisation'}
        </button>
      </div>
    </form>
  )
}

function OrgNameCard({
  org,
  onRenamed,
}: {
  org: Organization
  onRenamed: (next: Organization) => void
}) {
  const [name, setName] = useState(org.name)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    setError(null)
    setSaved(false)
    setSaving(true)
    try {
      onRenamed(await api.renameOrg(name.trim()))
      setSaved(true)
    } catch (err) {
      setError(message(err, 'Failed to rename the organisation'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card pad">
      <div className="card-title">Name</div>
      <p className="draft-hint">
        What this organisation is called on the invitations you send. Not the branding candidates
        see — that is per assessment, under Settings.
      </p>
      <div className="stack">
        <div className="field">
          <label htmlFor="org-name">Organisation name</label>
          <input
            id="org-name"
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              setSaved(false)
            }}
          />
        </div>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {saved && <p className="form-success">Saved.</p>}
      <div className="card-actions">
        <button
          type="button"
          className="btn accent"
          onClick={() => void handleSave()}
          disabled={saving || !name.trim() || name.trim() === org.name}
        >
          {saving ? 'Saving…' : 'Save name'}
        </button>
      </div>
    </div>
  )
}

function MemberTable({
  members,
  isAdmin,
  adminCount,
  selfId,
  onChanged,
}: {
  members: Member[]
  isAdmin: boolean
  adminCount: number
  /** So the roster can mark which row is you — and warn before you remove it. */
  selfId: number | null
  onChanged: () => void
}) {
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<{ id: number; message: string } | null>(null)

  async function run(id: number, action: () => Promise<unknown>, fallback: string) {
    setError(null)
    setBusyId(id)
    try {
      await action()
      onChanged()
    } catch (err) {
      setError({ id, message: message(err, fallback) })
    } finally {
      setBusyId(null)
    }
  }

  function handleRemove(member: Member) {
    const self = member.interviewer_id === selfId
    const warning = self
      ? 'Remove yourself from this organisation? You lose access to its questions, ' +
        'assessments and submissions immediately, and only an admin can invite you back.'
      : `Remove ${member.name} from this organisation? Everything they authored stays; ` +
        'they lose access until someone invites them back.'
    if (!window.confirm(warning)) return
    void run(member.interviewer_id, () => api.removeMember(member.interviewer_id), 'Failed to remove')
  }

  return (
    <div className="card">
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Person</th>
              <th>Role</th>
              <th>Joined</th>
              {isAdmin && <th />}
            </tr>
          </thead>
          <tbody>
            {members.map((member) => {
              // Demoting or removing the last admin is refused by the server; say
              // so on the control instead of letting the click fail.
              const lastAdmin = member.role === 'admin' && adminCount <= 1
              const busy = busyId === member.interviewer_id
              return (
                <tr key={member.interviewer_id}>
                  <td>
                    <div className="recip">
                      <span>{member.name}</span>
                    </div>
                    <span className="muted mono">{member.email}</span>
                  </td>
                  <td>
                    {isAdmin ? (
                      <>
                        <select
                          value={member.role}
                          disabled={lastAdmin || busy}
                          aria-label={`Role for ${member.name}`}
                          onChange={(e) =>
                            void run(
                              member.interviewer_id,
                              () =>
                                api.setMemberRole(
                                  member.interviewer_id,
                                  e.target.value as OrgRole,
                                ),
                              'Failed to change the role',
                            )
                          }
                        >
                          <option value="admin">Admin</option>
                          <option value="member">Member</option>
                        </select>
                        {lastAdmin && (
                          <p className="field-hint">
                            The only admin — promote someone else to change this.
                          </p>
                        )}
                      </>
                    ) : (
                      <span className="chip chip-neutral">{member.role}</span>
                    )}
                  </td>
                  <td>{parseServerDate(member.joined_at).toLocaleDateString()}</td>
                  {isAdmin && (
                    <td>
                      <div className="row-actions">
                        {lastAdmin ? (
                          <span className="muted">—</span>
                        ) : (
                          <button
                            type="button"
                            className="btn danger sm"
                            disabled={busy}
                            onClick={() => handleRemove(member)}
                          >
                            {busy ? 'Working…' : 'Remove'}
                          </button>
                        )}
                        {member.interviewer_id === selfId && <span className="muted">You</span>}
                        {error?.id === member.interviewer_id && (
                          <p role="alert" className="form-error">
                            {error.message}
                          </p>
                        )}
                      </div>
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function InviteForm({ onInvited }: { onInvited: (invite: OrgInvite) => void }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<OrgRole>('member')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<OrgInvite | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)
    setSending(true)
    try {
      const invite = await api.createOrgInvite(email.trim(), role)
      onInvited(invite)
      setResult(invite)
      setEmail('')
    } catch (err) {
      setError(message(err, 'Failed to send the invitation'))
    } finally {
      setSending(false)
    }
  }

  return (
    <form className="card pad" onSubmit={(e) => void handleSubmit(e)}>
      <p className="draft-hint">
        The link is addressed to one email and expires in 7 days. Anyone who joins can author
        questions and read every candidate&rsquo;s submission — only an admin can change this
        roster.
      </p>
      <div className="stack">
        <div className="grid2">
          <div className="field">
            <label htmlFor="invite-email">Email</label>
            <input
              id="invite-email"
              type="email"
              required
              placeholder="colleague@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="invite-role">Role</label>
            <select
              id="invite-role"
              value={role}
              onChange={(e) => setRole(e.target.value as OrgRole)}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
          </div>
        </div>
      </div>
      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {result &&
        (result.sent ? (
          <p className="form-success">Invitation sent to {result.email}.</p>
        ) : (
          <p role="alert" className="form-error">
            Couldn&rsquo;t email {result.email}
            {result.error ? ` — ${result.error}` : ''}. The invitation exists; copy its link below
            and send it yourself.
          </p>
        ))}
      <div className="card-actions">
        <button type="submit" className="btn accent" disabled={sending || !email.trim()}>
          {sending ? 'Sending…' : 'Send invitation'}
        </button>
      </div>
    </form>
  )
}

function PendingInvites({
  invites,
  onRevoked,
}: {
  invites: OrgInvite[]
  onRevoked: (id: number) => void
}) {
  const [busyId, setBusyId] = useState<number | null>(null)
  const [error, setError] = useState<{ id: number; message: string } | null>(null)
  const [copiedId, setCopiedId] = useState<number | null>(null)

  if (invites.length === 0) {
    return (
      <div className="card pad">
        <p className="muted">Nobody is waiting on an invitation.</p>
      </div>
    )
  }

  async function copy(invite: OrgInvite) {
    setError(null)
    try {
      await navigator.clipboard.writeText(invite.url)
      setCopiedId(invite.id)
      window.setTimeout(() => setCopiedId(null), 1500)
    } catch {
      // Clipboard access is denied outside a secure context; the link is visible
      // beside the button, so say nothing rather than raise a false alarm.
      setError({ id: invite.id, message: 'Couldn’t copy — select the link and copy it by hand.' })
    }
  }

  async function revoke(invite: OrgInvite) {
    if (!window.confirm(`Revoke the invitation to ${invite.email}? Their link stops working.`))
      return
    setError(null)
    setBusyId(invite.id)
    try {
      await api.revokeOrgInvite(invite.id)
      onRevoked(invite.id)
    } catch (err) {
      setError({ id: invite.id, message: message(err, 'Failed to revoke') })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="card">
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Expires</th>
              <th>Link</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {invites.map((invite) => (
              <tr key={invite.id}>
                <td>
                  {invite.email}
                  {!invite.sent && (
                    <p role="alert" className="form-error">
                      Couldn&rsquo;t email this one
                      {invite.error ? ` — ${invite.error}` : ''}. Copy the link and send it
                      yourself.
                    </p>
                  )}
                </td>
                <td>
                  <span className="chip chip-neutral">{invite.role}</span>
                </td>
                <td>
                  {invite.expires_at ? (
                    parseServerDate(invite.expires_at).toLocaleString()
                  ) : (
                    <span className="muted">Never</span>
                  )}
                </td>
                {/* The URL stays visible and selectable: a clipboard write can be
                    blocked, and an admin sometimes wants to paste it into chat. */}
                <td className="invite-url">
                  <div className="row-actions">
                    <span className="mono">{invite.url}</span>
                    <button type="button" className="btn sec sm" onClick={() => void copy(invite)}>
                      {copiedId === invite.id ? 'Copied!' : 'Copy link'}
                    </button>
                  </div>
                </td>
                <td>
                  <div className="row-actions">
                    <button
                      type="button"
                      className="btn danger sm"
                      disabled={busyId === invite.id}
                      onClick={() => void revoke(invite)}
                    >
                      {busyId === invite.id ? 'Revoking…' : 'Revoke'}
                    </button>
                    {error?.id === invite.id && (
                      <p role="alert" className="form-error">
                        {error.message}
                      </p>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
