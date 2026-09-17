import { describe, expect, it } from 'vitest'
import { clockOffsetMs, formatRemaining, serverNow, timerClass } from '../candidateTimer'

describe('clockOffsetMs (R2-028)', () => {
  it('measures how far the browser clock sits from the server', () => {
    const received = Date.parse('2026-09-17T12:00:00Z')
    // Browser five minutes fast: the server's "now" is five minutes behind it.
    expect(clockOffsetMs('2026-09-17T11:55:00Z', received)).toBe(-5 * 60_000)
    // Browser three minutes slow.
    expect(clockOffsetMs('2026-09-17T12:03:00Z', received)).toBe(3 * 60_000)
    // Agreeing clocks need no correction.
    expect(clockOffsetMs('2026-09-17T12:00:00Z', received)).toBe(0)
  })

  it('reads an offsetless server stamp as no correction', () => {
    // The API serialises UTC with a trailing Z; a value that somehow arrives
    // without one must not be read as local time and become an hours-long skew.
    const received = Date.parse('2026-09-17T12:00:00Z')
    expect(clockOffsetMs('2026-09-17T12:00:00', received)).toBe(0)
  })

  it('is what a countdown counts against', () => {
    const received = Date.parse('2026-09-17T12:00:00Z')
    const offset = clockOffsetMs('2026-09-17T11:55:00Z', received)
    const deadline = Date.parse('2026-09-17T12:05:00Z') // server time
    // Ten minutes left on the server's clock, not the five the browser thinks.
    expect(deadline - serverNow(offset, received)).toBe(10 * 60_000)
  })
})

describe('formatRemaining', () => {
  it('floors at zero and grows an hours field', () => {
    expect(formatRemaining(-5_000)).toBe('0:00')
    expect(formatRemaining(65_000)).toBe('1:05')
    expect(formatRemaining(3_725_000)).toBe('1:02:05')
  })
})

describe('timerClass', () => {
  it('escalates under five minutes and under one', () => {
    expect(timerClass(10 * 60_000)).toBe('timer')
    expect(timerClass(4 * 60_000)).toBe('timer warn')
    expect(timerClass(30_000)).toBe('timer crit')
  })
})
