import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'
import { parseServerDate } from '../invites'
import type { Billing, PaidPlanKey, Plan } from '../types'

/** Where a meter turns from reassuring to worth acting on. Under the first it
 *  is green, between the two amber, at or over the limit red — the app's
 *  existing semantic tokens, no new colours. */
const PRESSURE_WARN = 0.8

function meterClass(used: number, limit: number): string {
  const ratio = limit > 0 ? used / limit : 1
  if (ratio >= 1) return 'bad'
  if (ratio >= PRESSURE_WARN) return 'warn'
  return ''
}

function periodLabel(period: string): string {
  // "YYYY-MM" — parsed as UTC so the month name can't slip a day either way.
  const [year, month] = period.split('-').map(Number)
  if (!year || !month) return period
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString(undefined, {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

function dateLabel(iso: string): string {
  // Via parseServerDate: every timestamp column is timezone-naive (P14), so the
  // API serialises UTC with no offset and a bare `new Date` would read it as
  // local — showing the renewal a day early for anyone east of UTC.
  return parseServerDate(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

function money(usd: number): string {
  return `$${usd.toFixed(2)}`
}

/** What the month actually allows: the plan's entitlement less what the last
 *  one overran by. Mirrors `billing.allowance` on the server, including its
 *  floor at zero — a debt bigger than a month's allowance stops that month
 *  rather than compounding into the next. */
function allowanceOf(planLimit: number, carried: number): number {
  return Math.max(0, planLimit - carried)
}

function UsageRow({
  name,
  hint,
  used,
  limit,
  carried = 0,
  over,
}: {
  name: string
  hint?: string
  used: number
  limit: number
  /** What last period overran by, already subtracted from `limit`. Named here
   *  so a month that starts with less than the plan's headline number says why
   *  rather than looking like a mistake. */
  carried?: number
  /** What this period has gone past its allowance by. Passed in from what the
   *  server recorded at the time for the two metered allowances; seats have no
   *  such record — they are a live headcount — so that row derives it. */
  over?: number
}) {
  const width = limit > 0 ? Math.min(100, (used / limit) * 100) : 100
  const overBy = over ?? used - limit
  return (
    <div className="usage-row">
      <div className="usage-name">
        {name}
        {carried > 0 ? (
          <small>{carried} carried over from last month</small>
        ) : overBy > 0 ? (
          <small>{overBy} over the plan</small>
        ) : (
          hint && <small>{hint}</small>
        )}
      </div>
      <svg className="usage-meter" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">
        <rect className="meter-track" x={0} y={0} width={100} height={6} rx={3} />
        <rect
          className={`meter-fill ${meterClass(used, limit)}`}
          x={0}
          y={0}
          width={width}
          height={6}
          rx={3}
        />
      </svg>
      <div className="usage-val">
        {used} <em>/ {limit}</em>
      </div>
    </div>
  )
}

function PlanCard({
  plan,
  current,
  onChoose,
  busy,
}: {
  plan: Plan
  current: boolean
  onChoose: (key: PaidPlanKey) => void
  busy: boolean
}) {
  return (
    <div className={current ? 'plan-card current' : 'plan-card'}>
      <h4>
        {plan.label}
        {current && <span className="chip chip-neutral">Current</span>}
      </h4>
      <div className="plan-amount">
        ${plan.price_usd_month}
        <small> / mo</small>
      </div>
      <ul className="plan-limits">
        <li>
          <b>{plan.sittings}</b> sittings
        </li>
        <li>
          <b>{plan.drafts}</b> AI drafts
        </li>
        <li>
          <b>{plan.seats}</b> seats
        </li>
      </ul>
      {current ? (
        <button type="button" className="btn sec" disabled>
          Your plan
        </button>
      ) : (
        <button
          type="button"
          className={plan.key === 'growth' ? 'btn accent' : 'btn sec'}
          disabled={busy}
          onClick={() => onChoose(plan.key as PaidPlanKey)}
        >
          Choose {plan.label}
        </button>
      )}
    </div>
  )
}

/** Plan, allowances and spend for the organisation (X02).
 *
 *  Readable by every member — usage is the explanation for a refused invite,
 *  and withholding it from the person who hit the limit turns a clear 402 into
 *  a mystery. Only an admin is offered the buttons that spend money, and only
 *  when the deployment can actually take a payment: an upgrade button that
 *  leads to a 503 is worse than no button.
 */
export function BillingPanel() {
  const [billing, setBilling] = useState<Billing | null>(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    // The role comes from the organisation, not the login: /billing is about the
    // tenant's plan, and who may change it is the roster's business (X01).
    void Promise.all([api.getBilling(), api.getOrg()])
      .then(([nextBilling, org]) => {
        if (cancelled) return
        setBilling(nextBilling)
        setIsAdmin(org.role === 'admin')
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : 'Failed to load billing')
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Stripe hosts both pages, so leaving this origin IS the flow — the browser
  // comes back to /settings with the subscription already reported by webhook.
  async function leaveFor(get: () => Promise<{ url: string }>) {
    setError(null)
    setBusy(true)
    try {
      const { url } = await get()
      window.location.assign(url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach the payment page')
      setBusy(false)
    }
  }

  if (error && !billing) {
    return (
      <div className="card pad">
        <p role="alert" className="form-error">
          {error}
        </p>
      </div>
    )
  }
  if (!billing) return <div className="card pad muted">Loading…</div>

  const { plan, usage, status, plans, payments_enabled: payments } = billing
  const onFree = plan.key === 'free'
  const pastDue = status === 'past_due'
  const canPay = isAdmin && payments

  return (
    <>
      {pastDue && (
        <div className="form-warning" role="status">
          <p>
            <b>We couldn&rsquo;t take the last payment.</b> Your {plan.label} plan is still
            running while the card is retried.
            {canPay && ' Update it in the payment portal to avoid dropping back to Free.'}
          </p>
        </div>
      )}

      <div className="card pad">
        <div className="plan-head">
          <div>
            <div className="plan-name">
              <strong>{plan.label}</strong>
              {pastDue ? (
                <span className="chip chip-warn">Payment failed</span>
              ) : onFree ? (
                <span className="chip chip-neutral">Current plan</span>
              ) : (
                <span className="chip chip-good">Active</span>
              )}
            </div>
            <div className="plan-price">${plan.price_usd_month} / month</div>
          </div>
          {canPay && !onFree && (
            <button
              type="button"
              className={pastDue ? 'btn accent' : 'btn sec'}
              disabled={busy}
              onClick={() => void leaveFor(api.openBillingPortal)}
            >
              {pastDue ? 'Update payment method' : 'Manage subscription'}
            </button>
          )}
        </div>
        <div className="plan-renewal">
          {billing.current_period_end
            ? `Renews ${dateLabel(billing.current_period_end)}. Change plan, update the card or cancel in the payment portal.`
            : 'No card on file. Limits reset on the 1st of each month.'}
          {!billing.enforced && ' Limits are being measured, not enforced, on this deployment.'}
        </div>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
      </div>

      <div className="card pad">
        <div className="card-title">{periodLabel(usage.period)}</div>
        <p className="draft-hint">
          What this organisation has used this month. Everyone on the team can see it &mdash; it
          is the explanation for a refused invite.
        </p>
        <div className="usage">
          <UsageRow
            name="Candidate sittings"
            hint="one candidate opening one invite"
            used={usage.sittings}
            limit={allowanceOf(plan.sittings, usage.sittings_carried)}
            carried={usage.sittings_carried}
            over={usage.sittings_over}
          />
          <UsageRow
            name="AI question drafts"
            hint="a variant set of 3 costs 3"
            used={usage.drafts}
            limit={allowanceOf(plan.drafts, usage.drafts_carried)}
            carried={usage.drafts_carried}
            over={usage.drafts_over}
          />
          <UsageRow
            name="Seats"
            hint="members plus open invitations"
            used={usage.seats}
            limit={plan.seats}
          />
        </div>
      </div>

      <div className="card pad">
        <div className="card-title">AI spend this month</div>
        <p className="draft-hint">
          What the grader and the authoring assistant actually cost, rolled up from the figures
          the agent reports per job. Visibility only &mdash; it is not billed on.
        </p>
        <dl className="cost">
          <dt>Grading (judge)</dt>
          <dd>{money(usage.judge_cost_usd)}</dd>
          <dt>Question authoring</dt>
          <dd>{money(usage.draft_cost_usd)}</dd>
          <dt className="cost-total">Total</dt>
          <dd className="cost-total">{money(usage.judge_cost_usd + usage.draft_cost_usd)}</dd>
        </dl>
      </div>

      {/* Only on free: once subscribed, changing plan is the portal's job, which
          already prorates and invoices properly. */}
      {onFree && canPay && (
        <>
          <h2 className="section-title">Choose a plan</h2>
          <div className="plans">
            {plans.map((p) => (
              <PlanCard
                key={p.key}
                plan={p}
                current={p.key === plan.key}
                onChoose={(key) => void leaveFor(() => api.startCheckout(key))}
                busy={busy}
              />
            ))}
          </div>
        </>
      )}
    </>
  )
}
