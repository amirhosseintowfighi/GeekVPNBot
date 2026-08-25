import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

import * as motion from '@/lib/motion'

/**
 * Every variant name a component animates to must exist.
 *
 * `StaggerList` animated to "show" while every variant set in `lib/motion`
 * defines "visible". Framer resolves the missing name to nothing, so the
 * children never left `initial="hidden"` - opacity 0, forever. No error, no
 * warning, just a list that renders as empty space. The shop page looked like
 * a product with no packages and no way to buy.
 *
 * A typo in a string that names a key in another file is invisible to
 * TypeScript, which is why it is checked here instead.
 */

const SRC = path.resolve(__dirname, '../src')

function tsxFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return tsxFiles(full)
    return entry.name.endsWith('.tsx') ? [full] : []
  })
}

const known = new Set(
  Object.values(motion)
    .filter((value): value is Record<string, unknown> =>
      Boolean(value) && typeof value === 'object' && !Array.isArray(value),
    )
    .flatMap((variants) => Object.keys(variants)),
)

describe('variant names used in components', () => {
  it('all exist in lib/motion', () => {
    const missing: string[] = []

    for (const file of tsxFiles(SRC)) {
      const source = fs.readFileSync(file, 'utf8')
      for (const match of source.matchAll(
        /\b(?:initial|animate|exit|whileTap|whileHover)="([a-zA-Z]+)"/g,
      )) {
        if (!known.has(match[1]!)) {
          missing.push(`${path.relative(SRC, file)}: "${match[1]}"`)
        }
      }
    }

    expect(missing).toEqual([])
  })
})
