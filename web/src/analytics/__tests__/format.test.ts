import { describe, expect, it } from 'vitest'
import {
  bucketClass,
  formatDuration,
  meterClass,
  ordinal,
  pct,
  percentileLabel,
  score,
} from '../format'

describe('analytics format helpers', () => {
  it('pct: fraction -> percentage, null -> dash', () => {
    expect(pct(0.58)).toBe('58%')
    expect(pct(1)).toBe('100%')
    expect(pct(null)).toBe('—')
    expect(pct(undefined)).toBe('—')
  })

  it('score: rounds to one decimal, null -> dash', () => {
    expect(score(71.42)).toBe('71.4')
    expect(score(80, 0)).toBe('80')
    expect(score(null)).toBe('—')
  })

  it('formatDuration: compact h/m/s, null -> dash', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(45)).toBe('45s')
    expect(formatDuration(372)).toBe('6m 12s') // 6*60 + 12
    expect(formatDuration(3720)).toBe('1h 02m') // 1h 2m
  })

  it('meterClass: green (default) / warn / bad by rate', () => {
    expect(meterClass(0.8)).toBe('')
    expect(meterClass(0.55)).toBe('warn')
    expect(meterClass(0.2)).toBe('bad')
    expect(meterClass(null)).toBe('')
  })

  it('ordinal: handles the 11-13 exception', () => {
    expect(ordinal(1)).toBe('1st')
    expect(ordinal(2)).toBe('2nd')
    expect(ordinal(3)).toBe('3rd')
    expect(ordinal(11)).toBe('11th')
    expect(ordinal(13)).toBe('13th')
    expect(ordinal(22)).toBe('22nd')
    expect(ordinal(100)).toBe('100th')
  })

  it('percentileLabel: fraction -> ordinal, null -> dash', () => {
    expect(percentileLabel(0.83)).toBe('83rd')
    expect(percentileLabel(1)).toBe('100th')
    expect(percentileLabel(null)).toBe('—')
  })

  it('bucketClass: red < 40, amber 40-60, green >= 60', () => {
    expect(bucketClass(0)).toBe('lo')
    expect(bucketClass(20)).toBe('lo')
    expect(bucketClass(40)).toBe('mid')
    expect(bucketClass(60)).toBe('hi')
    expect(bucketClass(80)).toBe('hi')
  })
})
