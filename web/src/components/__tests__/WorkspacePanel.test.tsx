/** P3b — Settings → Workspace. Branding belongs to the organisation now, so
 *  the interesting question is what each role is shown, not just what saves. */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspacePanel } from '../WorkspacePanel'
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
  return {
    api: {
      getOrg: vi.fn(),
      renameOrg: vi.fn(),
      setOrgLogo: vi.fn(),
      clearOrgLogo: vi.fn(),
    },
    ApiError,
    logoSrc: (sha: string) => `/logos/${sha}`,
  }
})

const org = (over: Partial<Organization> = {}): Organization => ({
  id: 1,
  name: 'Acme Corp',
  role: 'admin',
  member_count: 2,
  logo_sha: null,
  retention_days: null,
  results_webhook_url: null,
  results_webhook_secret: null,
  ...over,
})

function pngFile(name = 'logo.png') {
  return new File([new Uint8Array([0x89, 0x50, 0x4e, 0x47])], name, { type: 'image/png' })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getOrg).mockResolvedValue(org())
})

describe('Workspace branding — an admin', () => {
  it('shows the organisation’s name and the empty logo well', async () => {
    render(<WorkspacePanel />)

    expect(await screen.findByLabelText(/organization name/i)).toHaveValue('Acme Corp')
    expect(screen.getByText(/no logo/i)).toBeInTheDocument()
    expect(screen.getByText(/upload logo/i)).toBeInTheDocument()
    // Nothing to remove yet.
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
  })

  it('uploads the chosen file immediately and shows what came back', async () => {
    const user = userEvent.setup()
    vi.mocked(api.setOrgLogo).mockResolvedValue(org({ logo_sha: 'abc123' }))
    render(<WorkspacePanel />)
    await screen.findByLabelText(/organization name/i)

    const file = pngFile()
    await user.upload(screen.getByLabelText(/choose|upload logo|replace logo/i), file)

    await waitFor(() => expect(api.setOrgLogo).toHaveBeenCalledWith(file))
    // The address the server returned, not a local preview of the file they
    // picked: the stored image is the re-encoded one, and the preview must show
    // what candidates will actually get.
    const shown = await screen.findAllByRole('img')
    expect(shown[0]).toHaveAttribute('src', '/logos/abc123')
    expect(screen.getByRole('button', { name: /remove/i })).toBeInTheDocument()
  })

  it('refuses an oversized file before uploading it', async () => {
    const user = userEvent.setup()
    render(<WorkspacePanel />)
    await screen.findByLabelText(/organization name/i)

    const big = new File([new Uint8Array(300 * 1024)], 'huge.png', { type: 'image/png' })
    await user.upload(screen.getByLabelText(/upload logo/i), big)

    expect(await screen.findByRole('alert')).toHaveTextContent(/300 KB.*limited to 256 KB/i)
    // Not sent: the body-size middleware would have answered in bytes, with a
    // different number, after the whole file went over the wire.
    expect(api.setOrgLogo).not.toHaveBeenCalled()
  })

  it('says why an upload was refused instead of failing silently', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.setOrgLogo).mockRejectedValue(
      new ApiError(422, 'that file is 900 KB; logos are limited to 256 KB.'),
    )
    render(<WorkspacePanel />)
    await screen.findByLabelText(/organization name/i)

    await user.upload(screen.getByLabelText(/upload logo/i), pngFile())

    expect(await screen.findByRole('alert')).toHaveTextContent(/limited to 256 KB/i)
    // Still offering the control, because a different file would work.
    expect(screen.getByText(/upload logo/i)).toBeInTheDocument()
  })

  it('removes the logo and falls back to the name alone', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getOrg).mockResolvedValue(org({ logo_sha: 'abc123' }))
    vi.mocked(api.clearOrgLogo).mockResolvedValue(org({ logo_sha: null }))
    render(<WorkspacePanel />)

    await user.click(await screen.findByRole('button', { name: /remove/i }))

    await waitFor(() => expect(api.clearOrgLogo).toHaveBeenCalled())
    expect(await screen.findByText(/no logo/i)).toBeInTheDocument()
    expect(screen.getByText(/acme corp — coding assessment/i)).toBeInTheDocument()
  })

  it('only offers to save a name that actually changed', async () => {
    const user = userEvent.setup()
    vi.mocked(api.renameOrg).mockResolvedValue(org({ name: 'Acme Inc' }))
    render(<WorkspacePanel />)

    const save = await screen.findByRole('button', { name: /save name/i })
    expect(save).toBeDisabled()

    const field = screen.getByLabelText(/organization name/i)
    await user.clear(field)
    await user.type(field, 'Acme Inc')
    expect(save).toBeEnabled()
    await user.click(save)

    await waitFor(() => expect(api.renameOrg).toHaveBeenCalledWith('Acme Inc'))
    expect(await screen.findByText(/^saved\.$/i)).toBeInTheDocument()
  })

  it('previews the saved name, not the one being typed', async () => {
    const user = userEvent.setup()
    render(<WorkspacePanel />)

    const field = await screen.findByLabelText(/organization name/i)
    await user.type(field, ' typing…')

    // The preview claims what candidates will see. Until the save lands, that
    // is still the old name.
    expect(screen.getByText(/acme corp — coding assessment/i)).toBeInTheDocument()
  })
})

describe('Workspace branding — a member', () => {
  beforeEach(() => {
    vi.mocked(api.getOrg).mockResolvedValue(org({ role: 'member', logo_sha: 'abc123' }))
  })

  it('sees the logo and the preview and not one control', async () => {
    render(<WorkspacePanel />)

    // The result is information about their own assessments, so it stays…
    expect(await screen.findByText(/what the candidate sees/i)).toBeInTheDocument()
    expect(screen.getAllByRole('img')[0]).toHaveAttribute('src', '/logos/abc123')
    // …and every way of changing it is absent, not disabled.
    expect(screen.queryByLabelText(/organization name/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/upload logo|replace logo/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /save name/i })).not.toBeInTheDocument()
    // Not even a note naming the option they cannot reach.
    expect(screen.queryByText(/only an admin/i)).not.toBeInTheDocument()
  })
})
