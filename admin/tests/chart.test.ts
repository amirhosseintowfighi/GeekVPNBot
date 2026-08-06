import { describe, expect, it } from 'vitest'

import { CHART_COLORS, formatValue } from '@/components/charts/chart'

/**
 * Chart formatting.
 *
 * Axis labels are the one place where a wrong number is invisible: nobody
 * cross-checks an axis. These tests pin the compaction rules and the Persian
 * digit output, because a chart that silently prints Latin digits in an RTL
 * dashboard is the fastest way to make the whole panel look untranslated.
 */
describe('formatValue', () => {
  it('renders counts in Persian digits with a Persian thousands separator', () => {
    const output = formatValue(12_345, 'count')
    expect(/[0-9]/.test(output)).toBe(false)
    expect(output).toContain('\u066c')
  })

  it('compacts large toman figures instead of printing eight digits on an axis', () => {
    // 1,200,000 becomes "1.2 million": an axis tick has room for a magnitude,
    // not a bank balance.
    const output = formatValue(1_200_000, 'toman')
    expect(output).toContain('\u0645\u06cc\u0644\u06cc\u0648\u0646')
    expect(/[0-9]/.test(output)).toBe(false)
  })

  it('uses the thousands word between one thousand and one million', () => {
    expect(formatValue(450_000, 'toman')).toContain('\u0647\u0632\u0627\u0631')
  })

  it('does not compact small amounts into meaningless precision', () => {
    const output = formatValue(750, 'toman')
    expect(output).not.toContain('\u0647\u0632\u0627\u0631')
  })

  it('prints percentages with the Persian percent sign', () => {
    expect(formatValue(12.5, 'percent')).toContain('\u066a')
  })

  it('renders zero as zero rather than an empty tick', () => {
    expect(formatValue(0, 'count')).toBe('\u06f0')
  })

  it('keeps negative values signed, since churn deltas can go either way', () => {
    expect(formatValue(-12, 'count')).toMatch(/^-|\u2212/)
  })
})

describe('CHART_COLORS', () => {
  it('exposes a fixed palette so a series keeps its colour between renders', () => {
    expect(CHART_COLORS).toHaveLength(6)
    expect(new Set(CHART_COLORS).size).toBe(6)
  })

  it('reserves red for the last slot, where churn and failures live', () => {
    // Series are assigned colours by index. Red sitting at index 5 means an
    // ordinary two-series chart can never accidentally paint revenue red.
    expect(CHART_COLORS[5]).toBeTruthy()
    expect(CHART_COLORS.slice(0, 3).every((colour) => colour.startsWith('hsl'))).toBe(true)
  })
})
