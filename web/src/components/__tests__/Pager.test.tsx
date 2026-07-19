import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Pager } from '../Pager'

describe('Pager', () => {
  it('renders nothing when everything fits on one page', () => {
    const { container } = render(
      <Pager total={80} limit={100} offset={0} onChange={vi.fn()} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the range and disables Prev on the first page', () => {
    render(<Pager total={247} limit={100} offset={0} onChange={vi.fn()} />)
    expect(screen.getByText(/1–100/)).toBeInTheDocument()
    expect(screen.getByText('247')).toBeInTheDocument()
    expect(screen.getByText(/Page 1 of 3/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /prev/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /next/i })).toBeEnabled()
  })

  it('clamps the range and disables Next on the last page', () => {
    render(<Pager total={247} limit={100} offset={200} onChange={vi.fn()} />)
    expect(screen.getByText(/201–247/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /next/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /prev/i })).toBeEnabled()
  })

  it('steps the offset by a page on Next and Prev', async () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <Pager total={247} limit={100} offset={100} onChange={onChange} />,
    )
    await userEvent.click(screen.getByRole('button', { name: /next/i }))
    expect(onChange).toHaveBeenLastCalledWith(200)

    rerender(<Pager total={247} limit={100} offset={100} onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: /prev/i }))
    expect(onChange).toHaveBeenLastCalledWith(0)
  })
})
