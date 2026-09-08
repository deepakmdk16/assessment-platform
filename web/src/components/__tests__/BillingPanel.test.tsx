import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BillingPanel } from '../BillingPanel'
import { api } from '../../api'
import type { Billing, Organization, Plan } from '../../types'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: { getBilling: vi.fn(), getOrg: vi.fn(), startCheckout: vi.fn(), openBillingPortal: vi.fn() },
    ApiError,
  }
})

const assign = vi.fn()

const PLANS: Plan[] = [
  { key: 'free', label: 'Free', price_usd_month: 0, sittings: 10, drafts: 5, seats: 2 },
  { key: 'starter', label: 'Starter', price_usd_month: 49, sittings: 100, drafts: 50, seats: 5 },
  { key: 'growth', label: 'Growth', price_usd_month: 199, sittings: 500, drafts: 250, seats: 20 },
]

function billing(over: Partial<Billing> = {}): Billing {
  return {
    plan: PLANS[0],
    status: 'active',
    usage: {
      period: '2026-09',
      sittings: 7,
      drafts: 2,
      seats: 1,
      sittings_carried: 0,
      drafts_carried: 0,
      judge_cost_usd: 3.81,
      draft_cost_usd: 0.94,
    },
    current_period_end: null,
    enforced: true,
    payments_enabled: true,
    plans: PLANS,
    ...over,
  }
}

function org(role: 'admin' | 'member'): Organization {
  return { id: 1, name: 'Acme', role, member_count: 1 }
}

function mount(over: Partial<Billing> = {}, role: 'admin' | 'member' = 'admin') {
  vi.mocked(api.getBilling).mockResolvedValue(billing(over))
  vi.mocked(api.getOrg).mockResolvedValue(org(role))
  return render(<BillingPanel />)
}

describe('BillingPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign },
      writable: true,
    })
  })

  it('shows the plan, the month and what it has cost', async () => {
    mount()

    // "Free" appears twice on this state — as the plan in force and as a card in
    // the chooser — so the current plan is identified by its price line.
    expect(await screen.findByText('$0 / month')).toBeInTheDocument()
    expect(screen.getByText('Current plan')).toBeInTheDocument()
    expect(screen.getByText('September 2026')).toBeInTheDocument()
    expect(screen.getByText('/ 10')).toBeInTheDocument()
    // Grading + authoring, and their total.
    expect(screen.getByText('$3.81')).toBeInTheDocument()
    expect(screen.getByText('$0.94')).toBeInTheDocument()
    expect(screen.getByText('$4.75')).toBeInTheDocument()
  })

  it('offers a plain member no way to spend the organisation money', async () => {
    mount({}, 'member')

    // The usage they need to understand a refused invite is still there...
    expect(await screen.findByText('September 2026')).toBeInTheDocument()
    // ...but nothing that would come back 403.
    expect(screen.queryByRole('button', { name: /choose/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /manage subscription/i })).not.toBeInTheDocument()
  })

  it('hides the buttons entirely when the deployment cannot take a payment', async () => {
    mount({ payments_enabled: false })

    expect(await screen.findByText('Free')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /choose/i })).not.toBeInTheDocument()
  })

  it('sends an admin to Stripe to subscribe', async () => {
    const user = userEvent.setup()
    vi.mocked(api.startCheckout).mockResolvedValue({ url: 'https://checkout.stripe.test/s' })
    mount()

    await user.click(await screen.findByRole('button', { name: /choose growth/i }))

    await waitFor(() => expect(api.startCheckout).toHaveBeenCalledWith('growth'))
    expect(assign).toHaveBeenCalledWith('https://checkout.stripe.test/s')
  })

  it('offers the portal once subscribed, and stops offering plans', async () => {
    const user = userEvent.setup()
    vi.mocked(api.openBillingPortal).mockResolvedValue({ url: 'https://portal.stripe.test/p' })
    mount({ plan: PLANS[2], current_period_end: '2026-10-15T00:00:00Z' })

    expect(await screen.findByText('Active')).toBeInTheDocument()
    // Changing plan is the portal's job — it prorates and invoices properly.
    expect(screen.queryByRole('button', { name: /choose/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /manage subscription/i }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://portal.stripe.test/p'))
  })

  it('says the card failed without pretending the plan has gone', async () => {
    mount({ plan: PLANS[2], status: 'past_due' })

    expect(await screen.findByRole('status')).toHaveTextContent(/couldn’t take the last payment/i)
    expect(screen.getByText('Payment failed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /update payment method/i })).toBeInTheDocument()
  })

  it('says why a month starts with less than the plan says', async () => {
    // A downgrade mid-month leaves the previous one over its allowance; the
    // debt is settled here rather than forgiven, so the number has to explain
    // itself or it reads as a bug.
    mount({
      usage: {
        period: '2026-09',
        sittings: 4,
        drafts: 0,
        seats: 1,
        sittings_carried: 3,
        drafts_carried: 0,
        judge_cost_usd: 0,
        draft_cost_usd: 0,
      },
    })

    expect(await screen.findByText('/ 7')).toBeInTheDocument() // 10 - 3
    expect(screen.getByText('3 carried over from last month')).toBeInTheDocument()
  })

  it('says plainly when the roster is over the seat cap', async () => {
    // Two people accepting the last seat at once can both get in; the answer is
    // to show it, not to throw one of them out afterwards.
    mount({
      usage: {
        period: '2026-09',
        sittings: 0,
        drafts: 0,
        seats: 3,
        sittings_carried: 0,
        drafts_carried: 0,
        judge_cost_usd: 0,
        draft_cost_usd: 0,
      },
    })

    expect(await screen.findByText('1 over the plan')).toBeInTheDocument()
  })

  it('says so when limits are measured but not enforced', async () => {
    mount({ enforced: false })

    expect(await screen.findByText(/measured, not enforced/i)).toBeInTheDocument()
  })

  it('reports a failure to load rather than rendering an empty plan', async () => {
    vi.mocked(api.getBilling).mockRejectedValue(new Error('offline'))
    vi.mocked(api.getOrg).mockResolvedValue(org('admin'))
    render(<BillingPanel />)

    expect(await screen.findByRole('alert')).toHaveTextContent(/failed to load billing/i)
  })
})
