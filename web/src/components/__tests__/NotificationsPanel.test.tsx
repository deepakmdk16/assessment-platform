import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NotificationsPanel } from '../NotificationsPanel'
import { api } from '../../api'
import type { Organization } from '../../types'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { api: { getOrg: vi.fn(), setResultsWebhook: vi.fn() }, ApiError }
})

const URL = 'https://acme.example.com/hooks/assessments'

function org(over: Partial<Organization> = {}): Organization {
  return {
    id: 1, name: 'Acme', role: 'admin', member_count: 2, retention_days: null,
    results_webhook_url: null, results_webhook_secret: null,
    ...over,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getOrg).mockResolvedValue(org())
  vi.mocked(api.setResultsWebhook).mockResolvedValue(org())
})

async function loaded() {
  render(<NotificationsPanel />)
  await screen.findByText('Send results to another system')
}

describe('who can see it', () => {
  it('renders nothing at all for a plain member', async () => {
    vi.mocked(api.getOrg).mockResolvedValue(org({ role: 'member' }))
    const { container } = render(<NotificationsPanel />)
    await waitFor(() => expect(container.textContent).not.toContain('Loading'))
    // Not even the heading: a member reading a setting they cannot change reads
    // it as an invitation to ask.
    expect(container).toBeEmptyDOMElement()
  })
})

describe('nothing configured', () => {
  it('offers an empty address field and no way to stop', async () => {
    await loaded()
    expect(screen.getByLabelText('Where should we post results?')).toHaveValue('')
    expect(screen.queryByRole('button', { name: 'Stop sending' })).toBeNull()
    // The payload contract is documentation for a decision nobody has made yet.
    expect(screen.queryByText('What we send')).toBeNull()
  })

  it('refuses to save an empty address instead of sending one', async () => {
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Enter the address/)
    expect(api.setResultsWebhook).not.toHaveBeenCalled()
  })
})

describe('saving', () => {
  it('shows the minted secret once, with the warning that it will not return', async () => {
    vi.mocked(api.setResultsWebhook).mockResolvedValue(
      org({ results_webhook_url: URL, results_webhook_secret: 'kR3vN8pQ2mX7' }),
    )
    await loaded()
    await userEvent.type(screen.getByLabelText('Where should we post results?'), URL)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('kR3vN8pQ2mX7')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/won’t show it again/)
    expect(api.setResultsWebhook).toHaveBeenCalledWith(URL)
  })

  it('keeps a just-minted secret on screen when Save is pressed again', async () => {
    // The second save mints nothing (the URL is unchanged), so the response
    // carries no secret — but the one already shown is still the live key, and
    // wiping it would cost a rotation that breaks the configured receiver.
    vi.mocked(api.setResultsWebhook)
      .mockResolvedValueOnce(org({ results_webhook_url: URL, results_webhook_secret: 'kR3vN8pQ2mX7' }))
      .mockResolvedValueOnce(org({ results_webhook_url: URL }))
    await loaded()
    await userEvent.type(screen.getByLabelText('Where should we post results?'), URL)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByText('kR3vN8pQ2mX7')

    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.setResultsWebhook).toHaveBeenCalledTimes(2))
    expect(screen.getByText('kR3vN8pQ2mX7')).toBeInTheDocument()
  })

  it('surfaces the server’s reason when the address is refused', async () => {
    const { ApiError } = await import('../../api')
    vi.mocked(api.setResultsWebhook).mockRejectedValue(
      new ApiError(422, "10.0.0.5 isn't reachable on the public internet."),
    )
    await loaded()
    await userEvent.type(screen.getByLabelText('Where should we post results?'), 'https://10.0.0.5/h')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/reachable on the public internet/)
  })

  it('trims the address before sending it', async () => {
    await loaded()
    await userEvent.type(screen.getByLabelText('Where should we post results?'), `  ${URL}  `)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(api.setResultsWebhook).toHaveBeenCalledWith(URL))
  })
})

describe('already configured', () => {
  beforeEach(() => {
    vi.mocked(api.getOrg).mockResolvedValue(org({ results_webhook_url: URL }))
  })

  it('reports the secret as set without ever showing it', async () => {
    await loaded()
    expect(screen.getByLabelText('Where should we post results?')).toHaveValue(URL)
    expect(screen.getByText(/Set — hidden since you saved it/)).toBeInTheDocument()
    // The rotate path is stated rather than hidden behind a separate control.
    expect(screen.getByText(/Stop sending, then save the address again/)).toBeInTheDocument()
  })

  it('shows what gets posted, for whoever wires up the endpoint', async () => {
    await loaded()
    expect(screen.getByText('What we send')).toBeInTheDocument()
    expect(screen.getByText(/"event": "results.ready"/)).toBeInTheDocument()
  })

  it('re-saving an unchanged address reveals no new secret', async () => {
    // The server deliberately does not rotate here, so the panel must not
    // pretend a key was issued.
    vi.mocked(api.setResultsWebhook).mockResolvedValue(org({ results_webhook_url: URL }))
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Saved. Results will be posted from now on.')).toBeInTheDocument()
    expect(screen.getByText(/Set — hidden since you saved it/)).toBeInTheDocument()
  })

  it('stopping clears the address and the panel goes back to unconfigured', async () => {
    vi.mocked(api.setResultsWebhook).mockResolvedValue(org())
    await loaded()
    await userEvent.click(screen.getByRole('button', { name: 'Stop sending' }))

    await waitFor(() => expect(api.setResultsWebhook).toHaveBeenCalledWith(null))
    await waitFor(() =>
      expect(screen.getByLabelText('Where should we post results?')).toHaveValue(''),
    )
    expect(screen.queryByRole('button', { name: 'Stop sending' })).toBeNull()
    expect(screen.queryByText('What we send')).toBeNull()
  })
})

describe('copying the secret', () => {
  it('says so plainly when the clipboard refuses, rather than claiming a copy', async () => {
    vi.mocked(api.setResultsWebhook).mockResolvedValue(
      org({ results_webhook_url: URL, results_webhook_secret: 'kR3vN8pQ2mX7' }),
    )
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    })
    await loaded()
    await userEvent.type(screen.getByLabelText('Where should we post results?'), URL)
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Copy' }))

    expect(await screen.findByText(/select the secret and copy it/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy' })).toBeInTheDocument()
  })
})
