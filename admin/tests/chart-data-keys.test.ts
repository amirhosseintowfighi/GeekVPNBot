import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * Every `dataKey` must name a field the payload carries.
 *
 * The revenue chart's x-axis read `dataKey="date"`. No point has a `date` -
 * they have `at` and `labelFa` - so every tick formatted `undefined` and the
 * axis rendered as "NaN اسفند" across its whole width, under a line that was
 * plotted perfectly well from `value`.
 *
 * A `dataKey` is a string Recharts resolves at runtime. TypeScript sees a
 * string literal and is satisfied, which is why this is checked here against
 * the interfaces the charts are fed.
 */

const CHART = path.resolve(__dirname, '../src/components/charts/chart.tsx')
const TYPES = path.resolve(__dirname, '../src/lib/types.ts')

function fieldsOf(iface: string): string[] {
  const source = fs.readFileSync(TYPES, 'utf8')
  const match = source.match(new RegExp(`export interface ${iface} \\{([^}]*)\\}`))
  if (!match) throw new Error(`${iface} is gone from types.ts`)
  return [...match[1]!.matchAll(/^\s*(\w+)\??:/gm)].map((m) => m[1]!)
}

describe('chart data keys', () => {
  it('all name a field of the point types the charts are given', () => {
    // Comments stripped first: this file's own explanation quotes the key
    // that was wrong, and a test that reads prose as code fails on the fix.
    const source = fs
      .readFileSync(CHART, 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, '')
    const keys = [...source.matchAll(/dataKey="(\w+)"/g)].map((m) => m[1]!)
    const known = new Set([
      ...fieldsOf('TimeSeriesPoint'),
      ...fieldsOf('BreakdownSlice'),
    ])

    expect(keys.length).toBeGreaterThan(0)
    expect(keys.filter((key) => !known.has(key))).toEqual([])
  })
})
